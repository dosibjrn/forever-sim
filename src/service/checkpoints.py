from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any

from src.forever_build import request_identity


class Compatibility(str, Enum):
    RESUME = "resume"
    SEED_ONLY = "seed_only"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class CheckpointManifest:
    job_id: str
    attempt_id: str
    path: str
    kind: str
    created_at: float
    size_bytes: int
    sha256: str
    request: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compatibility_detail(checkpoint_request: dict[str, Any], target_request: dict[str, Any]) -> dict[str, Any]:
    """Return compatibility plus stable, user-facing drift reasons.

    The classifier is intentionally request-only: integrity/hash verification is
    performed when a state is selected/staged, while this function explains why
    otherwise-valid saved state may or may not be reused for a target request.
    """
    hard_labels = {
        "ruleset": "ruleset drift",
        "class_name": "class drift",
        "endpoint_mode": "endpoint drift",
    }
    reasons = [label for key, label in hard_labels.items()
               if checkpoint_request.get(key) != target_request.get(key)]
    if reasons:
        return {"compatibility": Compatibility.INCOMPATIBLE.value, "reasons": reasons}

    cp_build, cp_legacy = request_identity(checkpoint_request)
    target_build, target_legacy = request_identity(target_request)
    if cp_build != target_build:
        reasons.append("Forever build drift")

    exact_labels = {
        "start_level": "level scope drift",
        "end_level": "level scope drift",
        "objective": "objective drift",
        "source_snapshot": "source drift",
        "engine_semantic_hash": "semantic drift",
        "policy_space_version": "policy drift",
        "config": "config drift",
        "validation_modes": "validation config drift",
    }
    for key, label in exact_labels.items():
        if checkpoint_request.get(key) != target_request.get(key) and label not in reasons:
            reasons.append(label)
    if reasons:
        return {"compatibility": Compatibility.SEED_ONLY.value, "reasons": reasons}
    exact_reason = "exact semantic/source/policy/config/build cohort"
    if cp_legacy or target_legacy:
        exact_reason += f"; legacy Forever artifact assumes {cp_build or target_build}"
    return {"compatibility": Compatibility.RESUME.value, "reasons": [exact_reason]}


def decorate_saved_states(checkpoints: list[dict[str, Any]], target_request: dict[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
    out=[]
    for cp in checkpoints[:max(1, int(limit))]:
        item=dict(cp)
        item.update(compatibility_detail(cp.get("request") or {}, target_request))
        out.append(item)
    return out


def classify_compatibility(checkpoint_request: dict[str, Any], target_request: dict[str, Any]) -> Compatibility:
    """Classify whether a checkpoint may be resumed, seeded, or must be ignored."""
    return Compatibility(compatibility_detail(checkpoint_request, target_request)["compatibility"])


def discover_checkpoint_files(run_root: str | Path) -> list[Path]:
    root = Path(run_root)
    if not root.exists():
        return []
    # MC owns .pkl checkpoints today. JSON checkpoint/manifest formats are
    # intentionally accepted for future executors without changing the store.
    found: list[Path] = []
    for pattern in ("*.pkl", "checkpoint*.json", "*checkpoint*.json"):
        found.extend(p for p in root.rglob(pattern) if p.is_file() and not p.name.endswith(".tmp"))
    # De-duplicate overlapping JSON globs while preserving deterministic order.
    return sorted(set(found), key=lambda p: (p.stat().st_mtime, str(p)))


def build_manifest(*, job: dict, attempt: dict, path: str | Path, kind: str = "optimizer_checkpoint") -> CheckpointManifest:
    p = Path(path)
    return CheckpointManifest(
        job_id=job["id"],
        attempt_id=attempt["id"],
        path=str(p),
        kind=kind,
        created_at=float(p.stat().st_mtime if p.exists() else time.time()),
        size_bytes=int(p.stat().st_size),
        sha256=file_sha256(p),
        request=dict(job["request"]),
    )


def write_sidecar(manifest: CheckpointManifest) -> Path:
    p = Path(manifest.path)
    sidecar = p.with_suffix(p.suffix + ".manifest.json")
    tmp = sidecar.with_suffix(sidecar.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(sidecar)
    return sidecar


def select_resume_checkpoint(checkpoints: list[dict[str, Any]], target_request: dict[str, Any], *, prefer_job_id: str | None = None) -> dict[str, Any] | None:
    """Pick the newest strict-resume checkpoint, preferring this job's own history.

    Seed-only artifacts are intentionally excluded here: they may inform proposal
    generation later, but they are never copied in as numeric resume state.
    """
    eligible = [cp for cp in checkpoints if classify_compatibility(cp["request"], target_request) is Compatibility.RESUME]
    if not eligible:
        return None
    eligible.sort(key=lambda cp: (cp.get("job_id") == prefer_job_id, float(cp.get("created_at", 0.0)), float(cp.get("discovered_at", 0.0))), reverse=True)
    return eligible[0]


def stage_resume_checkpoint(*, checkpoint: dict[str, Any], source_attempt: dict[str, Any], target_attempt: dict[str, Any]) -> dict[str, Any]:
    """Copy a verified checkpoint into a fresh immutable attempt root.

    The source attempt remains untouched.  We preserve the checkpoint's path
    relative to the old attempt root, because master_optimizer/controller state
    refers to that relative state layout.  Minimal runtime controller/config state
    is copied alongside it when present so a paused MC experiment resumes the
    exact in-flight experiment rather than inventing a new epoch.
    """
    src = Path(checkpoint["path"]); src_root = Path(source_attempt["run_root"]); dst_root = Path(target_attempt["run_root"])
    if not src.exists():
        raise FileNotFoundError(src)
    if file_sha256(src) != checkpoint["sha256"]:
        raise ValueError("checkpoint sha256 mismatch")
    try:
        rel = src.resolve().relative_to(src_root.resolve())
    except ValueError as exc:
        raise ValueError("checkpoint is outside source attempt root") from exc
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

    copied_support: list[str] = []
    for rel_support in (Path("state/runtime/controller.json"), Path("state/config.json")):
        support_src = src_root / rel_support
        if support_src.exists():
            support_dst = dst_root / rel_support
            support_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(support_src, support_dst)
            copied_support.append(str(rel_support))

    return {
        "checkpoint_id": checkpoint["id"],
        "source_job_id": checkpoint["job_id"],
        "source_attempt_id": checkpoint["attempt_id"],
        "source_path": str(src),
        "staged_path": str(dst),
        "sha256": checkpoint["sha256"],
        "support_files": copied_support,
    }

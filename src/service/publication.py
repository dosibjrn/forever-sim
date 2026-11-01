from __future__ import annotations

"""Atomic publication of completed immutable optimizer attempts.

A publication is a tiny manifest that points at an immutable attempt ``state/``
root.  ``current.json`` is the only mutable pointer and is replaced atomically;
therefore readers either see the previous last-good generation or the complete
new generation, never an in-progress attempt.  Publications form an overlay
chain so a Mage-only run can update Mage artifacts without erasing previously
published Paladin/Druid data.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any


class PublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Publication:
    id: str
    job_id: str
    attempt_id: str
    state_root: str
    parent_id: str | None
    created_at: float
    request: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "id": self.id,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "state_root": self.state_root,
            "parent_id": self.parent_id,
            "created_at": self.created_at,
            "request": self.request,
        }


def _service_root(project_root: str | Path) -> Path:
    return Path(project_root) / "state" / "service"


def _publications_root(project_root: str | Path) -> Path:
    return _service_root(project_root) / "publications"


def _current_path(project_root: str | Path) -> Path:
    return _service_root(project_root) / "publication_current.json"


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _manifest_path(project_root: str | Path, publication_id: str) -> Path:
    return _publications_root(project_root) / f"{publication_id}.json"


def read_publication(project_root: str | Path, publication_id: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(_manifest_path(project_root, publication_id).read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def current_publication(project_root: str | Path) -> dict[str, Any] | None:
    try:
        ptr = json.loads(_current_path(project_root).read_text(encoding="utf-8"))
        pid = str(ptr.get("publication_id") or "")
        return read_publication(project_root, pid) if pid else None
    except Exception:
        return None


def publication_chain(project_root: str | Path, *, limit: int = 128) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur = current_publication(project_root)
    while cur and len(out) < limit:
        pid = str(cur.get("id") or "")
        if not pid or pid in seen:
            break
        seen.add(pid); out.append(cur)
        parent = cur.get("parent_id")
        cur = read_publication(project_root, str(parent)) if parent else None
    return out


def resolve_published_path(project_root: str | Path, relative: str | Path) -> Path:
    """Resolve one listener artifact through newest->oldest publication overlays.

    Falls back to the historical canonical ``state/`` layout so existing local
    runs remain readable before the first service publication.
    """
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("publication relative path must stay below state root")
    for pub in publication_chain(project_root):
        root = Path(str(pub.get("state_root") or ""))
        p = root / rel
        if p.exists():
            return p
    return Path(project_root) / "state" / rel


def read_published_class_artifact(project_root: str | Path, relative: str | Path) -> dict[str, Any]:
    """Read a class-keyed JSON artifact through the publication overlay chain.

    Shared decision artifacts (endpoint_paths/spec_regret/dual_spec/spec_matrix)
    contain multiple classes in one file. Path-level overlay alone is insufficient:
    a newer Hunter artifact would shadow an older Druid file wholesale. Merge only
    the top-level ``classes`` mapping newest-first so the latest publication owns
    its classes while untouched classes remain reachable from older generations.
    """
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("publication relative path must stay below state root")
    merged: dict[str, Any] = {}
    classes: dict[str, Any] = {}
    found = False
    for pub in publication_chain(project_root):
        root = Path(str(pub.get("state_root") or ""))
        p = root / rel
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        found = True
        # Newest publication owns non-class metadata. Older generations only fill
        # absent metadata keys; class payloads are overlaid independently.
        for key, value in obj.items():
            if key != "classes" and key not in merged:
                merged[key] = value
        for cls, value in dict(obj.get("classes") or {}).items():
            classes.setdefault(str(cls), value)
    # Historical canonical state is the final fallback for classes never yet
    # published through the service.
    legacy = Path(project_root) / "state" / rel
    if legacy.is_file():
        try:
            obj = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            obj = None
        if isinstance(obj, dict):
            found = True
            for key, value in obj.items():
                if key != "classes" and key not in merged:
                    merged[key] = value
            for cls, value in dict(obj.get("classes") or {}).items():
                classes.setdefault(str(cls), value)
    if not found:
        return {}
    merged["classes"] = classes
    return merged


def _validate_attempt_state(job: dict, attempt: dict) -> Path:
    state_root = Path(attempt["run_root"]) / "state"
    if not state_root.is_dir():
        raise PublicationError("completed attempt has no state directory")
    request = job["request"]
    mode = str(request.get("endpoint_mode") or "")
    ruleset = str(request.get("ruleset") or "")
    cls = str(request.get("class_name") or "")
    if mode in {"smooth", "fast"}:
        viewer = state_root / "games" / f"{ruleset}-{cls}" / "v2" / "viewer.json"
        # classic/mage keeps the legacy non-games namespace.
        if ruleset == "classic" and cls == "mage":
            viewer = state_root / "v2" / "viewer.json"
        if not viewer.is_file():
            raise PublicationError(f"completed v2 attempt missing listener viewer: {viewer}")
        try:
            payload = json.loads(viewer.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PublicationError(f"listener viewer is not valid JSON: {viewer}") from exc
        if not isinstance(payload, dict) or payload.get("running") is True:
            raise PublicationError("listener viewer is incomplete/running")
    elif mode == "generic_decision":
        # G50h: source-only native generic record at an exactly declared level.
        # The request, manifest and DecisionRecord must agree independently.
        from src.version import SOFTWARE_VERSION
        from src.game.data.forever.queue_capabilities import (
            require_native_generic_queue, native_generic_queue_artifact,
        )
        req_class = request.get("class_name")
        req_level = int(request.get("start_level", -1))
        try:
            require_native_generic_queue(req_class, req_level)
        except ValueError as exc:
            raise PublicationError("native queue request outside declared capability") from exc
        path = state_root / native_generic_queue_artifact(req_class, req_level)
        if not path.is_file():
            raise PublicationError("native generic Decision artifact missing")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PublicationError("native generic Decision artifact is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise PublicationError("native generic Decision envelope must be an object")
        decision = payload.get("decision")
        if (payload.get("schema_version") != 1 or payload.get("complete") is not True
                or payload.get("execution_authority") != "native_generic_decision"
                or payload.get("legacy_fallback") is not False
                or payload.get("producer_version") != SOFTWARE_VERSION
                or payload.get("forever_build_as_of") != request.get("forever_build_as_of")
                or request.get("ruleset") != "forever"
                or int(request.get("end_level", -1)) != req_level
                or request.get("objective") != "endpoint"
                or not isinstance(decision, dict)):
            raise PublicationError("native generic Decision envelope/request provenance mismatch")
        identity = decision.get("identity") or {}
        backend = decision.get("backend") or {}
        provenance = decision.get("provenance") or {}
        if (identity.get("ruleset") != "forever" or identity.get("class_name") != req_class
                or identity.get("level") != req_level or identity.get("target_level") != req_level
                or backend.get("id") != "generic" or backend.get("version") != SOFTWARE_VERSION
                or backend.get("independent") is not True
                or provenance.get("source") != "generic_backend_native"
                or provenance.get("legacy_fallback") is not False
                or decision.get("schema_version") != 1
                or not isinstance(decision.get("publication_availability"), dict)):
            raise PublicationError("native generic Decision record provenance mismatch")
    elif mode == "mc":
        # MC can have several valid output shapes depending on first run vs
        # resumed experiment. Require at least one durable listener/runtime
        # surface rather than publishing an empty attempt.
        candidates = [
            state_root / "runtime" / "viewer_snapshot.json",
            state_root / "runtime" / "controller.json",
            state_root / "tracks",
            state_root / "best",
        ]
        if not any(p.exists() for p in candidates):
            raise PublicationError("completed MC attempt has no durable result/runtime surface")
    else:
        raise PublicationError(f"unsupported publication endpoint_mode {mode!r}")
    return state_root.resolve()


def publish_attempt(project_root: str | Path, *, job: dict, attempt: dict) -> dict[str, Any]:
    """Atomically make one completed attempt the newest canonical generation."""
    state_root = _validate_attempt_state(job, attempt)
    current = current_publication(project_root)
    pid = uuid.uuid4().hex
    pub = Publication(
        id=pid,
        job_id=str(job["id"]),
        attempt_id=str(attempt["id"]),
        state_root=str(state_root),
        parent_id=str(current["id"]) if current else None,
        created_at=time.time(),
        request=dict(job["request"]),
    ).to_dict()
    if job["request"].get("endpoint_mode") == "generic_decision":
        from src.game.data.forever.queue_capabilities import native_generic_queue_artifact
        request = job["request"]
        artifact = state_root / native_generic_queue_artifact(
            request["class_name"], int(request["start_level"]))
        pub["native_generic_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    # Manifest is durable first. The single atomic pointer swap is the commit.
    _atomic_write_json(_manifest_path(project_root, pid), pub)
    _atomic_write_json(_current_path(project_root), {"schema_version": 1, "publication_id": pid, "updated_at": time.time()})
    return pub


class QueuedGenericDecisionUnavailable(PublicationError):
    """No current, validated matching native generic queue publication."""


def read_current_queued_generic_decision(project_root: str | Path, *, class_name: str,
                                          level: int, backend: str) -> dict[str, Any]:
    """Explicit queue read: current pointer only; never search legacy/older overlays.

    Recheck the producer's envelope on every read. Pin the publication to its
    committed content hash so post-commit mutation cannot be silently served.
    """
    from src.game.data.forever.queue_capabilities import (
        require_native_generic_queue, native_generic_queue_artifact,
    )
    if backend != "generic":
        raise ValueError("queued native Decisions requires explicit generic backend")
    require_native_generic_queue(class_name, level)
    pub = current_publication(project_root)
    if not pub or not isinstance(pub.get("request"), dict):
        raise QueuedGenericDecisionUnavailable("no current native generic publication")
    if pub["request"].get("endpoint_mode") != "generic_decision":
        raise QueuedGenericDecisionUnavailable("current publication is not a native generic Decision")
    current_request = pub["request"]
    if (current_request.get("class_name") != class_name
            or int(current_request.get("start_level", -1)) != level
            or int(current_request.get("end_level", -1)) != level):
        raise QueuedGenericDecisionUnavailable("current native queue publication has different class/level")
    state_root = Path(str(pub.get("state_root") or ""))
    if not state_root.is_absolute() or state_root.name != "state":
        raise QueuedGenericDecisionUnavailable("invalid native publication state root")
    artifact = state_root / native_generic_queue_artifact(class_name, level)
    try:
        contents = artifact.read_bytes()
        content_hash = pub.get("native_generic_sha256")
        if (not isinstance(content_hash, str) or len(content_hash) != 64
                or hashlib.sha256(contents).hexdigest() != content_hash):
            raise QueuedGenericDecisionUnavailable("native Decision content hash mismatch")
        # Also revalidate producer version, exact request identity and provenance.
        _validate_attempt_state({"request": pub["request"]}, {"run_root": str(state_root.parent)})
        payload = json.loads(contents)
        if current_publication(project_root) != pub:
            raise QueuedGenericDecisionUnavailable("publication changed during native Decision read")
    except (OSError, ValueError, PublicationError) as exc:
        raise QueuedGenericDecisionUnavailable(f"native Decision failed read validation: {exc}") from exc
    return {
        "authority": "queued_native_generic_decision", "legacy_fallback": False,
        "publication_id": pub["id"], "job_id": pub["job_id"],
        "attempt_id": pub["attempt_id"], "producer_version": payload["producer_version"],
        "execution_authority": payload["execution_authority"],
        "forever_build_as_of": payload["forever_build_as_of"],
        "decision": payload["decision"],
    }

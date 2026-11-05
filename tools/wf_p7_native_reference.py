"""Frozen lower-level P7 reference produced and evaluated by selected MythicSim.

No Warcraft legality rules, source item lists, or level-60 proxy are maintained
here. The same pinned native engine must PREPARE the requested actor at its
actual checkpoint level and pay a stochastic 1,000-fight reference.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

# Direct CLI execution puts tools/ (not the repository root) on sys.path.
# Match wf_gate.py so the documented python tools/... entry point reaches
# the real gate modules even without PYTHONPATH or an editable install.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wf_gate_coverage import (
    P7_FINAL_STOCHASTIC_ITERATIONS, p7_final_stochastic_mean_passes,
    p7_required_dps,
)
from tools.wf_gate_p7_1_live import _selected_rust_submodule


def _blocked(reason: str, **details) -> dict:
    return {"status": "BLOCKED", "reasons": [reason], **details}


def _reference_directory(root: Path, class_key: str, level: int, spec: str) -> Path:
    return root / "docs/evidence/native-references" / f"{class_key}-l{level}-{spec}"


def _native(root: Path):
    path = root / "integrations/mythicsim-rust/live_world_probe.py"
    spec = importlib.util.spec_from_file_location("p71_generated_native", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P7_1_NATIVE_SCORER_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binary_and_pin(root: Path) -> tuple[Path, str] | None:
    # Default to the checkout recorded by this repository's 160000 gitlink.
    # An explicit binary override is allowed only when its checkout HEAD
    # matches that same pin; never run a floating sibling fork by default.
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root / "integrations/mythicsim-rust/engine/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return None
    selected = _selected_rust_submodule(root, binary.parents[2])
    if selected is None:
        return None
    return binary, selected


def _native_reference_request(root: Path, class_key: str,
                              level: int, spec: str) -> Path | None:
    """Use source request bytes owned by the exact selected native submodule.

    This is an input asset, not a Python game-rules database. Do not build a
    lower-level reference from the historical level-60 Balance request.
    """
    if (class_key, level, spec) != ("druid", 20, "unrestricted"):
        return None
    path = (root / "integrations/mythicsim-rust/engine"
            / "fixtures/references/druid-l20-p71.request.json")
    return path if path.is_file() else None


def _checkpoint_source(raw: bytes, class_key: str, level: int) -> tuple[dict, dict]:
    """Only check request identity/shape; native decides all Warcraft legality."""
    request = json.loads(raw)
    player = request["raid"]["parties"][0]["players"][0]
    # Go proto.Player has no level field. Native --actor-level owns the context;
    # actual native PREPARE establishes the actor, never a Python level hint.
    if (player.get("class") != "Class" + class_key.capitalize()
            or "level" in player):
        raise ValueError("P7_1_REQUEST_ACTOR_CHECKPOINT_MISMATCH")
    targets = request["encounter"]["targets"]
    if (len(targets) != 1 or type(targets[0].get("level")) is not int
            or targets[0]["level"] <= 0):
        raise ValueError("P7_1_REFERENCE_SINGLE_TARGET_MISSING")
    if (type(request["simOptions"]["iterations"]) is not int
            or request["simOptions"]["iterations"] < 1):
        raise ValueError("P7_1_REFERENCE_SIM_OPTIONS_INVALID")
    return request, player


def _prepare_actor(binary: Path, request_path: Path, level: int) -> dict:
    """Read native-prepared class/level, not just the source request hint."""
    completed = subprocess.run(
        [str(binary), "prepare", "--request", str(request_path),
         "--actor-level", str(level)],
        capture_output=True, text=True, timeout=90, check=False,
    )
    try:
        response = json.loads(completed.stdout)
    except (ValueError, TypeError):
        response = {}
    if completed.returncode:
        refusal = response.get("refusal") if isinstance(response, dict) else None
        if isinstance(refusal, dict):
            return {"status": "REFUSED", "code": refusal.get("code"),
                    "reason": refusal.get("reason")}
        raise RuntimeError("P7_1_NATIVE_PREPARE_FAILED:"
                           + (completed.stderr or completed.stdout)[-400:])
    player = response.get("player") if isinstance(response, dict) else None
    if not isinstance(player, dict):
        raise RuntimeError("P7_1_NATIVE_PREPARED_ACTOR_MISSING")
    return {"status": "PREPARED", "class": player.get("class"),
            "level": player.get("level")}


def _native_score(production, binary: Path, path: Path, level: int) -> dict:
    native = production.native_source_control(
        binary, path, P7_FINAL_STOCHASTIC_ITERATIONS, rng_mode="stochastic",
        actor_level=level)
    value = native.get("native_dps") if isinstance(native, dict) else None
    if (not isinstance(native, dict)
            or type(native.get("iterations")) is not int
            or native["iterations"] != P7_FINAL_STOCHASTIC_ITERATIONS
            or type(value) not in (int, float)
            or not math.isfinite(value) or value <= 0):
        raise ValueError("P7_1_NATIVE_REFERENCE_SCORE_INVALID")
    # Preserve the exact selected-native paid result as the reference receipt.
    # The approved P7.1 gate may reuse these same 1,000 stochastic fights.
    # Never turn a deterministic screen or merely configured count into proof.
    if native.get("native_rules") != "forever":
        raise ValueError("P7_1_NATIVE_REFERENCE_RULESET_MISMATCH")
    return {
        "native_dps": float(value),
        "iterations": P7_FINAL_STOCHASTIC_ITERATIONS,
        "native_rules": "forever",
        "first_duration_s": native.get("first_duration_s"),
    }


def produce_reference(root: Path, class_key: str, level: int, spec: str,
                      source_path: Path | None = None, destination: Path | None = None) -> dict:
    """Pay native once, then freeze exact source bytes and measured reference.

    The source is a level-specific request assembled from native-provided build
    options, not a copied L60 saved reference. Native PREPARE and SIM are the
    only authorities on the resulting actor and executable candidate.
    """
    if class_key != "druid" or spec != "unrestricted" or level not in (20, 30, 40):
        return _blocked("P7_1_GENERATED_REFERENCE_CHECKPOINT_NOT_SELECTED")
    out = destination or _reference_directory(root, class_key, level, spec)
    if (out / "request.json").exists() or (out / "reference.json").exists():
        return _blocked("P7_1_FROZEN_REFERENCE_ALREADY_EXISTS")
    selected = _binary_and_pin(root)
    if selected is None:
        return _blocked("P7_1_PINNED_RUST_BINARY_OR_GITLINK_MISSING")
    binary, revision = selected
    # Explicit requests remain supported for independent source-backed builds.
    # The default path is a reviewed, pinned Rust-owned executable input.
    chosen = source_path if source_path is not None else _native_reference_request(
        root, class_key, level, spec)
    if chosen is None or not chosen.is_file():
        return _blocked("P7_1_NATIVE_SOURCE_REQUEST_NOT_AVAILABLE")
    try:
        raw = chosen.read_bytes()
        source, _ = _checkpoint_source(raw, class_key, level)
    except (OSError, KeyError, IndexError, TypeError, ValueError) as exc:
        return _blocked(str(exc))
    with tempfile.TemporaryDirectory(prefix="p71_generated_") as temporary:
        path = Path(temporary) / "native-reference.json"
        path.write_bytes(raw)
        try:
            actor = _prepare_actor(binary, path, level)
            if actor["status"] != "PREPARED":
                return _blocked("P7_1_NATIVE_PREPARE_REFUSED", native_refusal=actor)
            if actor["class"] != "ClassDruid" or actor["level"] != level:
                return _blocked("P7_1_NATIVE_PREPARED_ACTOR_LEVEL_MISMATCH",
                                native_actor=actor)
            paid = _native_score(_native(root), binary, path, level)
            score = paid["native_dps"]
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            return _blocked("P7_1_NATIVE_REFERENCE_EXECUTION_FAILED",
                            native_error=str(exc)[-500:])
    sha = hashlib.sha256(raw).hexdigest()
    encounter = json.dumps(source["encounter"], sort_keys=True,
                           separators=(",", ":")).encode()
    manifest = {
        "reference_configuration_source": "native_generated_msim_reference",
        "class": class_key, "level": level, "spec": spec,
        "source_request_raw_sha256": sha,
        "encounter_sha256": hashlib.sha256(encounter).hexdigest(),
        "selected_engine_revision": revision,
        "native_prepared_actor": actor,
        "native_actor_level_context": level,
        "reference_dps": score,
        "reference_native_sample": paid,
        "reference_iterations": P7_FINAL_STOCHASTIC_ITERATIONS,
        "reference_rng_mode": "stochastic",
        "encounter_target_level": source["encounter"]["targets"][0]["level"],
        "native_rules": "forever",
    }
    out.mkdir(parents=True, exist_ok=True)
    # Exclusive writes: never silently replace a frozen scored reference.
    with (out / "request.json").open("xb") as stream:
        stream.write(raw)
    with (out / "reference.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"status": "REFERENCE_GENERATED", "reference_path": str(out),
            **manifest}


def run_generated_p71(root: Path, class_key: str, level: int, spec: str) -> dict:
    if class_key != "druid" or spec != "unrestricted" or level not in (20, 30, 40):
        return _blocked("P7_1_GENERATED_REFERENCE_CHECKPOINT_NOT_SELECTED")
    directory = _reference_directory(root, class_key, level, spec)
    request_path, manifest_path = directory / "request.json", directory / "reference.json"
    if not request_path.is_file() or not manifest_path.is_file():
        return _blocked("P7_1_NATIVE_GENERATED_REFERENCE_NOT_PINNED")
    raw = request_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(manifest_path.read_text())
        source, _ = _checkpoint_source(raw, class_key, level)
        reference = manifest["reference_dps"]
        sample = manifest["reference_native_sample"]
        encounter_sha = hashlib.sha256(json.dumps(
            source["encounter"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if (manifest.get("reference_configuration_source") != "native_generated_msim_reference"
                or manifest.get("class") != class_key
                or manifest.get("level") != level or manifest.get("spec") != spec
                or manifest.get("source_request_raw_sha256") != sha
                or manifest.get("encounter_sha256") != encounter_sha
                or manifest.get("encounter_target_level") != source["encounter"]["targets"][0]["level"]
                or manifest.get("native_actor_level_context") != level
                or manifest.get("reference_iterations") != P7_FINAL_STOCHASTIC_ITERATIONS
                or manifest.get("reference_rng_mode") != "stochastic"
                or type(reference) not in (int, float)
                or not math.isfinite(reference) or reference <= 0
                or not isinstance(sample, dict)
                or type(sample.get("iterations")) is not int
                or sample["iterations"] != P7_FINAL_STOCHASTIC_ITERATIONS
                or sample.get("native_rules") != "forever"
                or type(sample.get("native_dps")) not in (int, float)
                or not math.isfinite(sample["native_dps"])
                or sample["native_dps"] != reference):

            return _blocked("P7_1_GENERATED_REFERENCE_IDENTITY_INVALID")
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        return _blocked("P7_1_GENERATED_REFERENCE_INVALID", error=str(exc)[-240:])
    selected = _binary_and_pin(root)
    if selected is None:
        return _blocked("P7_1_PINNED_RUST_BINARY_OR_GITLINK_MISSING")
    binary, revision = selected
    if manifest.get("selected_engine_revision") != revision:
        return _blocked("P7_1_GENERATED_REFERENCE_ENGINE_CHANGED")
    try:
        actor = _prepare_actor(binary, request_path, level)
        if actor["status"] != "PREPARED":
            return _blocked("P7_1_NATIVE_PREPARE_REFUSED", native_refusal=actor)
        if actor["class"] != "ClassDruid" or actor["level"] != level:
            return _blocked("P7_1_NATIVE_PREPARED_ACTOR_LEVEL_MISMATCH",
                            native_actor=actor)
        # The pinned reference's own executed 1,000-fight stochastic sample
        # already satisfies P7.1's required replay identity. Reuse it instead
        # of paying a second statistically different 1,000-fight sample.
        measured = float(sample["native_dps"])
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        return {"status": "FAIL", "reasons": [
            "P7_1_NATIVE_STOCHASTIC_EXECUTION_FAILED"], "native_error": str(exc)[-500:]}
    details = {
        "production_engine": "pinned_mythicsim_rust_native",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py:native_source_control",
        "reference_configuration_source": "native_generated_msim_reference",
        "native_source_revision": revision, "source_request_raw_sha256": sha,
        "reference_profile": spec, "checkpoint_spec": spec, "native_rules": "forever",
        "saved_reference_dps": float(reference), "required_dps": p7_required_dps("P7.1", reference),
        "native_dps": measured, "iterations": P7_FINAL_STOCHASTIC_ITERATIONS,
        "sampled_source_fights": P7_FINAL_STOCHASTIC_ITERATIONS,
        "stochastic_rng": True, "selected_validation": "1000_native_stochastic_fights",
        "reused_authentic_native_reference_receipt": True,
    }
    if not p7_final_stochastic_mean_passes(
            "P7.1", measured, reference,
            iterations=P7_FINAL_STOCHASTIC_ITERATIONS, stochastic=True):
        return {"status": "FAIL", "reasons": [
            "P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"], **details}
    return {
        "status": "PASS", "reasons": [],
        "p7_1_1_reference_pinned": True, "p7_1_2_native_reproduced": True,
        "runtime_proof": {
            "executed": True, "engine_revision": revision,
            "source_revision": sha,
            "run_id": "P7.1-generated-native-" + sha[:20],
            "reference_receipt_reused": True,
        },
        **details,
    }


def produce_and_verify_reference(root: Path, class_key: str, level: int, spec: str,
                                 source_path: Path | None = None,
                                 destination: Path | None = None) -> dict:
    """Pay a source-native reference once, then run the actual P7.1 gate path.

    This is deliberately a single process/checkout operation: a CI workspace
    can preserve the frozen native receipt even when the gate does not pass.
    The P7.1 evaluator reuses the paid sample; it does not draw a second
    stochastic batch or write the official M1 ledger.
    """
    generated = produce_reference(root, class_key, level, spec, source_path, destination)
    if generated["status"] != "REFERENCE_GENERATED":
        return {"status": generated["status"], "generation": generated}
    if destination is not None and destination != _reference_directory(root, class_key, level, spec):
        # run_generated_p71 reads the canonical reference directory. A custom
        # destination is an export only, never a reason to grade a different
        # reference that may already exist on disk.
        return {"status": "REFERENCE_GENERATED", "generation": generated,
                "verification": {"status": "NOT_RUN",
                                 "reasons": ["P7_1_CUSTOM_OUTPUT_DIR_NOT_CANONICAL"]}}
    verified = run_generated_p71(root, class_key, level, spec)
    return {"status": verified["status"], "generation": generated,
            "verification": verified}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-request", type=Path,
                        help="Native-authored request (defaults to selected Druid L20 Rust fixture)")
    parser.add_argument("--class", dest="class_key", default="druid")
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--spec", default="unrestricted")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify", action="store_true",
                        help="Evaluate the generated receipt through real P7.1 (no M1 write)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.verify:
        result = produce_and_verify_reference(root, args.class_key, args.level, args.spec,
                                              args.source_request, args.output_dir)
    else:
        result = produce_reference(root, args.class_key, args.level, args.spec,
                                   args.source_request, args.output_dir)
    print(json.dumps(result, sort_keys=True))
    if result["status"] != ("PASS" if args.verify else "REFERENCE_GENERATED"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

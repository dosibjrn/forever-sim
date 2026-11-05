"""P7.1 selected-native generated reference: real L20 actor or no gate credit.

Capture pays the actual Rust 1,000 stochastic fight sample and emits a frozen
request/receipt. Only source-verified L20 may be frozen; no game rules in Python.
Existing saved L60 references are not copied or reinterpreted.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from tools.wf_gate_p7_1_live import _selected_rust_submodule
from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_required_dps,
                                    p7_final_stochastic_mean_passes)

BASE = Path("docs/evidence/druid-l20-unrestricted/p7.1")
REQUEST = "native_reference_request.json"
RECEIPT = "native_reference.json"
FIGHTS = P7_FINAL_STOCHASTIC_ITERATIONS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blocked(reason, **details):
    return {"status": "BLOCKED", "reasons": [reason], **details}


def native_module(root):
    path = root / "integrations/mythicsim-rust/live_world_probe.py"
    spec = importlib.util.spec_from_file_location("native_p71_l20", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P7_1_NATIVE_SOURCE_CONTROL_UNAVAILABLE")
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def selected_pin(root, binary):
    if not binary.is_file():
        return None
    return _selected_rust_submodule(root, binary.parents[2])


def source_identity(raw):
    doc = json.loads(raw)
    players = [p for party in doc["raid"]["parties"] for p in party["players"]]
    targets = doc["encounter"]["targets"]
    if len(players) != 1 or len(targets) != 1:
        raise ValueError("P7_1_SINGLE_ACTOR_SINGLE_TARGET_REQUIRED")
    if players[0].get("class") != "ClassDruid" or targets[0].get("level") != 23:
        raise ValueError("P7_1_NATIVE_L20_SOURCE_CLASS_OR_TARGET_MISMATCH")
    return doc


def native_prepared_actor(binary, request):
    with tempfile.TemporaryDirectory(prefix="p71-l20-prepare-") as tmp:
        result = Path(tmp) / "prepared.json"
        proc = subprocess.run(
            [str(binary), "prepare", "--request", str(request), "--outfile", str(result)],
            capture_output=True, text=True, timeout=120, check=False)
        if proc.returncode:
            raise RuntimeError("P7_1_NATIVE_PREPARE_REFUSED:"
                               + (proc.stdout or proc.stderr)[-800:])
        prepared = json.loads(result.read_text())
    actor = prepared.get("player") or {}
    if actor.get("class") != "ClassDruid" or actor.get("level") != 20:
        raise ValueError("P7_1_NATIVE_ACTOR_LEVEL_MISMATCH:"
                         + str((actor.get("class"), actor.get("level"))))
    return prepared["request_sha256"]


def capture(root, binary, request, output):
    """No invented score: emit receipt only after actual L20 preparation+1000 fights."""
    binary, request = binary.resolve(), request.resolve()
    sha = selected_pin(root, binary)
    if sha is None:
        raise ValueError("P7_1_SELECTED_ENGINE_GITLINK_MISMATCH")
    raw = request.read_bytes()
    source = source_identity(raw)
    prepared_sha = native_prepared_actor(binary, request)
    measured = native_module(root).native_source_control(
        binary, request, FIGHTS, rng_mode="stochastic")
    score = measured.get("native_dps")
    if (measured.get("iterations") != FIGHTS or type(score) not in (int, float)
            or not math.isfinite(score) or score <= 0):
        raise ValueError("P7_1_PAID_REFERENCE_1000_STOCHASTIC_FIGHTS_INVALID")
    witness = {
        "source": "native_generated_msim_reference",
        "selected_engine_revision": sha,
        "source_request_raw_sha256": digest(raw),
        "native_prepared_request_sha256": prepared_sha,
        "native_prepared_actor_class": "ClassDruid",
        "native_prepared_actor_level": 20,
        "native_rules": "forever",
        "target_level": 23,
        "encounter_sha256": digest(json.dumps(
            source["encounter"], sort_keys=True, separators=(",", ":")).encode()),
        "rng_mode": "stochastic",
        "iterations": FIGHTS,
        "reference_dps": float(score),
        "native_receipt": measured,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / REQUEST).write_bytes(raw)
    (output / RECEIPT).write_text(json.dumps(witness, indent=2, sort_keys=True) + "\n")
    return witness


def load_frozen(root, selected):
    directory = root / BASE
    request, manifest = directory / REQUEST, directory / RECEIPT
    if not (request.is_file() and manifest.is_file()):
        return blocked("P7_1_NATIVE_GENERATED_REFERENCE_NOT_CAPTURED")
    try:
        raw = request.read_bytes()
        doc = source_identity(raw)
        m = json.loads(manifest.read_text())
        expected = {
            "source": "native_generated_msim_reference",
            "selected_engine_revision": selected,
            "source_request_raw_sha256": digest(raw),
            "native_prepared_actor_class": "ClassDruid",
            "native_prepared_actor_level": 20,
            "native_rules": "forever",
            "target_level": 23,
            "encounter_sha256": digest(json.dumps(
                doc["encounter"], sort_keys=True, separators=(",", ":")).encode()),
            "rng_mode": "stochastic",
            "iterations": FIGHTS,
        }
        score = m["reference_dps"]
        if (any(m.get(k) != v for k, v in expected.items())
                or not isinstance(m.get("native_prepared_request_sha256"), str)
                or len(m["native_prepared_request_sha256"]) != 64
                or type(score) not in (int, float) or not math.isfinite(score)
                or score <= 0 or m["native_receipt"]["iterations"] != FIGHTS
                or m["native_receipt"]["native_dps"] != score):
            return blocked("P7_1_NATIVE_GENERATED_REFERENCE_RECEIPT_MISMATCH")
    except (ValueError, KeyError, TypeError, OSError):
        return blocked("P7_1_NATIVE_GENERATED_REFERENCE_RECEIPT_INVALID")
    return request, m


def run_native_generated_p71(root, spec):
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN",
                                str(root.parent / "upstream/target/release/forever-engine"))).resolve()
    selected = selected_pin(root, binary)
    if selected is None:
        return blocked("P7_1_SELECTED_ENGINE_GITLINK_OR_BINARY_MISSING")
    frozen = load_frozen(root, selected)
    if isinstance(frozen, dict):
        return frozen
    request, meta = frozen
    try:
        # The source-native actor must *actually* be L20; the engine remains
        # authoritative even if a JSON payload asserts a different level.
        if native_prepared_actor(binary, request) != meta["native_prepared_request_sha256"]:
            return blocked("P7_1_NATIVE_PREPARED_SOURCE_IDENTITY_CHANGED")
        result = native_module(root).native_source_control(
            binary, request, FIGHTS, rng_mode="stochastic")
    except (RuntimeError, ValueError, TypeError, OSError, KeyError,
            subprocess.SubprocessError) as exc:
        return blocked("P7_1_NATIVE_GENERATED_REFERENCE_REFUSED",
                       native_execution_error=str(exc)[-800:])
    actual = result.get("native_dps")
    if (result.get("iterations") != FIGHTS or type(actual) not in (int, float)
            or not math.isfinite(actual) or actual < 0):
        return {"status": "FAIL", "reasons": ["P7_1_NATIVE_RESULT_INVALID"]}
    target = float(meta["reference_dps"])
    evidence = {
        "production_engine": "pinned_mythicsim_rust_native",
        "native_source_revision": selected,
        "source_request_raw_sha256": meta["source_request_raw_sha256"],
        "reference_configuration_source": "native_generated_msim_reference",
        "reference_profile": "native_generated_druid_l20",
        "checkpoint_spec": spec,
        "native_rules": "forever",
        "native_dps": float(actual),
        "saved_reference_dps": target,
        "required_dps": p7_required_dps("P7.1", target),
        "iterations": FIGHTS,
        "sampled_source_fights": FIGHTS,
        "stochastic_rng": True,
        "selected_validation": "1000_native_stochastic_fights",
    }
    if not p7_final_stochastic_mean_passes(
            "P7.1", actual, target, iterations=FIGHTS, stochastic=True):
        return {"status": "FAIL",
                "reasons": ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"], **evidence}
    return {
        "status": "PASS", "reasons": [],
        "p7_1_1_reference_pinned": True,
        "p7_1_2_native_reproduced": True,
        "runtime_proof": {
            "executed": True,
            "engine_revision": selected,
            "source_revision": meta["source_request_raw_sha256"],
            "run_id": "P7.1-native-generated-" + str(uuid4()),
        },
        **evidence,
    }


def main():
    parser = argparse.ArgumentParser(description="Capture selected-native L20 reference (no M1 record)")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(capture(root, args.binary, args.request, args.out_dir), sort_keys=True))


if __name__ == "__main__":
    main()

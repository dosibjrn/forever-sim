"""P7.2 live first contact: real cold APL mutation -> pinned Rust -> gsim 2D.

Uses the existing source-backed APL mutator and the *selected* native-world
production evaluator. A short cold search is a FAIL with numeric DPS proximity,
NOT the required 300s independent search or 1000 stochastic-fight acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity)


def _source_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_PRODUCTION_MODULE_UNAVAILABLE:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blocked(reason: str):
    return {"status": "BLOCKED", "reasons": [reason]}


def _cold_apl(base: dict, rng: random.Random, mutation):
    """Rebuild a genuinely new source-grammar APL with fixed gear and talents."""
    result = copy.deepcopy(base)
    p = result["raid"]["parties"][0]["players"][0]
    initial = base["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    candidate = mutation.mutate_apl(None, initial, rng, cold=True)
    if candidate == initial:
        raise ValueError("COLD_APL_IDENTICAL_TO_REFERENCE")
    p["rotation"]["priorityList"] = candidate
    original = base["raid"]["parties"][0]["players"][0]
    if p["equipment"] != original["equipment"] or (
            p.get("talentsString") != original.get("talentsString")):
        raise ValueError("ROTATION_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return result


def _pinned_source_runtime(root: Path, class_key: str, level: int,
                           spec: str, gate: str):
    """One exact-source native preflight shared by P7 discovery gates."""
    if (class_key, level, spec) != ("druid", 60, "balance"):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT")
    request = root / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    if not request.is_file() or not witness.is_file():
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_OR_REFERENCE_MISSING")
    raw = request.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SAVED_BALANCE_RAW_SHA:
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_CHANGED")
    base = json.loads(raw)
    meta = json.loads(witness.read_text())
    if (meta.get("engine_revision") != PINNED_RUST
            or not isinstance(meta.get("reference_dps"), (float, int))
            or meta["reference_dps"] <= 0
            or base["raid"]["parties"][0]["players"][0]["class"] != "ClassDruid"
            or len(base["encounter"]["targets"]) != 1
            or base["encounter"]["targets"][0]["level"] != 63):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_SCENARIO_MISMATCH")
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root.parent / "upstream/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return _blocked(gate.replace(".", "_") + "_PINNED_RUST_BINARY_MISSING")
    upstream = binary.parents[2]
    revision = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
    if (revision.returncode != 0 or revision.stdout.strip() != PINNED_RUST
            or not (upstream / "src/core/fight/world_bridge.rs").is_file()):
        return _blocked(gate.replace(".", "_") + "_PINNED_NATIVE_WORLD_BUILD_NOT_VERIFIED")

    return (base, meta, binary)


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(root, class_key, level, spec, "P7.2")
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    mutation = _source_module(root / "integrations/mythicsim-rust/apl_mutation.py",
                              "p72_source_apl_mutator")
    production = _source_module(
        root / "integrations/mythicsim-rust/live_world_probe.py",
        "p72_production_native_world")
    player = base["raid"]["parties"][0]["players"][0]
    rng = random.Random(63272)
    initial_hash = hashlib.sha256(json.dumps(
        player["rotation"]["priorityList"], sort_keys=True).encode()).hexdigest()
    best = None
    executed = 0
    failures = []
    # Small cold search first: no saved-reference winner, no static DPS proxy.
    # Every scored candidate goes through the real native↔2D coupled producer.
    for index in range(4):
        try:
            candidate = _cold_apl(base, rng, mutation)
            with tempfile.TemporaryDirectory(prefix="forever_p72_live_") as temp:
                file = Path(temp) / "source-cold-candidate.json"
                file.write_text(json.dumps(candidate))
                native = production.native_source_control(binary, file, 3)
                result = production.run(
                    binary, file, distance=player["distanceFromTarget"], iterations=3)
                parity_failure = _source_native_world_parity(native, result, 3)
                if parity_failure is not None:
                    raise ValueError("SOURCE_NATIVE_WORLD_PARITY_FAILED:" + parity_failure)
            if (result.get("iterations_done") != 3
                    or result.get("native_damage_events", 0) <= 0
                    or result.get("native_world_ticks", 0) <= 0):
                raise ValueError("SOURCE_NATIVE_WORLD_INCOMPLETE")
            executed += 1
            score = float(result["world_mean_dps"])
            if score < 0 or not score < float("inf"):
                raise ValueError("INVALID_COUPLED_WORLD_DPS")
            if best is None or score > best[0]:
                best = (score, result, hashlib.sha256(
                    json.dumps(candidate, sort_keys=True).encode()).hexdigest())
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_2_NO_EXECUTED_SOURCE_LEGAL_COLD_APL_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "cold_candidate_failures": failures[:4]}

    score, selected, selected_sha = best
    return {
        "status": "FAIL",
        "reasons": ["P7_2_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED",
                    "P7_2_SOURCE_LEGAL_ROTATION_UNIVERSE_NOT_EXHAUSTED"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "original_apl_hash": initial_hash,
        "cold_winner_request_sha256": selected_sha,
        "winner_live_dps": score,
        "world_damage_events": int(selected["native_damage_events"]),
        "world_boundaries": int(selected["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_world_fights_per_cold_candidate",
        "source_fixed_gear_and_talents": True,
        "coverage_scope_complete": False,
    }

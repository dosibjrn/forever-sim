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
import time

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_final_stochastic_mean_passes,
                                    p7_required_dps)

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     _source_native_world_parity, _executed_p7_runtime_proof)


def _source_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_PRODUCTION_MODULE_UNAVAILABLE:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blocked(reason: str):
    return {"status": "BLOCKED", "reasons": [reason]}


def _cold_apl(base: dict, rng: random.Random, mutation, *, elite=None):
    """Cold grammar draw or local improvement of this search's paid best.

    The first candidate is sampled independently of the saved reference.
    The optional elite is this search's already executed native/world winner;
    only its rotation is mutable, while gear and talents remain pinned.
    """
    result = copy.deepcopy(base)
    p = result["raid"]["parties"][0]["players"][0]
    original = base["raid"]["parties"][0]["players"][0]
    grammar = original["rotation"]["priorityList"]
    if elite is None:
        candidate = mutation.mutate_apl(None, grammar, rng, cold=True)
    else:
        winner = elite["raid"]["parties"][0]["players"][0]
        if (winner["equipment"] != original["equipment"]
                or winner.get("talentsString") != original.get("talentsString")):
            raise ValueError("P72_PAID_ELITE_CHANGED_FIXED_DIMENSIONS")
        # Reuse only an actually paid P7.2 winner, never the reference policy
        # or an independently accepted P7.1/P7.3-P7.5 result as a seed.
        candidate = mutation.mutate_apl(
            winner["rotation"]["priorityList"], grammar, rng, cold=False)
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
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return _blocked("P7_2_INVALID_FULL_SOURCE_SEARCH_MODE")
    full_search = search_mode == "1"
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
    paid_or_rejected = set()
    proposals = 0
    search_start = time.monotonic()
    # Default = four real bounded coupled-world diagnostics. Explicit --heavy
    # = a separate independent 300-second wall-clock cold search using the
    # SAME source APL grammar and real Rust/gsim evaluator (no proxy engine).
    # Repeated APLs cannot be counted as new paid source candidates.
    while (time.monotonic() - search_start < 300.0
           if full_search else proposals < 4):
        proposals += 1
        try:
            # After the first paid winner, 4/5 proposals improve that
            # winner locally; every fifth is a fresh independent cold draw.
            # A bounded short probe always stays cold. Candidate SHA
            # deduplication and native/world paid scoring remain unchanged.
            elite = (best[3] if full_search and best is not None
                     and proposals % 5 != 0 else None)
            candidate = _cold_apl(base, rng, mutation, elite=elite)
            candidate_sha = hashlib.sha256(
                json.dumps(candidate, sort_keys=True).encode()).hexdigest()
            if candidate_sha in paid_or_rejected:
                continue
            paid_or_rejected.add(candidate_sha)
            with tempfile.TemporaryDirectory(prefix="forever_p72_live_") as temp:
                file = Path(temp) / "source-cold-candidate.json"
                file.write_text(json.dumps(candidate))
                native = production.native_source_control(binary, file, 3,
                                                          rng_mode="balanced")
                result = production.run(
                    binary, file, distance=player["distanceFromTarget"],
                    iterations=3, rng_mode="balanced")
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
                best = (score, result, candidate_sha, candidate)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError) as exc:
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    search_wall_s = time.monotonic() - search_start
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_2_NO_EXECUTED_SOURCE_LEGAL_COLD_APL_WORLD_CANDIDATE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "search_wall_s": search_wall_s,
                "cold_candidate_failures": failures[:4]}

    score, selected, selected_sha, frozen_winner = best
    final = {}
    if full_search and search_wall_s >= 300.0:
        # Freeze the best source request before any final measurement. This
        # strictly separate stochastic run must never modify or rank winners.
        # Keep a real native control alongside genuine gsim world execution.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p72_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_raw_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(binary, frozen_path, n,
                                                          rng_mode="stochastic")
                live = production.run(
                    binary, frozen_path, distance=player["distanceFromTarget"],
                    iterations=n, rng_mode="stochastic")
                mismatch = _source_native_world_parity(
                    native, live, n, expected_raw_sha=frozen_raw_sha)
                if mismatch is not None:
                    raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                native_dps = float(native["native_dps"])
                world_dps = float(live["world_mean_dps"])
                final = {
                    "frozen_request_raw_sha256": frozen_raw_sha,
                    "frozen_stochastic_iterations": n,
                    "frozen_stochastic_native_dps": native_dps,
                    "frozen_stochastic_world_dps": world_dps,
                    "frozen_stochastic_world_damage_events": int(live["native_damage_events"]),
                    "frozen_stochastic_world_boundaries": int(live["native_world_ticks"]),
                    "frozen_stochastic_reference_floor_met": (
                        p7_final_stochastic_mean_passes(
                            "P7.2", world_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)
                        and p7_final_stochastic_mean_passes(
                            "P7.2", native_dps, float(meta["reference_dps"]),
                            iterations=n, stochastic=True)),
                }
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    # The original saved report source is pinned by shared preflight; the
    # gate requires executable source-legal candidates, not an exhaustive
    # enumeration or a second interactive UI capture.
    reasons = []
    if not full_search:
        reasons.append("P7_2_FULL_INDEPENDENT_300S_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif search_wall_s < 300.0:
        reasons.append("P7_2_300S_SEARCH_NOT_COMPLETED")
    elif search_wall_s > 301.0:
        reasons.append("P7_2_SEARCH_BUDGET_OVERRUN")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_2_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_reference_floor_met"]:
        reasons.append("P7_2_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR")
    return {
        "status": "PASS" if not reasons else "FAIL",
        **(_executed_p7_runtime_proof("P7.2", final["frozen_request_raw_sha256"])
           if not reasons else {}),
        "reasons": reasons,
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": PINNED_RUST,
        "source_request_raw_sha256": SAVED_BALANCE_RAW_SHA,
        "saved_reference_dps": float(meta["reference_dps"]),
        "original_apl_hash": initial_hash,
        "cold_winner_request_sha256": selected_sha,
        "winner_live_dps": score,
        "required_reference_dps": p7_required_dps(
            "P7.2", float(meta["reference_dps"])),
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": full_search and 300.0 <= search_wall_s <= 301.0,
        "cold_unique_source_requests": len(paid_or_rejected),
        **final,
        "world_damage_events": int(selected["native_damage_events"]),
        "world_boundaries": int(selected["native_world_ticks"]),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_world_fights_per_cold_candidate",
        "search_rng_mode": "balanced",
        "source_fixed_gear_and_talents": True,
        "coverage_scope_complete": False,
    }

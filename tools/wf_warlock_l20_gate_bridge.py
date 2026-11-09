"""Shared official Warlock L20 P4/P5/P6 native-paid gate provider.

Only the explicitly paired CLI may start the expensive cold search. All three
gate verdicts inspect the SAME freshly executed 30/300s/100-mob receipt; no
saved JSON, static PASS field, or second 300-second search is trusted.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4

_SHARED_COLD: dict | None = None
PAIR = ("warlock", 20, "unrestricted")
OPT_IN = "FOREVER_P4_P5_WARLOCK_L20_COLD_SEARCH"


def set_shared_warlock_l20_cold(enabled: bool) -> None:
    """Arm one ephemeral shared run for an explicit paired gate invocation."""
    global _SHARED_COLD
    _SHARED_COLD = {} if enabled else None


def _rejected(reason: str, *, status: str = "FAIL", **extra) -> dict:
    return {"status": status, "reasons": [reason],
            "coverage_scope_complete": False, **extra}


def _execute() -> dict:
    """Call the production paid Rust/gsim producer once, not a surrogate."""
    binary_name = os.environ.get("FOREVER_P4_P5_WARLOCK_L20_BINARY")
    source_name = os.environ.get("FOREVER_P4_P5_WARLOCK_L20_SOURCE_REQUEST")
    output_name = os.environ.get("FOREVER_P4_P5_WARLOCK_L20_RECEIPT_DIR")
    if not binary_name or not source_name or not output_name:
        return _rejected("WARLOCK_NATIVE_COLD_BINARY_SOURCE_AND_OUTPUT_REQUIRED",
                         status="BLOCKED")
    binary, source, output = Path(binary_name), Path(source_name), Path(output_name)
    if not binary.is_file() or not source.is_file():
        return _rejected("WARLOCK_NATIVE_COLD_BINARY_OR_SOURCE_NOT_FOUND",
                         status="BLOCKED")
    try:
        from tools.wf_warlock_l20_native_cold import run_cold
        from native_options import query_native_options
        request = json.loads(source.read_text(encoding="utf-8"))
        options = query_native_options(binary, "warlock", 20)
        cold = run_cold(
            request, options, binary=binary, out=output,
            seed=int(os.environ.get("FOREVER_P4_P5_WARLOCK_L20_SEED",
                                    "20261109")))
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return _rejected("WARLOCK_NATIVE_COLD_EXECUTION_REFUSED:"
                         + type(exc).__name__ + ":" + str(exc)[-400:])
    if not isinstance(cold, dict):
        return _rejected("WARLOCK_NATIVE_COLD_INVALID_PRODUCER_RESPONSE")
    return cold


def _completed_finalist(row: object) -> bool:
    """Require the actual paid native/world hundred-kill receipt, not a score."""
    if not isinstance(row, dict) or row.get("status") != (
            "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"):
        return False
    raw = row.get("native_receipt")
    value = row.get("seconds_per_mob")
    return bool(
        isinstance(raw, dict)
        and raw.get("status") == "COMPLETED_100_REAL_NATIVE_GSIM_KILLS"
        and raw.get("target_count_requested") == 100
        and raw.get("hostile_player_tank_requested") is True
        and raw.get("native_enemy_attack_prepared") is True
        and raw.get("native_actor_continuity_receipt_complete") is True
        and raw.get("native_recovery_clock_accounted") is True
        and raw.get("native_recovery_mode") == "decisions_food_water"
        and raw.get("native_2d_paid_objective_eligible") is True
        and type(value) in (float, int) and math.isfinite(value) and value > 0
        and type(raw.get("seconds_per_mob")) in (float, int)
        and math.isclose(value, raw["seconds_per_mob"], rel_tol=1e-9))


def _gate_verdict(cold: dict, gate: str) -> dict:
    """Check existing P4-P6 criteria against the one source-paid receipt."""
    if "status" in cold and cold["status"] in ("FAIL", "BLOCKED"):
        return cold
    base = {
        "production_component": "tools.wf_warlock_l20_native_cold.run_cold",
        "production_engine": "mythicsim-rust-native-world",
        "source_request_sha256": cold.get("source_request_sha256"),
        "engine_binary_sha256": cold.get("engine_binary_sha256"),
        "source_revision": cold.get("source_revision"),
        "search_seed": cold.get("search_seed"),
        "search_wall_s": cold.get("elapsed_search_s"),
        "native_paid_screen_count": cold.get("native_paid_screen_count"),
        "distinct_paid_candidates": cold.get("distinct_paid_candidates"),
        "native_paid_after_snapshot": cold.get("native_paid_after_snapshot"),
        "selected_paid_winners": {
            label: cold.get("finalists", {}).get(label, {}).get("candidate_sha256")
            for label in ("30s", "300s")
        },
    }
    reasons = []
    first = cold.get("snapshot_30")
    last = cold.get("final_300")
    finalists = cold.get("finalists") or {}
    if cold.get("cold_300_reached") is not True:
        reasons.append("P4_P5_NATIVE_COLD_300S_NOT_REACHED")
    if (not isinstance(first, dict)
            or type(first.get("paid_completed_elapsed_s")) not in (int, float)
            or not 0 <= first["paid_completed_elapsed_s"] <= 30):
        reasons.append("P4_NATIVE_PAID_30S_SNAPSHOT_MISSING")
    if not isinstance(last, dict):
        reasons.append("P5_NATIVE_PAID_300S_WINNER_MISSING")
    elif (type(last.get("paid_completed_elapsed_s")) not in (int, float)
          or last["paid_completed_elapsed_s"] > 300):
        reasons.append("P5_NATIVE_PAID_WINNER_OUTSIDE_BUDGET")
    if not _completed_finalist(finalists.get("30s")):
        reasons.append("P4_NATIVE_100MOB_FINALIST_INCOMPLETE")
    if not _completed_finalist(finalists.get("300s")):
        reasons.append("P5_NATIVE_100MOB_FINALIST_INCOMPLETE")
    if (not isinstance(first, dict) or not isinstance(last, dict)
            or first.get("candidate_sha256") != finalists.get("30s", {}).get("candidate_sha256")
            or last.get("candidate_sha256") != finalists.get("300s", {}).get("candidate_sha256")):
        reasons.append("WARLOCK_NATIVE_FROZEN_WINNER_RECEIPT_MISMATCH")
    if (not isinstance(cold.get("source_request_sha256"), str)
            or not isinstance(cold.get("engine_binary_sha256"), str)):
        reasons.append("WARLOCK_NATIVE_EXECUTED_IDENTITY_MISSING")
    if gate == "P4":
        # Producer must report a *real paid cast and result* when the source
        # supplies a reachable talent unlock. This is not an exhaustive audit.
        if (cold.get("native_source_unlocked_actions_available") is not False
                and cold.get("native_representative_unlocked_cast_compared")
                is not True):
            reasons.append("P4_NATIVE_REPRESENTATIVE_UNLOCK_CAST_UNVERIFIED")
    elif gate == "P5":
        if type(cold.get("native_paid_after_snapshot")) is not int or (
                cold["native_paid_after_snapshot"] < 1):
            reasons.append("P5_NATIVE_PAID_CONTINUATION_NOT_OBSERVED")
        if type(cold.get("distinct_paid_candidates")) is not int or (
                cold["distinct_paid_candidates"] < 2):
            reasons.append("P5_NATIVE_DISTINCT_PAID_BUILDS_NOT_DEMONSTRATED")
    elif gate == "P6":
        comparison = cold.get("p6_comparison") or {}
        first_s = finalists.get("30s", {}).get("seconds_per_mob")
        last_s = finalists.get("300s", {}).get("seconds_per_mob")
        if (not isinstance(comparison, dict)
                or comparison.get("status") != "MEASURED_PAID_100_MOB_FINALISTS"
                or type(first_s) not in (int, float)
                or type(last_s) not in (int, float)
                or not math.isfinite(first_s) or not math.isfinite(last_s)
                or last_s <= 0
                or not math.isclose(comparison.get("t30_over_t300", -1),
                                    first_s / last_s, rel_tol=1e-9)
                or first_s > 1.01 * last_s):
            reasons.append("P6_NATIVE_PAID_100MOB_ONE_PERCENT_NOT_PROVEN")
        base["source_replay_T30_s_per_mob"] = first_s
        base["source_replay_T300_s_per_mob"] = last_s
        base["source_replay_T30_T300"] = (first_s / last_s
            if type(first_s) in (int, float) and type(last_s) in (int, float)
            and last_s > 0 else None)
    if reasons:
        return {"status": "FAIL", "reasons": reasons,
                "coverage_scope_complete": False, **base}
    return {"status": "PASS", "reasons": [], "coverage_scope_complete": True,
            **base, "runtime_proof": {
                "executed": True,
                "engine_revision": "mythicsim-rust-bin-sha256:"
                                   + cold["engine_binary_sha256"],
                "source_revision": "source-request-sha256:"
                                   + cold["source_request_sha256"],
                "run_id": os.environ.get("GITHUB_RUN_ID")
                          or "warlock-native-p456-" + uuid4().hex,
            }}


def run_warlock_l20_gate(class_key: str, level: int, spec: str,
                        *, gate: str) -> dict:
    if (class_key, level, spec) != PAIR or gate not in ("P4", "P5", "P6"):
        return _rejected("WARLOCK_NATIVE_COLD_WRONG_GATE_OR_CHECKPOINT",
                         status="BLOCKED")
    if os.environ.get(OPT_IN) != "1" or _SHARED_COLD is None:
        return _rejected("WARLOCK_NATIVE_COLD_REQUIRES_EXPLICIT_PAIRED_DISPATCH",
                         status="BLOCKED")
    if "executed" not in _SHARED_COLD:
        _SHARED_COLD["executed"] = _execute()
    return _gate_verdict(_SHARED_COLD["executed"], gate)

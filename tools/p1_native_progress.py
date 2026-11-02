"""Pure 80/20 progress presentation for genuine P1 native ability behavior.

This is NOT a new acceptance gate, PASS database, independent simulator,
or authority for reading user-supplied 'PASS' JSON. It counts in-memory
outcomes from the real selected production executor. The only code allowed
to produce NATIVE_DIRECT_BEHAVIOR_VERIFIED is the actual runtime test that
compares/measures relevant effects; a schema/unit fixture is never evidence.

9 diagnostic milestones: 50%, 80%, 85%, 88%, 91%, 93%, 95%, 97%, 99%.
Formal P1 PASS is separately awarded only by approved wf_gate.py P1.
"""
from __future__ import annotations

THRESHOLDS = (50, 80, 85, 88, 91, 93, 95, 97, 99)
REAL_NATIVE_BACKENDS = frozenset(("msim-rust", "msim-go", "hybrid-rust", "hybrid-go"))
VERIFIED_EFFECT = "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
_DIAGNOSTICS = frozenset((
    "NATIVE_APL_ABLATION_DIFFERENCE",
    "NO_COMBAT_METRIC_DIFFERENCE",
    "RUST_APL_ABLATION_DIAGNOSTIC_NOT_ISOLATED_P1",
    "MISSING_GAME_IR_ACTION",
    "EFFECT_OBSERVED",
))


def _positive_ids(rows, *, field="spell_id"):
    seen = set()
    for row in rows:
        sid = row[field] if isinstance(row, dict) else row
        if type(sid) is not int or sid <= 0:
            raise ValueError("INVALID_P1_SPELL_ID")
        if sid in seen:
            raise ValueError("DUPLICATE_P1_SPELL_ID:" + str(sid))
        seen.add(sid)
    return seen


def milestone_progress(verified: int, total: int, *, unknown: int = 0) -> dict:
    """Generic diagnostic partial-credit series, never an acceptance decision.

    Unknown source eligibility is included conservatively in the denominator
    rather than silently shrinking the scope. No invented integer denominator
    is inferred when the real total is unknown.
    """
    if any(type(x) is not int or x < 0 for x in (verified, total, unknown)):
        raise ValueError("INVALID_PROGRESS_COUNTS")
    if verified > total:
        raise ValueError("MORE_SUCCESSES_THAN_SCOPED_ITEMS")
    denominator = total + unknown
    ratio = verified / denominator if denominator else 0.
    reached = [x for x in THRESHOLDS if denominator > 0
               and 100 * verified >= x * denominator]
    return {
        "verified": verified,
        "scope_count": total,
        "source_unknown_count": unknown,
        "conservative_denominator": denominator,
        "effect_coverage_fraction": ratio if denominator else None,
        "milestones_reached": reached,
        "progress_naksut": len(reached),
        "max_diagnostic_naksut": 9,
        "formal_gate_pass": False,
        "progress_only_not_acceptance": True,
    }


def native_p1_progress(scope: dict, runtime_results=()) -> dict:
    """Summarize only source-scoped direct native tests, not gsim/APL proxies.

    `scope` comes from p1_native_source_inventory.inventory and records
    unverified acquisition. `runtime_results` are in-memory, not a historical
    JSON status ledger. This helper DOES NOT validate source legality itself.
    A native APL/DPS delta cannot be promoted to a direct per-spell effect.
    """
    if scope.get("source_only") is not True or scope.get("game_ir_required") is not False:
        raise ValueError("P1_NATIVE_SOURCE_INVENTORY_REQUIRED")
    candidates = _positive_ids(scope["candidates"])
    separate = _positive_ids(scope["separate"])
    if candidates & separate:
        raise ValueError("P1_CANDIDATES_OVERLAP_SEPARATE")
    waived = {int(row["spell_id"]) for row in scope["separate"]
              if row["status"] == "NOT_RELEVANT_TO_SIMULATION"}
    unresolved = {int(row["spell_id"]) for row in scope["separate"]
                  if row["status"] == "ACQUISITION_UNRESOLVED"}
    if waived & unresolved:
        raise ValueError("P1_APPLICABILITY_OVERLAPS_UNKNOWN")
    known = candidates | separate
    counted = set()
    diagnostic_only = set()
    tested = set()
    for result in runtime_results:
        sid = result.get("spell_id")
        if type(sid) is not int or sid not in known:
            raise ValueError("RUNTIME_RESULT_NOT_IN_SOURCE_SCOPE")
        if sid in tested:
            raise ValueError("DUPLICATE_RUNTIME_TEST_FOR_SPELL:" + str(sid))
        tested.add(sid)
        if sid not in candidates:
            # Source noncombat/passive/auto/pet actions need their own producer;
            # P1's cast-action scope cannot award them accidental green ticks.
            diagnostic_only.add(sid)
            continue
        if (result.get("status") == VERIFIED_EFFECT
                and result.get("proof_kind") == "NATIVE_DIRECT_EFFECT"
                and result.get("executor") in REAL_NATIVE_BACKENDS
                and result.get("native_executed") is True
                and result.get("controlled_behavior_assertion_passed") is True
                and result.get("observable_effects")):
            counted.add(sid)
        else:
            # In particular this includes native APL removal and gsim-only
            # observables, which never count as native P1 progress.
            diagnostic_only.add(sid)
    # ALL source-index candidates are still potential until independently
    # checked for actual learning. This is a conservative *diagnostic* scope,
    # NOT a certified legal denominator.
    result = milestone_progress(len(counted), len(candidates), unknown=len(unresolved))
    result.update({
        "kind": "P1_NATIVE_REAL_BEHAVIOR_PROGRESS_ONLY",
        "class": scope["class"],
        "level": scope["level"],
        "scenario": scope["scenario"],
        "verified_spell_ids": sorted(counted),
        "diagnostic_only_spell_ids": sorted(diagnostic_only),
        "not_relevant_spell_ids": sorted(waived),
        "not_relevant_count": len(waived),
        "source_candidate_count": len(candidates),
        "source_legality_confirmed": False,
        "other_channel_spell_ids": sorted(separate - waived - unresolved),
        "note": "Raw spell-index candidates are not confirmed acquired/learned. "
                "Only direct measured native effect outcomes may earn diagnostic ticks.",
    })
    return result

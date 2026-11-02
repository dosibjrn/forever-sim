"""P3 first production contact: REAL gear catalogue, scorer and combat weights.

Uses existing source/legal IR, paid source search, production stat sensitivities,
actual item_score and P3 smoke. No alternate gear scorer or gate-only simulator.
Constrained profile/native compatibility is explicitly fail-closed until the
selected production build is actually represented.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from uuid import uuid4


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
    from src.v2.source_budgeted_gear import run_source_budgeted_gear
    from src.v2.source_stateful_budgeted import _make_policy
    from src.game.model import PolicyCondition

    # This is an actual cheap P3 attempt, not a 300s optimization. No default
    # weights, class-specific winners or invented P3 positive epsilons.
    ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_SELECTED_CLASS_LEVEL_SOURCE_IR_UNAVAILABLE"],
            "production_component": "src.game.checkpoint_p3_smoke.fast_p3_smoke_for_policy"}
    result = run_source_budgeted_gear(
        class_key=class_key, level=level, ir_slice=ir,
        max_evaluations=36, initial_search=12, search_per_gear=3,
        max_gear_states=1, probe_deltas=(5., 20.),
        probe_stats=("armor", "stamina", "strength", "agility", "intellect",
                     "spirit", "spell_power", "attack_power", "mp5",
                     "crit", "hit", "dodge", "parry"),
        schedule_incoming_attacks=True)
    stages = result.get("stages") or []
    naked = next((x for x in stages if x.get("stage") == "source_naked"), None)
    sensitivity = next((x for x in result.get("sensitivity_history", ())
                        if x.get("stage") == "source_naked"
                        and isinstance(x.get("values"), dict)), None)
    if not naked or not naked.get("winner") or sensitivity is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_PRODUCTION_SEARCH_OR_MEASURED_WEIGHT_CONTEXT_UNAVAILABLE:"
            + str(result.get("status"))],
            "production_component": "src.v2.source_budgeted_gear.run_source_budgeted_gear",
            "real_source_search_attempts": result.get("attempted", 0),
            "real_source_search_evaluated": result.get("evaluated", 0)}
    record = naked["winner"]
    policy = _make_policy(
        ir, record["fallback"],
        guarded_action=record.get("guarded_action"),
        guarded_conditions=tuple(PolicyCondition(**x)
                                 for x in record.get("guarded_conditions", ())))
    weights = sensitivity["values"]
    if not all(type(v) in (int, float) and isfinite(v) for v in weights.values()):
        return {"status": "FAIL", "reasons": ["P3_REAL_PRODUCTION_WEIGHTS_NONFINITE"]}
    item_check = fast_p3_smoke_for_policy(
        source_ir=ir, policy=policy, class_key=class_key, level=level,
        weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT")
    reasons = list(item_check["blockers"])
    # P3 explicitly permits a real gsim gear context: never invent a
    # native-only prerequisite. But a constrained talent profile cannot use
    # an unrestricted allocation as its P3 production build.
    if spec != "unrestricted":
        reasons.append("P3_SPEC_CONSTRAINED_PRODUCTION_BUILD_NOT_EVALUATED:" + spec)
    # Source-ranked, real CombatRuntime measurements were used for each
    # measured derivative; the ordinary source item scorer tested ilvl top5.
    status = "FAIL" if reasons else "PASS"
    proof = {}
    if status == "PASS":
        from src.version import SOFTWARE_VERSION
        proof = {"runtime_proof": {
            "executed": True, "engine_revision": "gsim-" + SOFTWARE_VERSION,
            "source_revision": result["source_context_sha256"],
            "run_id": "p3-live-" + str(uuid4())}}
    return {
        "status": status, "reasons": sorted(set(reasons)),
        **proof,
        "production_component": "src.game.checkpoint_p3_smoke.fast_p3_smoke_for_policy",
        "production_engine": "gsim_CombatRuntime",
        "real_source_search_attempts": result.get("attempted", 0),
        "real_source_search_evaluated": result.get("evaluated", 0),
        "real_catalogue_legal_items": item_check["legal_item_count"],
        "real_catalogue_top5_items_scored": item_check["tested_item_count"],
        "real_catalogue_slots_scored": item_check["slot_count"],
        "real_item_score_checked": item_check["source"] == "CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS",
        "real_measured_stat_weight_axes": sorted(weights),
        "actual_search_result_status": result.get("status"),
        "source_context_sha256": result.get("source_context_sha256"),
    }

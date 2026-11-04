"""P3 first production contact: REAL gear catalogue, scorer and combat weights.

Uses existing source/legal IR, paid source search, production stat sensitivities,
actual item_score and P3 smoke. No alternate gear scorer or gate-only simulator.
Constrained profile/native compatibility is explicitly fail-closed until the
selected production build is actually represented.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from hashlib import sha256
from uuid import uuid4


def _source_profile_build_ir(root: Path, ir, class_key: str, level: int, spec: str):
    """Use the actual source-legal talent frontier as the P3 build.

    Never substitute an unrestricted naked caster for a constrained profile,
    or a tree-name label for a real executable full-point talent allocation.
    This returns the IR used by the existing *paid* gear/policy evaluator.
    """
    if spec == "unrestricted":
        return ir, {"profile": spec, "full_point_source_allocation": None}

    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.game.talents import (
        apply_talent_selection, available_talent_points,
        talented_bonus_for_level, validate_talent_selection)
    from tools.wf_source_profile import (
        _load_product_spec_profile, _source_spec_profile)

    db = Path(DEFAULT_DB)
    if not db.is_file():
        raise ValueError("P3_CANONICAL_TALENT_DB_MISSING")
    source_hash = sha256(db.read_bytes()).hexdigest()
    compiled, _ = compile_talent_runtime(ir)
    if not compiled.talents:
        raise ValueError("P3_NO_EXECUTABLE_SOURCE_TALENTS")
    bonus = talented_bonus_for_level(level)
    step = int((compiled.provenance.get("talent_tree_rules") or {})
               .get("points_per_row") or 0)
    if step <= 0:
        raise ValueError("P3_SOURCE_TALENT_TIER_RULE_MISSING")
    rule = _load_product_spec_profile(
        root, class_key, level, spec, source_sha256=source_hash)
    builds, profile = _source_spec_profile(
        compiled, spec, level=level, bonus=bonus, step=step,
        source_sha256=source_hash, profile_rule=rule)
    if not profile["source_spec_profile_verified"] or not builds:
        raise ValueError("P3_SPEC_PROFILE_NOT_SOURCE_VERIFIED:" + spec)
    # The production frontier already checked every full-point candidate.
    # A first deterministic legal candidate suffices for P3's *smoke*;
    # P4/P5 must independently search talents rather than reuse this winner.
    allocation = dict(builds[0])
    validate_talent_selection(compiled, allocation, level=level,
                              bonus_talent_points=bonus)
    if sum(allocation.values()) != available_talent_points(
            level, bonus_talent_points=bonus):
        raise ValueError("P3_SPEC_NOT_FULL_POINT_SOURCE_ALLOCATION")
    selected, receipt = apply_talent_selection(
        compiled, allocation, level=level, bonus_talent_points=bonus)
    if not receipt.applied_modifiers:
        raise ValueError("P3_SPEC_ALLOCATION_NOT_APPLIED_TO_RUNTIME")
    return selected, {
        "profile": spec,
        "full_point_source_allocation": allocation,
        "source_profile_candidate_count": len(builds),
        "source_profile_contract": profile["source_spec_profile_kind"],
        "source_talent_db_sha256": source_hash,
        "applied_modifiers": len(receipt.applied_modifiers),
    }


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
    from src.v2.source_budgeted_gear import (run_source_budgeted_gear,
        paid_source_policy_stat_witness)
    from src.v2.source_stateful_budgeted import _make_policy
    from src.game.model import PolicyCondition

    # This is an actual cheap P3 attempt, not a 300s optimization. No default
    # weights, class-specific winners or invented P3 positive epsilons.
    ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_SELECTED_CLASS_LEVEL_SOURCE_IR_UNAVAILABLE"],
            "production_component": "src.game.checkpoint_p3_smoke.fast_p3_smoke_for_policy"}
    try:
        ir, profile_context = _source_profile_build_ir(
            root, ir, class_key, level, spec)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"status": "BLOCKED", "reasons": [
            "P3_SOURCE_PROFILE_PRODUCTION_BUILD_UNAVAILABLE:"
            + str(exc)], "production_component":
            "src.v2.source_bounded_joint_frontier.source_spec_talent_frontier"}
    max_p3_evaluations = 44
    schedule_incoming_attacks = True
    result = run_source_budgeted_gear(
        class_key=class_key, level=level, ir_slice=ir,
        max_evaluations=max_p3_evaluations, initial_search=12, search_per_gear=3,
        max_gear_states=1, probe_deltas=(5., 20.),
        probe_stats=("armor", "stamina", "strength", "agility", "intellect",
                     "spirit", "spell_power", "attack_power", "mp5",
                     "crit", "hit", "dodge", "parry",
                     "health_regeneration_per_5s", "weapon_dps"),
        schedule_incoming_attacks=schedule_incoming_attacks,
        allow_naked_source_without_named_gear_roles=True)
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
    weights = dict(sensitivity["values"])
    if not all(type(v) in (int, float) and isfinite(v) for v in weights.values()):
        return {"status": "FAIL", "reasons": ["P3_REAL_PRODUCTION_WEIGHTS_NONFINITE"]}
    item_check = fast_p3_smoke_for_policy(
        source_ir=ir, policy=policy, class_key=class_key, level=level,
        weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT")
    # One narrowly chosen 12-evaluation winner is not proof that an ordinary
    # stat has no causal value to this build. The same source-legal full-point
    # IR may carry alternative executable policies. When the first policy
    # measured exactly ZERO for a required axis, seek a positive *paid* witness
    # with the source-authored policies and the same combat+recovery scorer.
    # Do not erase observed negative weights, waive missing stats, fabricate an
    # epsilon, or change P4/P5 search. The only extra work is paid from the
    # source search's remaining bounded budget.
    extra_evaluations = 0
    source_policy_stat_witnesses = []
    # Reuse a paid baseline for the same source policy across stat axes. Without
    # this, repeated baseline runs consume the fixed P3 budget before later
    # required axes (such as Spirit) receive their own paid perturbation.
    source_policy_baseline_cache = {}
    for blocker in item_check["blockers"]:
        if not blocker.startswith("NONPOSITIVE_RELEVANT_WEIGHT:"):
            continue
        axis = blocker.split(":", 1)[1]
        if weights.get(axis) != 0.0:
            continue
        remaining = max(0, max_p3_evaluations - int(result.get("attempted", 0)) - extra_evaluations)
        cache_prefix = (id(ir), int(level), bool(schedule_incoming_attacks))
        has_reusable_baseline = any(
            key[:3] == cache_prefix for key in source_policy_baseline_cache
        )
        minimum_evaluations = 1 if has_reusable_baseline else 2
        if remaining < minimum_evaluations:
            break
        witness = paid_source_policy_stat_witness(
            ir, stat=axis, level=level, probe_deltas=(5., 20.),
            max_evaluations=remaining,
            schedule_incoming_attacks=schedule_incoming_attacks,
            baseline_cache=source_policy_baseline_cache)
        extra_evaluations += int(witness["paid_evaluations"])
        source_policy_stat_witnesses.append(witness)
        if witness["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS":
            weights[axis] = witness["weight_s_saved_per_mob_per_unit"]
    if any(w["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
           for w in source_policy_stat_witnesses):
        item_check = fast_p3_smoke_for_policy(
            source_ir=ir, policy=policy, class_key=class_key, level=level,
            weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT")
    reasons = list(item_check["blockers"])
    # The same source-legal selected IR was used for actual CombatRuntime
    # sensitivity and the real item scorer. Never fake a positive stat weight.
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
        "source_profile_production_build": profile_context,
        "real_source_search_attempts": result.get("attempted", 0),
        "real_source_search_evaluated": result.get("evaluated", 0) + extra_evaluations,
        "source_policy_stat_witnesses": source_policy_stat_witnesses,
        "real_measured_stat_weights": dict(sorted(weights.items())),
        "real_catalogue_legal_items": item_check["legal_item_count"],
        "real_catalogue_top5_items_scored": item_check["tested_item_count"],
        "real_catalogue_slots_scored": item_check["slot_count"],
        # Comparable measured unit: one source-legal top-ilvl item x
        # applicable ordinary stat requirement, checked in the real selector.
        # Runtime-paid stat sensitivities establish causal context. Global
        # conditions may still fail P3; this fraction is NOT a gate PASS.
        "reachability_count": item_check["tested_stat_assertions"],
        "pass_count": item_check["verified_stat_assertions"],
        "behavior_probes_executed": result.get("evaluated", 0) + extra_evaluations,
        "partial_scope": "CURRENT_SOURCE_TOP5_ITEM_STAT_WEIGHT_ASSERTIONS",
        "coverage_basis": "executed_behavior_assertions",
        "coverage_scope_complete": False,
        "real_item_score_checked": item_check["source"] == "CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS",
        "real_measured_stat_weight_axes": sorted(weights),
        "actual_search_result_status": result.get("status"),
        "source_context_sha256": result.get("source_context_sha256"),
    }

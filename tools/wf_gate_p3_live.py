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
import os


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


def native_item_options_required(
        class_key: str, level: int, spec: str = "unrestricted") -> bool:
    """Use native ItemSparse only for targets with a source-backed native provider."""
    key = str(class_key).lower()
    profile = str(spec).lower()
    return (
        (key in ("priest", "mage") and level == 20)
        or (key == "shaman" and level == 20 and profile == "unrestricted")
        or (key == "paladin" and level == 20 and profile == "unrestricted")
        or (key == "mage" and level == 30 and profile == "unrestricted")
    )


def _p3_stat_witness_priority(ir, policy) -> tuple[str, ...]:
    """Order paid stat probes by their causal proximity to the selected policy.

    The P3 evaluation budget is shared and hard-capped. Alphabetically probing
    zero-weight axes spent Mage's remaining budget on Agility/Attack Power
    before the selected caster policy's Spell Power/Intellect witnesses.
    This is scheduling only: every accepted weight still requires a real paid
    before/after CombatRuntime witness; no value or applicability is inferred.
    """
    from src.game.checkpoint_p3_smoke import policy_uses_weapon_damage

    if policy_uses_weapon_damage(ir, policy):
        return (
            "attack_power", "strength", "agility", "hit", "crit",
            "spell_power", "intellect", "spirit", "mp5",
        )
    return (
        "spell_power", "intellect", "spirit", "mp5", "hit", "crit",
        "agility", "attack_power", "strength",
    )


def _native_item_stat_probe_deltas(item_check: dict, axis: str):
    """Return native item-sized deltas in descending measurement value.

    Candidate probes are the largest single positive stat amount among the
    selected legal top-five items and, when available, the sum from two
    different slots. Return the largest delta first so a tight paid-evaluation
    budget tests the strongest real item-sized perturbation before smaller
    deltas. The pair is a measured stat delta, not a jointly legal build claim.
    """
    best_by_slot = {}
    for slot, slot_report in item_check.get("slots", {}).items():
        for item in slot_report.get("items", ()):
            amount = item.get("stat_values", {}).get(axis)
            item_id = item.get("item_id")
            if (type(amount) not in (int, float)
                    or not isfinite(float(amount)) or float(amount) <= 0.
                    or type(item_id) is not int):
                continue
            candidate = {
                "slot": str(slot), "item_id": item_id,
                "name": str(item.get("name") or ""),
                "amount": float(amount),
            }
            previous = best_by_slot.get(str(slot))
            if (previous is None or candidate["amount"] > previous["amount"]
                    or (candidate["amount"] == previous["amount"]
                        and candidate["item_id"] < previous["item_id"])):
                best_by_slot[str(slot)] = candidate
    ranked = sorted(best_by_slot.values(),
                    key=lambda item: (-item["amount"], item["slot"], item["item_id"]))
    if not ranked:
        return (), []
    deltas = [ranked[0]["amount"]]
    sources = [{
        "kind": "single_native_item",
        "delta": ranked[0]["amount"],
        "items": [dict(ranked[0])],
    }]
    if len(ranked) >= 2:
        pair = ranked[:2]
        total = sum(item["amount"] for item in pair)
        if total > deltas[0]:
            deltas.append(total)
            sources.append({
                "kind": "two_distinct_native_item_slots",
                "delta": total,
                "items": [dict(item) for item in pair],
            })
    ordered = sorted(zip(deltas, sources), key=lambda pair: -pair[0])
    return (tuple(delta for delta, _source in ordered),
            [source for _delta, source in ordered])


def _paladin_policy_mana_constraint(ir, policy, record) -> dict:
    """Prove Intellect can affect this same combat objective before paying for it.

    A prefix spell having a mana cost is not enough: it was already cast in the
    paid baseline. Require a mana-costed action in the selected continuation,
    an exact executed-action trace, and evidence that the baseline pool could
    not pay that action again while the target was still alive. Between-pull
    recovery is deliberately outside this check.
    """
    def rejected(reason, **details):
        return {"eligible": False, "reason": reason, **details}

    resources = tuple(getattr(ir, "resources", ()) or ())
    mana = next((resource for resource in resources
                 if str(getattr(resource, "id", "")) == "mana"
                 and str(getattr(resource, "owner_actor_id", "")) ==
                 str(getattr(getattr(ir, "actor", None), "id", ""))), None)
    if mana is None or not bool(getattr(mana, "active_by_default", False)):
        return rejected("ACTOR_MANA_RESOURCE_UNAVAILABLE")
    initial_mana = getattr(mana, "initial_amount", None)
    if type(initial_mana) not in (int, float) or not isfinite(float(initial_mana)):
        return rejected("BASELINE_MANA_AMOUNT_UNAVAILABLE")
    if tuple(getattr(mana, "event_gain_rules", ()) or ()):
        return rejected("MANA_EVENT_GAIN_RULES_UNRESOLVED")

    selected = record.get("selected_actions")
    if not isinstance(selected, (list, tuple)) or not selected:
        return rejected("PAID_SELECTED_ACTION_TRACE_UNAVAILABLE")
    action_map = {str(action.id): action for action in tuple(getattr(ir, "actions", ()) or ())}
    selected_ids = []
    selected_mana_cost = 0.0
    mana_gained = 0.0
    for row in selected:
        if not isinstance(row, dict) or not isinstance(row.get("action_id"), str):
            return rejected("PAID_SELECTED_ACTION_TRACE_INVALID")
        action_id = row["action_id"]
        action = action_map.get(action_id)
        if action is None:
            return rejected("SELECTED_ACTION_MISSING_FROM_SOURCE_IR",
                            selected_action_id=action_id)
        selected_ids.append(action_id)
        for cost in tuple(getattr(action, "costs", ()) or ()):
            if str(getattr(cost, "resource_id", "")) != "mana":
                continue
            amount = float(getattr(cost, "amount", 0.0))
            if not isfinite(amount) or amount < 0.0:
                return rejected("SELECTED_MANA_COST_INVALID",
                                selected_action_id=action_id)
            selected_mana_cost += amount
        for effect in tuple(getattr(action, "effects", ()) or ()):
            if (str(getattr(effect, "resource_id", "")) != "mana"
                    or str(getattr(effect, "target", "")) not in ("actor", "self")):
                continue
            if (str(getattr(effect, "operation", "")) != "add"
                    or not hasattr(effect, "amount")):
                return rejected("SELECTED_MANA_GAIN_EFFECT_UNRESOLVED",
                                selected_action_id=action_id)
            amount = float(effect.amount)
            if not isfinite(amount):
                return rejected("SELECTED_MANA_GAIN_EFFECT_INVALID",
                                selected_action_id=action_id)
            mana_gained += amount

    policy_mana_action_costs = []
    for rule in tuple(getattr(policy, "rules", ()) or ()):
        action_id = str(getattr(rule, "action_id", ""))
        action = action_map.get(action_id)
        if action is None:
            return rejected("POLICY_ACTION_MISSING_FROM_SOURCE_IR",
                            policy_action_id=action_id)
        amount = sum(
            float(cost.amount) for cost in tuple(getattr(action, "costs", ()) or ())
            if str(getattr(cost, "resource_id", "")) == "mana")
        if amount > 0.0:
            policy_mana_action_costs.append({
                "action_id": action_id, "mana_cost": amount,
            })
    if not policy_mana_action_costs:
        return rejected(
            "NO_MANA_COSTED_POLICY_CONTINUATION",
            selected_action_ids=selected_ids,
            selected_mana_cost=selected_mana_cost,
            policy_mana_action_costs=[],
            initial_mana=float(initial_mana),
        )
    if selected_mana_cost <= 0.0:
        return rejected(
            "NO_SELECTED_IN_COMBAT_MANA_SPEND",
            selected_action_ids=selected_ids,
            policy_mana_action_costs=policy_mana_action_costs,
            initial_mana=float(initial_mana),
        )

    kill_s = record.get("kill_s")
    if type(kill_s) not in (int, float) or not isfinite(float(kill_s)) or float(kill_s) <= 0.0:
        return rejected("PAID_COMBAT_KILL_TIME_UNAVAILABLE")
    last_end = selected[-1].get("end_time_s")
    if type(last_end) not in (int, float) or not isfinite(float(last_end)):
        return rejected("PAID_SELECTED_ACTION_TIMING_UNAVAILABLE")

    mana_regenerated = max(
        0.0, float(getattr(mana, "regeneration_per_s", 0.0) or 0.0)
    ) * float(kill_s)
    mana_at_kill = (
        float(initial_mana) + mana_regenerated + mana_gained - selected_mana_cost)
    if not isfinite(mana_at_kill) or mana_at_kill < -1e-9:
        return rejected(
            "RECONSTRUCTED_MANA_TRACE_INCONSISTENT",
            selected_action_ids=selected_ids,
            selected_mana_cost=selected_mana_cost,
        )
    next_cost = min(row["mana_cost"] for row in policy_mana_action_costs)
    common = {
        "selected_action_ids": selected_ids,
        "selected_mana_cost": selected_mana_cost,
        "mana_gained_during_combat": mana_gained,
        "mana_regenerated_during_combat": mana_regenerated,
        "estimated_mana_at_kill": max(0.0, mana_at_kill),
        "next_policy_mana_cost": next_cost,
        "policy_mana_action_costs": policy_mana_action_costs,
        "last_selected_action_end_s": float(last_end),
        "kill_s": float(kill_s),
        "initial_mana": float(initial_mana),
    }
    if mana_at_kill >= next_cost - 1e-9:
        return rejected("BASELINE_MANA_REMAINS_ABOVE_NEXT_POLICY_COST", **common)
    if float(kill_s) <= float(last_end) + 1e-9:
        return rejected("TARGET_DIED_BEFORE_NEXT_MANA_COSTED_ACTION", **common)
    return {"eligible": True, "reason": "BASELINE_MANA_LIMITED_BEFORE_TARGET_DEATH",
            **common}


def _source_actor_context_summary(ir) -> dict:
    """Expose source actor/weapon provenance when the paid naked search blocks."""
    actor = getattr(ir, "actor", None)
    if actor is None:
        return {}
    metadata = getattr(actor, "metadata", {}) or {}
    try:
        base_stats = dict(getattr(actor, "base_stats", {}) or {})
    except (TypeError, ValueError):
        base_stats = {}
    actor_provenance = getattr(actor, "provenance", ()) or ()
    if not isinstance(actor_provenance, (list, tuple)):
        actor_provenance = (actor_provenance,)
    auto_attacks = []
    for attack in getattr(ir, "auto_attacks", ()) or ():
        source = getattr(attack, "damage_source", None)
        provenance = getattr(attack, "provenance", ()) or ()
        if not isinstance(provenance, (list, tuple)):
            provenance = (provenance,)
        auto_attacks.append({
            "id": getattr(attack, "id", None),
            "attack_type": getattr(attack, "attack_type", None),
            "required_mode_id": getattr(attack, "required_mode_id", None),
            "swing_time_s": getattr(attack, "swing_time_s", None),
            "damage_source": {
                "kind": getattr(source, "kind", None),
                "flat_dps": getattr(source, "flat_dps", None),
                "dps_stat_id": getattr(source, "dps_stat_id", None),
                "attack_power_stat_id": getattr(source, "attack_power_stat_id", None),
            },
            "provenance": list(provenance),
        })
    return {
        "state_status": getattr(actor, "state_status", None),
        "base_stats": base_stats,
        "base_stats_are_zero_proxy": metadata.get("base_stats_are_zero_proxy"),
        "race_key": metadata.get("race_key"),
        "actor_provenance": list(actor_provenance),
        "auto_attacks": auto_attacks,
    }


def _allow_cooldown_fallback_for_profile(class_key: str, level: int, spec: str) -> bool:
    """Enable cooldown continuations only for the Paladin L20 unrestricted P3 lane."""
    return (
        str(class_key).lower() == "paladin"
        and int(level) == 20
        and str(spec).lower() == "unrestricted"
    )


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    # Priest/Mage L20, unrestricted Shaman L20, and unrestricted Mage L30
    # P3 use native ItemSparse; other profiles/levels retain their existing path.
    native_required = native_item_options_required(class_key, level, spec)
    native_binary = (os.environ.get('FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN')
                     if native_required else None)
    if native_required and not native_binary:
        return {'status': 'BLOCKED',
                'reasons': ['P3_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED'],
                'production_component': 'src.game.native_p3_item_options'}

    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
    from src.v2.source_budgeted_gear import (
        run_source_budgeted_gear, paid_search_winner_baseline,
        paid_search_winner_baseline_validation, paid_source_policy_stat_witness)
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
    native_spell_facts = None
    native_spell_coefficients_applied = []
    native_spell_coefficients_error = None
    mage_l30_spellbook = (
        str(class_key).lower() == "mage" and int(level) == 30
        and str(spec).lower() == "unrestricted")
    shaman_l20_spellbook = (
        str(class_key).lower() == "shaman" and int(level) == 20
        and str(spec).lower() == "unrestricted")
    if mage_l30_spellbook or shaman_l20_spellbook:
        from src.game.native_p3_item_options import (
            NativeItemOptionsError, apply_native_mage_spell_coefficients,
            apply_native_shaman_lightning_bolt_coefficient,
            query_native_mage_spell_coefficients,
            query_native_shaman_spell_coefficients,
        )
        try:
            if shaman_l20_spellbook:
                native_spell_facts = query_native_shaman_spell_coefficients(native_binary)
                ir, native_spell_coefficients_applied = (
                    apply_native_shaman_lightning_bolt_coefficient(
                        ir, native_spell_facts))
            else:
                native_spell_facts = query_native_mage_spell_coefficients(native_binary)
                ir, native_spell_coefficients_applied = (
                    apply_native_mage_spell_coefficients(ir, native_spell_facts))
        except (NativeItemOptionsError, ValueError, TypeError, OSError) as exc:
            if shaman_l20_spellbook:
                # Native spell coefficient evidence is optional for this P3
                # continuation. Preserve the existing measured result and
                # report the exact refusal; never turn missing source data
                # into a guessed coefficient, weight or BLOCKED gate verdict.
                native_spell_coefficients_error = str(exc)
            else:
                return {
                    "status": "BLOCKED",
                    "reasons": [str(exc)],
                    "production_component": "src.game.native_p3_item_options",
                }
    native_player_context = None
    if (str(class_key).lower() == "paladin" and int(level) == 20
            and str(spec).lower() == "unrestricted"):
        # Source-backed actor and equipped-weapon facts come from the selected
        # Rust authority, never from the old zero-stat/14-DPS scenario proxy.
        # This is still a context-only query, not native L20 combat execution.
        from src.game.native_p3_player_context import (
            NativePlayerContextError, apply_native_player_context,
            query_native_player_context,
        )
        # The selected item-options engine is also the Paladin actor authority.
        # A second environment variable is optional; never silently fall back
        # to the zero-stat proxy when it is omitted.
        player_context_binary = (
            os.environ.get("FOREVER_P3_NATIVE_PLAYER_CONTEXT_BIN") or native_binary)
        try:
            native_player_context = query_native_player_context(
                player_context_binary, class_key, level)
            ir = apply_native_player_context(ir, native_player_context)
        except (NativePlayerContextError, ValueError, TypeError, KeyError) as exc:
            return {
                "status": "BLOCKED",
                "reasons": [str(exc)],
                "production_component": "src.game.native_p3_player_context",
            }
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
        allow_cooldown_fallback=_allow_cooldown_fallback_for_profile(class_key, level, spec))
    stages = result.get("stages") or []
    naked = next((x for x in stages if x.get("stage") == "source_naked"), None)
    sensitivity = next((x for x in result.get("sensitivity_history", ())
                        if x.get("stage") == "source_naked"
                        and isinstance(x.get("values"), dict)), None)
    # A cooldown-bound source action can now be explored by the real prefix
    # executor even when no zero-cooldown filler exists. Its observed score
    # is NOT P3 evidence when the selected actor or weapon is still a
    # scenario proxy. Do not turn a successful proxy search into an M1 row.
    fallback_id = str(((naked or {}).get("winner") or {}).get("fallback") or "")
    cooldown_fallback = any(
        getattr(action, 'id', None) == fallback_id
        and float(getattr(action, 'cooldown_s', 0) or 0) > 0
        for action in ir.actions)
    actor_proxy = getattr(ir.actor, "metadata", {}).get("base_stats_are_zero_proxy") is True
    weapon_proxy = any(
        "proxy" in str(source.get("caveat") or "")
        for attack in getattr(ir, 'auto_attacks', ())
        for source in getattr(attack, 'provenance', ())
        if isinstance(source, dict))
    if cooldown_fallback and (actor_proxy or weapon_proxy):
        return {
            "status": "BLOCKED",
            "reasons": ["P3_SOURCE_COOLDOWN_WINNER_HAS_PROXY_ACTOR_OR_WEAPON"],
            "production_component": "src.v2.source_budgeted_gear.run_source_budgeted_gear",
            "real_source_search_attempts": result.get("attempted", 0),
            "real_source_search_evaluated": 0,
            "diagnostic_proxy_search_evaluated": result.get("evaluated", 0),
            "source_naked_stage": {
                "search_backend": naked.get("search_backend"),
                "search_status": naked.get("search_status"),
                "attempted": naked.get("attempted", 0),
                "evaluated": naked.get("evaluated", 0),
                "blocked": naked.get("blocked", 0),
            },
            "source_naked_diagnostics": naked.get("source_search_diagnostics"),
            "source_actor_context": _source_actor_context_summary(ir),
        }
    if not naked or not naked.get("winner") or sensitivity is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_PRODUCTION_SEARCH_OR_MEASURED_WEIGHT_CONTEXT_UNAVAILABLE:"
            + str(result.get("status"))],
            "production_component": "src.v2.source_budgeted_gear.run_source_budgeted_gear",
            "real_source_search_attempts": result.get("attempted", 0),
            "real_source_search_evaluated": result.get("evaluated", 0),
            "source_naked_stage": ({
                "search_backend": naked.get("search_backend"),
                "search_status": naked.get("search_status"),
                "attempted": naked.get("attempted", 0),
                "evaluated": naked.get("evaluated", 0),
                "blocked": naked.get("blocked", 0),
            } if naked else None),
            "source_naked_diagnostics": (
                naked.get("source_search_diagnostics") if naked else None),
            "source_actor_context": _source_actor_context_summary(ir)}
    record = naked["winner"]
    native_spell_action_ids = {
        str(row.get("action_id")) for row in native_spell_coefficients_applied
        if isinstance(row, dict) and row.get("action_id")
    }
    native_fallback_action = str(record.get("fallback") or "") in native_spell_action_ids
    policy = _make_policy(
        ir, record["fallback"],
        guarded_action=record.get("guarded_action"),
        guarded_conditions=tuple(PolicyCondition(**x)
                                 for x in record.get("guarded_conditions", ())))
    weights = dict(sensitivity["values"])
    if not all(type(v) in (int, float) and isfinite(v) for v in weights.values()):
        return {"status": "FAIL", "reasons": ["P3_REAL_PRODUCTION_WEIGHTS_NONFINITE"]}
    # Native ItemSparse activation was required before paid search above;
    # non-target profiles continue through their existing P3 source path.
    try:
        item_check = fast_p3_smoke_for_policy(
            source_ir=ir, policy=policy, class_key=class_key, level=level,
            weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            native_options_binary=native_binary)
    except ValueError as exc:
        if native_binary is None:
            raise
        return {'status': 'BLOCKED', 'reasons': [str(exc)],
                'production_component': 'src.game.native_p3_item_options',
                'real_source_search_evaluated': result.get('evaluated', 0)}
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
    witness_priority = _p3_stat_witness_priority(ir, policy)
    witness_rank = {axis: index for index, axis in enumerate(witness_priority)}
    witness_blockers = sorted(
        (blocker for blocker in item_check["blockers"]
         if blocker.startswith("NONPOSITIVE_RELEVANT_WEIGHT:")),
        key=lambda blocker: (
            witness_rank.get(blocker.split(":", 1)[1], len(witness_rank)),
            blocker.split(":", 1)[1]))
    mage_l30_native = (
        str(class_key).lower() == "mage" and int(level) == 30
        and str(spec).lower() == "unrestricted"
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    shaman_l20_native = (
        shaman_l20_spellbook
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    paladin_l20_native = (
        str(class_key).lower() == "paladin" and int(level) == 20
        and str(spec).lower() == "unrestricted"
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    native_item_sized_probe = (
        mage_l30_native or shaman_l20_native or paladin_l20_native)
    if shaman_l20_native:
        # This issue is only the Spell Power witness. Other zero axes are
        # separate P3 defects. If the exact native coefficient/action was not
        # obtained, retain the existing score without attempting a substitute.
        witness_blockers = (
            [] if native_spell_coefficients_error else [
                blocker for blocker in witness_blockers
                if blocker == "NONPOSITIVE_RELEVANT_WEIGHT:spell_power"
            ])
    # The Shaman paid winner is eligible only when its actual fallback is the
    # exact, native-enriched rank-915 source action.
    native_spell_winner = (
        mage_l30_native or (shaman_l20_native and native_fallback_action))
    force_native_shaman_spell_power_witness = (
        shaman_l20_native and native_spell_winner
        and native_spell_coefficients_error is None
        and bool(native_spell_coefficients_applied))
    witness_axes = [blocker.split(":", 1)[1] for blocker in witness_blockers]
    if (force_native_shaman_spell_power_witness
            and "spell_power" not in witness_axes):
        # The native coefficient can make the initial CombatRuntime sensitivity
        # positive, removing the NONPOSITIVE blocker. Still require the explicit
        # paid source-policy witness for the exact native fallback action.
        witness_axes.insert(0, "spell_power")

    paladin_paid_winner_validation = None
    paladin_paid_winner_eligible = False
    paladin_mana_constraint = None
    paladin_paid_winner_policy = None
    if paladin_l20_native:
        paid_prefix = tuple(record.get("prefix") or ())
        # Keep the existing strict paid_search_winner_baseline predicate. The
        # detailed result below only explains a rejection; it does not relax it.
        paid_score = paid_search_winner_baseline(policy, record, paid_prefix)
        paladin_paid_winner_validation = paid_search_winner_baseline_validation(
            policy, record, paid_prefix)
        paladin_paid_winner_eligible = paid_score is not None
        if paladin_paid_winner_eligible != paladin_paid_winner_validation["accepted"]:
            raise AssertionError("PAID_SEARCH_WINNER_VALIDATOR_RESULT_MISMATCH")
        if paladin_paid_winner_eligible:
            paladin_paid_winner_policy = {
                "policy_id": str(policy.id),
                "opening_action_ids": list(paid_prefix),
                "selected_action_ids": [
                    row.get("action_id") for row in record.get("selected_actions", ())
                    if isinstance(row, dict)
                ],
                "fallback": record.get("fallback"),
                "guarded_action": record.get("guarded_action"),
                "guarded_conditions": list(record.get("guarded_conditions") or ()),
                "score_s_per_mob": paid_score,
            }
            paladin_mana_constraint = _paladin_policy_mana_constraint(
                ir, policy, record)
            # Agility is always first. Intellect is paid only when the exact
            # selected continuation is demonstrably mana-limited before kill;
            # prefix mana costs alone and between-pull recovery do not qualify.
            paladin_axes = [
                axis for axis in ("agility", "intellect")
                if f"NONPOSITIVE_RELEVANT_WEIGHT:{axis}" in witness_blockers
            ]
            witness_axes = (["agility"] if "agility" in paladin_axes else [])
            if (paladin_mana_constraint["eligible"]
                    and "intellect" in paladin_axes):
                witness_axes.append("intellect")
        else:
            # A rejected winner is not replaced with a generic delta or a
            # weaker source-IR baseline. Report the precise failed invariant.
            witness_axes = []
            source_policy_stat_witnesses.append({
                "stat": "agility",
                "status": "PAID_SEARCH_WINNER_BASELINE_REJECTED",
                "validation_reason": paladin_paid_winner_validation["reason"],
                "paid_evaluations": 0,
                "opening_action_ids": list(paid_prefix),
            })

    paid_winner_baseline_available = (
        (native_spell_winner and paid_search_winner_baseline(
            policy, record, tuple(record.get("prefix") or ())) is not None)
        or paladin_paid_winner_eligible
    )
    preferred_paid_winner = native_spell_winner or paladin_paid_winner_eligible
    for axis in witness_axes:
        if (weights.get(axis) != 0.0
                and not (force_native_shaman_spell_power_witness
                         and axis == "spell_power")):
            continue
        if native_item_sized_probe:
            probe_deltas, probe_delta_sources = _native_item_stat_probe_deltas(
                item_check, axis)
            # If native top-five items have no positive value for this axis,
            # do not fall back to guessed generic deltas.
            if not probe_deltas:
                continue
        else:
            probe_deltas = (5., 20.)
            probe_delta_sources = []
        remaining = max(0, max_p3_evaluations - int(result.get("attempted", 0)) - extra_evaluations)
        cache_prefix = (id(ir), int(level), bool(schedule_incoming_attacks))
        has_reusable_baseline = any(
            key[:3] == cache_prefix
            and type(value) in (int, float)
            and isfinite(value) and value > 0
            for key, value in source_policy_baseline_cache.items()
        )
        minimum_evaluations = (
            1 if (has_reusable_baseline or paid_winner_baseline_available)
            else (3 if native_item_sized_probe and record.get("prefix") else 2)
        )
        if remaining < minimum_evaluations:
            break
        witness = paid_source_policy_stat_witness(
            ir, stat=axis, level=level, probe_deltas=probe_deltas,
            max_evaluations=remaining,
            schedule_incoming_attacks=schedule_incoming_attacks,
            baseline_cache=source_policy_baseline_cache,
            opening_action_ids=tuple(record.get("prefix", ())),
            preferred_policy=(policy if preferred_paid_winner else None),
            baseline_record=(record if preferred_paid_winner else None),
            allow_paid_winner_after_nonpositive=(
                native_fallback_action and (mage_l30_native or shaman_l20_native)),
            prefer_paid_search_winner=paladin_paid_winner_eligible)
        if native_item_sized_probe:
            witness["probe_delta_sources"] = probe_delta_sources
        extra_evaluations += int(witness["paid_evaluations"])
        source_policy_stat_witnesses.append(witness)
        if witness["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS":
            weights[axis] = witness["weight_s_saved_per_mob_per_unit"]
    if any(w["status"] == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS"
           for w in source_policy_stat_witnesses):
        item_check = fast_p3_smoke_for_policy(
            source_ir=ir, policy=policy, class_key=class_key, level=level,
            weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            native_options_binary=native_binary)
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
        "paid_search_winner_baseline_validation": paladin_paid_winner_validation,
        "paid_search_winner_policy": paladin_paid_winner_policy,
        "paladin_in_combat_mana_constraint": paladin_mana_constraint,
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
        "real_item_score_checked": item_check["source"] in (
            "CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS", "MYTHICSIM_NATIVE_ITEM_OPTIONS"),
        "item_options_source": item_check["source"],
        "native_item_options_status": item_check.get("native_item_options_status"),
        "native_unverified_candidate_count": item_check.get("native_unverified_candidate_count", 0),
        "native_excluded_non_client_item_count": item_check.get(
            "native_excluded_non_client_item_count", 0),
        "native_item_options_source": item_check.get("native_item_options_source"),
        "real_measured_stat_weight_axes": sorted(weights),
        "actual_search_result_status": result.get("status"),
        "source_context_sha256": result.get("source_context_sha256"),
        "native_spell_coefficients_source": (
            native_spell_facts.get("source") if native_spell_facts else None),
        "native_spell_coefficients_engine_revision": (
            native_spell_facts.get("engine_revision") if native_spell_facts else None),
        "native_spell_coefficients_applied": native_spell_coefficients_applied,
        "native_spell_coefficients_error": native_spell_coefficients_error,
        "native_paid_winner_spell_probe_enabled": native_fallback_action,
        "native_player_context_id": (
            native_player_context.get("source_context_id")
            if native_player_context else None),
        "native_player_context_scope": (
            native_player_context.get("source_scope")
            if native_player_context else None),
        "native_player_context_kind": (
            native_player_context.get("context_kind")
            if native_player_context else None),
        "native_player_context_race": (
            native_player_context.get("race") if native_player_context else None),
        "native_player_context_base_stats": (
            dict(native_player_context.get("base_stats") or {})
            if native_player_context else {}),
        "native_player_context_resources": (
            dict(native_player_context.get("resources") or {})
            if native_player_context else {}),
        "native_player_context_weapon": (
            dict(native_player_context.get("weapon") or {})
            if native_player_context else {}),
        "native_player_context_unresolved_fields": (
            native_player_context.get("unsupported_fields", ())
            if native_player_context else ()),
    }

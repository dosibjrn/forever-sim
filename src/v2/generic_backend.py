from __future__ import annotations

"""Capability-limited Generic WoW backend publication.

G03 created an independently executable producer. G04–G06 filled the common
DecisionRecord from source-backed/tuned Game IR. G07–G09 built the generic
stateful/periodic event runtime. G10 maps a source-backed combat slice directly
into the shared canonical Evaluation; G11–G14 add multi-action execution, recovery,
talents and parity diagnostics. G15 makes canonical Policy IR the runtime authority;
G16 adds bounded structural policy search; G17 adds bounded numeric threshold search;
G18 adds conservative pruning/cache; G19 searches legal Talent IR allocations and
feeds every candidate through that same policy/runtime/Evaluation stack. G20 adds
named gear + exact scorer sensitivities; G21 closes the explicit bounded fixed point.
G22 publishes native CandidateResult / LevelFrontier objects from those generic scorer states.
G23 adds reusable Mode transitions; G24 adds generic repeated AutoAttack swing execution; G25 adds generic active-resource regeneration and Cat action gating. G26 adds target-bound resources and builder/finisher threshold search. G27 adds generic event-driven Resource gain/cap/spend semantics. G28 adds generic incoming attack, Armor mitigation, survivability and projected resource-trigger basis semantics. G29 adds Bear as a real generic Mode/action policy; G30 makes cross-mode transitions searchable Policy IR; G31 adds generic runtime event -> Effect triggers and makes Thorns reactive damage executable.
The backend never reads legacy route rows.
"""

from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from typing import Iterable

from src.class_registry import get_definition, ClassRegistryError
from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.gear import select_named_gear
from src.game.model import ActionDefinition, ControlEffect, DamageEffect, HealEffect, ModeChangeEffect, PeriodicEffect, PeriodicHealEffect, ResourceCost, SummonEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility, execute_action, execute_action_timeline, execute_repeated_actions
from src.game.runtime.multi_actor_probe import execute_multi_actor_mechanics_probe
from src.game.runtime.hunter_pet_slice import search_hunter_pet_policy
from src.game.runtime.timed_summon_probe import execute_timed_summon_mechanics_probe
from src.game.policy import execute_priority_policy
from src.game.policy_search import search_priority_policy
from src.game.policy_threshold_search import search_policy_thresholds
from src.game.policy_search_efficiency import PolicyEvaluationCache
from src.game.evaluation import Evaluation, evaluation_from_combat_timeline, evaluation_with_recovery
from src.game.recovery import recover_actor_to_full
from src.game.gear import apply_gear_selection, EXECUTABLE_CASTER_GEAR_STATS
from src.game.stat_sensitivity import measure_stat_sensitivities
from src.game.fixed_point import run_optimizer_fixed_point
from src.game.talents import apply_talent_selection
from src.game.talent_search import search_talent_allocations, talent_candidate_id
from src.shared.leveling.objective import representative_hp
from src.version import SOFTWARE_VERSION
from .backend_decision import DecisionRecord


GENERIC_BACKEND_ID = "generic"
GENERIC_IMPLEMENTATION = "generic_wow_backend"
RUNTIME_PROBE_TARGET_HEALTH = 50.0

# Missing reusable mechanic families.  Per-record publication removes an item
# from this list only when the selected class/level has that capability natively.
GENERIC_UNSUPPORTED_MECHANICS = (
    "canonical_game_ir",
    "exact_tuning_for_approximate_overlays",
    "combat_event_runtime",
    "resource_state_evaluation",
    "gcd_cooldown_readiness",
    "action_effect_execution",
    "combat_evaluation",
    "recovery_evaluation",
    "travel_evaluation",
    "combat_attack_table_resolution",
    "periodic_effect_runtime",
    "aura_refresh_replace",
    "policy_execution",
    "policy_search",
    "policy_threshold_search",
    "talent_modifier_evaluation",
    "talent_search",
    "gear_optimization",
    "stat_weight_evaluation",
    "level_frontier_generation",
    "mode_transition_runtime",
    "auto_attack_runtime",
    "energy_resource_runtime",
    "target_bound_resource_runtime",
    "builder_finisher_policy_search",
    "event_driven_resource_gain",
    "incoming_player_damage_runtime",
    "armor_mitigation_runtime",
    "survivability_state",
    "incoming_resource_trigger_basis",
    "mode_action_policy_search",
    "cross_mode_policy_search",
    "event_trigger_runtime",
    "class_pet_policy_modifiers",  # G35: scoped L24-L31 Hunter slice
    "timed_summon_class_availability_and_damage_fidelity",  # G36 mechanics-only sourced timer
    "route_solving",
)


@lru_cache(maxsize=1)
def _multi_actor_engine_proof() -> dict:
    """G34 engine capability proof, intentionally not a class combat score."""
    return execute_multi_actor_mechanics_probe()


@lru_cache(maxsize=1)
def _timed_summon_engine_proof() -> dict:
    """Source-timed lifecycle with explicitly synthetic damage; not a class score."""
    return execute_timed_summon_mechanics_probe()


@lru_cache(maxsize=8)
def _hunter_pet_slice_proof(level: int) -> dict:
    """One real generic Hunter+pet combat path, scoped to pinned skill ranks."""
    return search_hunter_pet_policy(level=level)


def backend_metadata() -> dict:
    return {
        "id": GENERIC_BACKEND_ID,
        "version": SOFTWARE_VERSION,
        "implementation": GENERIC_IMPLEMENTATION,
        "status": "partial_combat_recovery_evaluation",
        "independent": True,
    }





def _policy_combat_evaluation(ir_slice, *, level: int, policy_override=None,
                              post_combat_action_ids: tuple[str, ...] = (),
                              schedule_incoming_attacks: bool = False,
                              attacker_relative_position: str | None = None,
                              opening_action_ids: tuple[str, ...] = (),
                              prefix_cache: dict | None = None,
                              stop_after_opening_actions: int | None = None,
                              max_new_event_transitions: int | None = None,
                              cpu_deadline_ns: int | None = None,
                              wall_deadline_ns: int | None = None):
    policy = policy_override or (ir_slice.policies[0] if ir_slice.policies else None)
    if policy is None:
        return None, None, None
    searched = bool(policy.provenance.get("search_performed"))
    actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
    # Search and full-cycle replay must start with the same source maintenance
    # auras and the same charged casts. Previously source L2 screened naked
    # while L3 always pre-buffed, so candidate ordering was on DIFFERENT games.
    from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
    upkeep_s,upkeep_casts,upkeep_events = _execute_source_maintenance_upkeep(
        ir_slice,actor,max_new_event_transitions=max_new_event_transitions,
        cpu_deadline_ns=cpu_deadline_ns,wall_deadline_ns=wall_deadline_ns)
    from src.game.runtime.simulator import EventTransitionBudgetExceeded
    if max_new_event_transitions is not None and upkeep_events >= max_new_event_transitions:
        raise EventTransitionBudgetExceeded(upkeep_events)
    target_hp = float(representative_hp(level))
    from src.game.data.forever.target_combat_source import target_combat_metadata
    defense = (target_combat_metadata(ir_slice) if
               ir_slice.provenance.get('target_combat_profile') else {})
    target = TargetState.with_health(
        f"canonical_leveling_target_L{int(level)}", target_hp,
        **defense,
        source_status="source_backed_canonical_leveling_reference",
        authority="src.shared.leveling.objective.MOB_BASE_HP",
        source_basis="CMaNGOS warrior-class BaseHealthExp0 ordinary melee target curve",
        level=int(level),
    )
    if attacker_relative_position is not None:
        target.metadata['attacker_relative_position'] = str(attacker_relative_position)
    runtime = CombatRuntime(
        actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)),
        auto_attacks=ir_slice.auto_attacks,
        companions=tuple(ActorState.from_ir(d, ()) for d in ir_slice.companions),
        timed_summons=ir_slice.timed_summons,
        incoming_attacks=(ir_slice.incoming_attacks if schedule_incoming_attacks else ()),
        mitigation_rules=(ir_slice.mitigation_rules if schedule_incoming_attacks else ()),
        triggers=(ir_slice.triggers if schedule_incoming_attacks else ())
    )
    # Exact event-state checkpointing is optional. The key contains the full
    # source IR (including gear/talents), engine version, scenario and incoming
    # schedule. No snapshot is shared between changed configurations.
    from copy import deepcopy
    from hashlib import sha256
    from json import dumps
    from src.version import SOFTWARE_VERSION
    from time import process_time_ns
    checkpoint_context = sha256(dumps({
        'engine': SOFTWARE_VERSION, 'ir': ir_slice.as_dict(), 'level': int(level),
        'incoming': bool(schedule_incoming_attacks),
        'relative_position': attacker_relative_position,
        'scenario': 'representative_hp+combat_recovery_survival',
        'seed': 'expected_value_deterministic',
    }, sort_keys=True, default=str).encode()).hexdigest()
    opening_action_ids = tuple(opening_action_ids)
    resumed = ()
    checkpoint_hit_length = 0
    saved_prefixes = 0
    if prefix_cache is not None and opening_action_ids:
        for length in range(len(opening_action_ids), 0, -1):
            found = prefix_cache.get((checkpoint_context, opening_action_ids[:length]))
            if found is not None and (stop_after_opening_actions is None or length < stop_after_opening_actions):
                runtime, resumed = deepcopy(found)
                actor, target = runtime.actor, runtime.target
                checkpoint_hit_length = length
                break
    transitions_before = runtime.event_transitions
    runtime.event_budget_start = transitions_before
    runtime.event_budget_cap = (None if max_new_event_transitions is None
                                else max_new_event_transitions - upkeep_events)
    runtime.cpu_deadline_ns = cpu_deadline_ns
    runtime.wall_deadline_ns = wall_deadline_ns
    cpu_start_ns = process_time_ns()
    def capture_prefix(prefix, current_runtime, selected):
        nonlocal saved_prefixes
        if prefix_cache is not None:
            key = (checkpoint_context, prefix)
            if key not in prefix_cache:
                prefix_cache[key] = deepcopy((current_runtime, selected))
                saved_prefixes += 1
    execution = execute_priority_policy(
        policy=policy, actions=ir_slice.actions, runtime=runtime, max_actions=256,
        opening_action_ids=opening_action_ids, resume_selected_actions=resumed,
        stop_after_opening_actions=stop_after_opening_actions,
        on_opening_action=capture_prefix if prefix_cache is not None else None,
    )
    new_transitions = runtime.event_transitions - transitions_before + upkeep_events
    measured_cpu_ns = process_time_ns() - cpu_start_ns
    checkpoint_evidence = {
        'checkpoint_context': checkpoint_context,
        'checkpoint_hit_length': checkpoint_hit_length,
        'checkpoint_new_prefixes': saved_prefixes,
        'event_transitions_new': new_transitions,
        'event_transitions_total': runtime.event_transitions + upkeep_events,
        'source_maintenance_casts': upkeep_casts,
        'source_maintenance_elapsed_s': upkeep_s,
        'source_maintenance_events': upkeep_events,
        'executor_cpu_ns': measured_cpu_ns,
        'remaining_queue_events': len(runtime.queue),
    }
    if stop_after_opening_actions is not None:
        return None, execution, {
            'status': ('PARTIAL_REAL_EXECUTOR' if execution.stopped_reason == 'PARTIAL_OPENING_CHECKPOINT' or execution.timeline.target_defeated else 'BLOCKED_PARTIAL_EXECUTOR'),
            'stop_reason': execution.stopped_reason, 'terminal_objective': None,
            'target_health_remaining': float(target.health),
            'actor_resources': dict(actor.resources),
            'actor_time_s': float(actor.current_time_s),
            'active_actor_auras': sorted(actor.active_auras),
            'active_target_auras': sorted(target.active_auras),
            **checkpoint_evidence,
        }
    timeline = execution.timeline
    # A kill after the player's death is not a valid leveling encounter.
    incoming_health_ids = {str(attack.health_resource_id) for attack in ir_slice.incoming_attacks} if schedule_incoming_attacks else set()
    actor_survived = all(actor.resource_positive(resource_id) for resource_id in incoming_health_ids)
    if not timeline.target_defeated or not actor_survived:
        return None, execution, {
            "policy": policy.as_dict(),
            "stop_reason": ("actor_died" if not actor_survived else execution.stopped_reason or "target_not_defeated"),
            "target_health": target_hp,
            "actor_survived": actor_survived,
            "incoming_hit_count": sum(e.kind == "IncomingAttackResolved" for e in timeline.events),
            "search_performed": searched,
            **checkpoint_evidence,
        }
    action_names = {action.id: action.name for action in ir_slice.actions}
    talent_application = dict(ir_slice.provenance.get("talent_application") or {})
    combat_evaluation = evaluation_from_combat_timeline(
        timeline,
        action_name_by_id=action_names,
        provenance={
            "producer": "generic_searched_policy_ir" if searched else "generic_canonical_policy_ir",
            "policy": policy.as_dict(),
            "selected_actions": [dict(x) for x in execution.selected_actions],
            "target": dict(target.metadata),
            "spell_power": float(actor.stats.get("spell_power", 0.0)),
            "talent_application": talent_application,
            "incoming_schedule_executed": bool(schedule_incoming_attacks and ir_slice.incoming_attacks),
            "incoming_hit_count": sum(e.kind == "IncomingAttackResolved" for e in timeline.events),
        },
        fidelity={
            "rating": "expected_value_naked_actor_searched_policy" if searched else "expected_value_naked_actor_canonical_policy",
            "source_backed_actor": True,
            "source_backed_target_hp": True,
            "policy_search": searched,
            "maintenance_execution": bool(upkeep_casts),
            "limitations": [
                ("bounded action inclusion/exclusion + priority-order + numeric-condition threshold search" if policy.provenance.get("threshold_search_performed") else "bounded action inclusion/exclusion + priority-order search" if searched else "canonical supplied Policy IR; policy search starts later"),
                "single-pull source upkeep is paid in full, not amortized; persistent 100-mob evaluation owns final ranking",
                "Mark of the Wild: exact source armor/attributes and sourced conversions execute; intellect-to-mana and spirit regeneration not yet verified",
                ("source-cadenced ordinary incoming hits executed on the production combat clock; derived avoidance, base Armor and attack timing remain unverified" if schedule_incoming_attacks else "ordinary incoming attacks not scheduled; opt-in requires sourced actor mitigation stat"),
                ("naked source-backed actor; gear not yet applied; explicit source-backed talent seed applied" if talent_application else "naked source-backed actor; gear/talents not yet applied"),
                "expected-value damage; hit/crit/resist/variance not yet resolved",
                "recovery and travel are not part of this combat-only Evaluation",
            ],
        },
    )
    # Mode candidates must leave their combat form before ordinary recovery.
    # Execute the *source-defined* zero-time exit through the same generic
    # runtime.  Do not allow arbitrary post-kill healing, free mana or a
    # synthetic form reset masquerading as a valid recovery transition.
    post_combat = []
    if post_combat_action_ids:
        action_map = {action.id: action for action in ir_slice.actions}
        initial_mode = next((m.id for m in ir_slice.modes if m.initial), None)
        if initial_mode is None or len(post_combat_action_ids) != 1:
            raise ValueError("post-combat mode exit needs one source action and initial mode")
        action = action_map.get(post_combat_action_ids[0])
        if (action is None or action.costs or float(action.cast_time_s) != 0.0
                or float(action.gcd_s) != 0.0 or len(action.effects) != 1
                or not isinstance(action.effects[0], ModeChangeEffect)
                or action.effects[0].target_mode_id != initial_mode
                or not action.provenance):
            raise ValueError("post-combat mode exit is not a sourced zero-time transition")
        from_mode = actor.current_mode_id
        if from_mode == initial_mode:
            raise ValueError("post-combat mode exit requested without an active alternate mode")
        eligibility = action_eligibility(action=action, actor=actor, target=target)
        if not eligibility.eligible:
            raise ValueError(f"post-combat mode exit unavailable: {eligibility.reason}")
        runtime.schedule_action(action)
        if actor.current_mode_id != initial_mode:
            raise ValueError("post-combat mode exit did not restore initial mode")
        post_combat.append({"action_id": action.id, "from_mode": from_mode,
                            "to_mode": initial_mode, "time_s": float(actor.current_time_s),
                            "source": [dict(x) for x in action.provenance]})
    recovery = recover_actor_to_full(
        actor=actor, level=int(level), actions=ir_slice.actions,
        start_time_s=float(timeline.target_death_s), healing_power=float(actor.stats.get("spell_power", 0.0)),
    )
    evaluation = evaluation_with_recovery(combat_evaluation, recovery)
    if upkeep_s:
        # This is a deliberately one-mob score (the upfront cost appears once).
        # We DO NOT use it as a fake 100-mob average. True full-cycle scoring
        # remains the persistent finalist's one-actor repeated runtime.
        score=float(evaluation.score_s_per_100)+100.*upkeep_s
        evaluation=replace(evaluation,score_s_per_100=score,
            mobs_per_hour=(360000./score),
            diagnostics={**dict(evaluation.diagnostics),
                'source_maintenance_s':upkeep_s,'source_maintenance_casts':upkeep_casts,
                'source_maintenance_events':upkeep_events},
            provenance={**dict(evaluation.provenance),'paid_source_upkeep':'real_actions_before_pull'},
            fidelity={**dict(evaluation.fidelity),
                'maintenance_execution':True})
    return evaluation, execution, {
        "policy": policy.as_dict(),
        "selection": ("bounded searched Policy IR priority" if searched else "canonical Policy IR priority; no search"),
        "search_performed": searched,
        "target_health": target_hp,
        "target_source_status": target.metadata.get("source_status"),
        "incoming_hit_count": sum(e.kind == "IncomingAttackResolved" for e in timeline.events),
        "actor_survived": actor_survived,
        "incoming_schedule_executed": bool(schedule_incoming_attacks and ir_slice.incoming_attacks),
        "recovery": recovery.as_dict(),
        **checkpoint_evidence,
        **({"post_combat_mode_actions": post_combat,
            "recovery_mode_id": actor.current_mode_id} if post_combat_action_ids else {}),
    }


def _searched_policy_combat_evaluation(ir_slice, *, level: int):
    seed_policy = ir_slice.policies[0] if ir_slice.policies else None
    if seed_policy is None:
        return None, None, None, None

    def evaluate_candidate(policy):
        evaluation, execution, metadata = _policy_combat_evaluation(
            ir_slice, level=level, policy_override=policy,
        )
        return (
            None if evaluation is None else evaluation.seconds_per_mob,
            {
                "stop_reason": None if execution is None else execution.stopped_reason,
                "target_defeated": bool(execution is not None and execution.timeline.target_defeated),
                "action_count": 0 if execution is None else len(execution.selected_actions),
            },
        )

    evaluation_cache = PolicyEvaluationCache(
        actions=ir_slice.actions, expensive_evaluate=evaluate_candidate,
    )
    structural_search = search_priority_policy(
        seed_policy, evaluate=evaluation_cache.evaluate, max_candidates=64,
    )
    if structural_search.selected_policy is None:
        return None, None, None, structural_search, None, evaluation_cache.as_dict()
    threshold_search = search_policy_thresholds(
        seed_policy, structural_search=structural_search, actions=ir_slice.actions,
        evaluate=evaluation_cache.evaluate, max_candidates=128,
    )
    selected = threshold_search.selected_policy or structural_search.selected_policy
    efficiency = evaluation_cache.as_dict()
    selected = replace(
        selected,
        provenance={
            **dict(selected.provenance),
            "search_efficiency": efficiency,
        },
    )
    evaluation, execution, metadata = _policy_combat_evaluation(
        ir_slice, level=level, policy_override=selected,
    )
    if metadata is not None:
        metadata = {
            **dict(metadata),
            "policy_search": structural_search.as_dict(),
            "policy_threshold_search": threshold_search.as_dict(),
            "policy_search_efficiency": evaluation_cache.as_dict(),
        }
    return evaluation, execution, metadata, structural_search, threshold_search, efficiency

def _event_resource_gain_probe(ir_slice):
    """Exercise one source-declared event-driven Resource without class branches.

    The canonical source rule may require a mode that is not yet represented
    (Bear arrives in G29). For this mechanics probe only, the same rule is
    activated without that future mode requirement; its event kind, formula and
    capacity remain source-declared.
    """
    if ir_slice is None:
        return None
    resource = next((r for r in ir_slice.resources if tuple(getattr(r, "event_gain_rules", ()) or ())), None)
    if resource is None or resource.capacity is None:
        return None
    rule = tuple(resource.event_gain_rules)[0]
    multiplier = float(rule.multiplier)
    if multiplier <= 0.0 and float(rule.flat_amount) <= 0.0:
        return None
    probe_rule = replace(rule, required_mode_id=None)
    probe_resource = replace(resource, active_by_default=True, event_gain_rules=(probe_rule,))
    actor = ActorState.from_ir(ir_slice.actor, (probe_resource,), ())
    target = TargetState.with_health("event_resource_gain_probe_target", 1000.0, source_status="synthetic_runtime_probe")
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=())
    spend_cost = min(15.0, float(resource.capacity))
    spender = ActionDefinition(
        id="event-resource-spender-probe", family_key="event_resource_spender_probe",
        name="Event resource spender probe", owner_actor_id=actor.id, requirements=(),
        costs=(ResourceCost(resource_id=str(resource.id), amount=spend_cost),),
        cast_time_s=0.0, gcd_s=0.0, cooldown_s=0.0, effects=(),
        provenance=({"authority": "generic_mechanics_probe", "g27": True},),
    )
    before_eligibility = action_eligibility(action=spender, actor=actor, target=target)
    target_gain = min(float(resource.capacity), max(spend_cost, 20.0))
    if multiplier > 0.0:
        event_value = max(0.0, (target_gain - float(rule.flat_amount)) / multiplier)
    else:
        event_value = 0.0
    queued = runtime.emit_resource_event(
        str(rule.event_kind), source_action_id=None,
        **{str(rule.event_value_field): float(event_value), "probe": True},
    )
    after_gain = float(actor.resource_amount(str(resource.id)) or 0.0)
    after_eligibility = action_eligibility(action=spender, actor=actor, target=target)
    after_spend = after_gain
    if after_eligibility.eligible:
        runtime.schedule_action(spender)
        after_spend = float(actor.resource_amount(str(resource.id)) or 0.0)
    gains = [e for e in runtime.result().events if e.kind == "ResourceEventGain"]
    return {
        "resource_id": str(resource.id), "capacity": float(resource.capacity),
        "rule_id": str(rule.id), "event_kind": str(rule.event_kind),
        "event_value_field": str(rule.event_value_field), "multiplier": multiplier,
        "flat_amount": float(rule.flat_amount), "canonical_required_mode_id": rule.required_mode_id,
        "event_value": float(event_value), "queued_gain_count": int(queued),
        "resource_before": 0.0, "resource_after_gain": after_gain,
        "spender_cost": float(spend_cost),
        "spender_eligible_before_gain": bool(before_eligibility.eligible),
        "spender_eligible_after_gain": bool(after_eligibility.eligible),
        "resource_after_spend": after_spend,
        "gain_events": [e.as_dict() for e in gains],
        "mode_activation_status": "mechanics_probe_bypasses_future_mode_only; canonical rule unchanged",
        "legacy_fallback": False,
    }


def _incoming_damage_probe(ir_slice):
    """Exercise canonical incoming attack/mitigation + Rage-basis projection.

    Bear mode itself arrives in G29, so this mechanics probe only bypasses the
    future mode requirement on the already-canonical Rage gain rule.
    """
    if ir_slice is None or not ir_slice.incoming_attacks or not ir_slice.mitigation_rules:
        return None
    attack = ir_slice.incoming_attacks[0]
    health = next((r for r in ir_slice.resources if str(r.id) == str(attack.health_resource_id)), None)
    rage = next((r for r in ir_slice.resources if str(r.id) == "rage" and tuple(r.event_gain_rules or ())), None)
    if health is None or rage is None:
        return None
    rage_rules = tuple(replace(rule, required_mode_id=None) for rule in rage.event_gain_rules)
    probe_rage = replace(rage, active_by_default=True, event_gain_rules=rage_rules)

    def run(armor: float):
        probe_actor_def = replace(
            ir_slice.actor,
            base_stats={**dict(ir_slice.actor.base_stats), "armor": float(armor)},
            metadata={**dict(ir_slice.actor.metadata), "g28_probe_armor": float(armor)},
        )
        actor = ActorState.from_ir(probe_actor_def, (health, probe_rage), ())
        target = TargetState.with_health("incoming_damage_probe_target", 1000.0, source_status="synthetic_runtime_probe")
        runtime = CombatRuntime(actor=actor, target=target, auto_attacks=())
        health_before = float(actor.resource_amount(str(health.id)) or 0.0)
        rage_before = float(actor.resource_amount(str(rage.id)) or 0.0)
        resolved = runtime.resolve_incoming_attack(attack, mitigation_rules=ir_slice.mitigation_rules)
        health_after = float(actor.resource_amount(str(health.id)) or 0.0)
        rage_after = float(actor.resource_amount(str(rage.id)) or 0.0)
        projected = [e for e in runtime.result().events if e.kind == "IncomingEventProjected"]
        gains = [e for e in runtime.result().events if e.kind == "ResourceEventGain" and e.payload.get("resource_id") == str(rage.id)]
        return {
            "armor": float(armor), "health_before": health_before, "health_after": health_after,
            "health_damage": health_before - health_after, "rage_before": rage_before, "rage_after": rage_after,
            "rage_gained": rage_after - rage_before, "resolved": dict(resolved),
            "projected_events": [e.as_dict() for e in projected],
            "rage_gain_events": [e.as_dict() for e in gains],
            "actor_alive": actor.resource_positive(str(health.id)),
        }

    low = run(0.0)
    high = run(1000.0)
    projection = attack.event_projections[0] if attack.event_projections else None
    return {
        "status": "executed", "incoming_attack_id": str(attack.id),
        "mitigation_rule_id": attack.mitigation_rule_id,
        "health_resource_id": str(attack.health_resource_id),
        "raw_damage": float(attack.raw_damage), "hit_chance": float(attack.hit_chance),
        "projection_event_kind": (None if projection is None else str(projection.event_kind)),
        "projection_source_value_field": (None if projection is None else str(projection.source_value_field)),
        "projection_multiplier": (None if projection is None else float(projection.multiplier)),
        "zero_armor": low, "high_armor": high,
        "real_armor_changes_health_damage": bool(high["health_damage"] + 1e-12 < low["health_damage"]),
        "rage_basis_independent_of_real_armor": bool(abs(high["rage_gained"] - low["rage_gained"]) <= 1e-12),
        "mode_activation_status": "mechanics_probe_bypasses_future_bear_mode_only; canonical rule unchanged",
        "legacy_fallback": False,
    }


def _builder_finisher_policy_search_probe(ir_slice, *, level: int):
    """Run any source-declared target-resource builder/finisher policy generically.

    The source adapter declares the seed policy and its entry Action.  This
    orchestrator never branches on class/action names; the same shape is ready
    for Rogue combo-point builders/finishers.
    """
    seed_policy = next((
        p for p in ir_slice.policies
        if str(p.provenance.get("g26_scope") or "") == "builder_finisher_threshold_seed"
    ), None)
    if seed_policy is None:
        return None
    entry_action_id = str(seed_policy.provenance.get("entry_action_id") or "")
    action_map = {str(a.id): a for a in ir_slice.actions}
    entry_action = action_map.get(entry_action_id)
    if entry_action_id and entry_action is None:
        return {"status": "unavailable", "error": "declared entry action missing", "legacy_fallback": False}

    target_hp = float(representative_hp(level))

    def evaluate_candidate(policy):
        actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
        target = TargetState.with_health(
            f"generic_builder_finisher_target_L{int(level)}", target_hp,
            source_status="source_backed_canonical_leveling_reference", level=int(level),
        )
        runtime = CombatRuntime(
            actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)),
            auto_attacks=ir_slice.auto_attacks,
        )
        if entry_action is not None:
            eligibility = action_eligibility(action=entry_action, actor=actor, target=target)
            if not eligibility.eligible:
                return None, {"stop_reason": eligibility.reason, "target_defeated": False}
            runtime.schedule_action(entry_action)
            if actor.gcd_ready_s > actor.current_time_s:
                runtime.advance_to(actor.gcd_ready_s)
        execution = execute_priority_policy(
            policy=policy, actions=ir_slice.actions, runtime=runtime, max_actions=256,
        opening_action_ids=opening_action_ids,
        )
        timeline = execution.timeline
        return (
            None if not timeline.target_defeated else float(timeline.target_death_s),
            {
                "stop_reason": execution.stopped_reason,
                "target_defeated": bool(timeline.target_defeated),
                "action_count": len(execution.selected_actions),
                "selected_action_ids": [str(x["action_id"]) for x in execution.selected_actions],
                "ending_target_resources": dict(runtime.target.resources),
            },
        )

    structural = search_priority_policy(seed_policy, evaluate=evaluate_candidate, max_candidates=16)
    thresholds = search_policy_thresholds(
        seed_policy, structural_search=structural, actions=ir_slice.actions,
        evaluate=evaluate_candidate, max_candidates=64,
    )
    selected = thresholds.selected_policy or structural.selected_policy
    if selected is None:
        return {
            "status": "unavailable", "policy_search": structural.as_dict(),
            "policy_threshold_search": thresholds.as_dict(), "legacy_fallback": False,
        }
    score, detail = evaluate_candidate(selected)
    selected_row = thresholds.selected_candidate or structural.selected_candidate or {}
    cp_threshold = None
    for key, value in dict(selected_row.get("threshold_values") or {}).items():
        if str(key).endswith(".resource.combo_points"):
            cp_threshold = float(value)
            break
    threshold_rows = []
    for row in thresholds.candidates:
        vals = dict(row.get("threshold_values") or {})
        cp = next((float(v) for k, v in vals.items() if str(k).endswith(".resource.combo_points")), None)
        if cp is not None and row.get("seconds_per_mob") is not None:
            threshold_rows.append({
                "combo_point_threshold": cp,
                "seconds_per_mob": float(row["seconds_per_mob"]),
                "candidate_id": str(row.get("candidate_id") or ""),
                "action_ids": list(row.get("action_ids") or ()),
            })
    return {
        "status": "selected", "seed_policy_id": seed_policy.id,
        "selected_policy": selected.as_dict(),
        "selected_candidate_id": selected_row.get("candidate_id"),
        "selected_seconds_per_mob": score,
        "selected_combo_point_threshold": cp_threshold,
        "selected_action_ids": list(detail.get("selected_action_ids") or ()),
        "target_health": target_hp,
        "policy_search": structural.as_dict(),
        "policy_threshold_search": thresholds.as_dict(),
        "threshold_results": threshold_rows,
        "target_bound_resource_ids": [r.id for r in ir_slice.resources if str(r.scope or "actor") == "target"],
        "legacy_fallback": False,
    }


def _event_trigger_damage_probe(ir_slice, *, level: int):
    """Execute one real source-declared reactive-damage Trigger end to end.

    The target is a bounded mechanics probe.  Incoming cadence, incoming attack,
    Wrath action and Thorns damage all come from canonical IR; the only synthetic
    input is the 100-HP probe target so the timing delta is cheap and obvious.
    """
    if ir_slice is None or not ir_slice.triggers or not ir_slice.incoming_attacks or not ir_slice.mitigation_rules:
        return None
    trigger = next((t for t in ir_slice.triggers if t.metadata.get("g31_scope") == "generic_event_trigger_damage"), None)
    if trigger is None:
        return None
    attack = ir_slice.incoming_attacks[0]
    direct = next((
        a for a in ir_slice.actions
        if str(a.family_key) == "wrath" and any(isinstance(e, DamageEffect) for e in a.effects)
    ), None)
    if direct is None:
        return None

    def run(active_triggers):
        actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
        # G28 deliberately requires explicit Armor authority.  Zero Armor keeps
        # this G31 proof isolated from the known derived-Bear-Armor fidelity gap.
        actor.stats["armor"] = 0.0
        target = TargetState.with_health("g31-trigger-timing-probe", 130.0, source_status="synthetic_mechanics_probe")
        runtime = CombatRuntime(
            actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)),
            auto_attacks=(), triggers=active_triggers,
        )
        for swing_time in (0.0, 2.0, 4.0, 6.0):
            if not target.alive:
                break
            runtime.resolve_incoming_attack(attack, mitigation_rules=ir_slice.mitigation_rules, at_time_s=swing_time)
            if not target.alive:
                break
            eligibility = action_eligibility(action=direct, actor=actor, target=target)
            if not eligibility.eligible and str(eligibility.reason or "").startswith("action not ready:"):
                runtime.advance_to(eligibility.next_ready_s)
                eligibility = action_eligibility(action=direct, actor=actor, target=target)
            if not eligibility.eligible:
                break
            runtime.schedule_action(direct)
        runtime.run_until_idle()
        timeline = runtime.result()
        trigger_damage_events = [
            e for e in timeline.events
            if e.kind == "Damage" and e.payload.get("trigger_id") == str(trigger.id) and bool(e.payload.get("applied", True))
        ]
        return {
            "target_defeated": bool(timeline.target_defeated),
            "target_death_s": timeline.target_death_s,
            "total_damage": float(timeline.total_damage),
            "trigger_damage": sum(float(e.payload.get("amount", 0.0)) for e in trigger_damage_events),
            "trigger_count": len(trigger_damage_events),
            "event_kinds": [e.kind for e in timeline.events],
        }

    baseline = run(())
    active = run(ir_slice.triggers)
    if not active["target_defeated"] or not baseline["target_defeated"]:
        return {"status": "unavailable", "baseline": baseline, "active": active, "legacy_fallback": False}
    return {
        "status": "executed", "trigger_id": str(trigger.id), "trigger_name": str(trigger.name),
        "event_kind": str(trigger.event_kind), "effect": trigger.effects[0].as_dict(),
        "baseline_seconds_per_mob": float(baseline["target_death_s"]),
        "trigger_seconds_per_mob": float(active["target_death_s"]),
        "improvement_seconds_per_mob": float(baseline["target_death_s"] - active["target_death_s"]),
        "trigger_damage": float(active["trigger_damage"]), "trigger_count": int(active["trigger_count"]),
        "baseline": baseline, "active": active, "legacy_fallback": False,
    }


def _mode_action_policy_search_probe(ir_slice, *, level: int):
    """Search any source-declared mode-entry action policy generically.

    G29's Druid Bear proof is only the first producer. The orchestrator knows
    neither class nor form/action names: the source Policy declares its entry
    Action, and ordinary Mode/Resource/AutoAttack semantics execute the rest.
    """
    seed_policy = next((
        p for p in ir_slice.policies
        if str(p.provenance.get("g29_scope") or "") == "mode_action_policy_seed"
    ), None)
    if seed_policy is None:
        return None
    entry_action_id = str(seed_policy.provenance.get("entry_action_id") or "")
    action_map = {str(a.id): a for a in ir_slice.actions}
    entry_action = action_map.get(entry_action_id)
    if entry_action is None:
        return {"status": "unavailable", "error": "declared mode entry action missing", "legacy_fallback": False}

    mode_id = next((
        str(effect.target_mode_id) for effect in entry_action.effects
        if isinstance(effect, ModeChangeEffect)
    ), None)
    target_hp = float(representative_hp(level))

    def evaluate_candidate(policy):
        actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
        target = TargetState.with_health(
            f"generic_mode_action_target_L{int(level)}", target_hp,
            source_status="source_backed_canonical_leveling_reference", level=int(level),
        )
        runtime = CombatRuntime(
            actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)),
            auto_attacks=ir_slice.auto_attacks,
        )
        if entry_action is not None:
            eligibility = action_eligibility(action=entry_action, actor=actor, target=target)
            if not eligibility.eligible:
                return None, {"stop_reason": eligibility.reason, "target_defeated": False}
            runtime.schedule_action(entry_action)
            if actor.gcd_ready_s > actor.current_time_s:
                runtime.advance_to(actor.gcd_ready_s)
        execution = execute_priority_policy(
            policy=policy, actions=ir_slice.actions, runtime=runtime, max_actions=256,
        opening_action_ids=opening_action_ids,
        )
        timeline = execution.timeline
        return (
            None if not timeline.target_defeated else float(timeline.target_death_s),
            {
                "stop_reason": execution.stopped_reason,
                "target_defeated": bool(timeline.target_defeated),
                "action_count": len(execution.selected_actions),
                "selected_action_ids": [str(x["action_id"]) for x in execution.selected_actions],
                "entered_mode_id": actor.current_mode_id,
                "ending_resources": dict(actor.resources),
                "auto_attack_damage": float(timeline.auto_attack_damage),
                "total_damage": float(timeline.total_damage),
            },
        )

    structural = search_priority_policy(seed_policy, evaluate=evaluate_candidate, max_candidates=32)
    selected = structural.selected_policy
    if selected is None:
        return {
            "status": "unavailable", "seed_policy_id": seed_policy.id,
            "policy_search": structural.as_dict(), "legacy_fallback": False,
        }
    score, detail = evaluate_candidate(selected)
    selected_row = structural.selected_candidate or {}
    return {
        "status": "selected", "seed_policy_id": seed_policy.id,
        "entry_action_id": entry_action_id, "mode_id": mode_id,
        "selected_policy": selected.as_dict(),
        "selected_candidate_id": selected_row.get("candidate_id"),
        "selected_seconds_per_mob": score,
        "seed_seconds_per_mob": structural.as_dict().get("seed_seconds_per_mob"),
        "improvement_vs_seed_seconds_per_mob": structural.as_dict().get("improvement_vs_seed_seconds_per_mob"),
        "selected_action_ids": list(detail.get("selected_action_ids") or ()),
        "target_health": target_hp,
        "policy_search": structural.as_dict(),
        "legacy_fallback": False,
    }


def _cross_mode_policy_search_probe(ir_slice, *, level: int):
    """Evaluate source-declared mode policies together; transitions stay in Policy IR."""
    candidates = tuple(p for p in ir_slice.policies if any(p.provenance.get(k) for k in ("g26_scope", "g29_scope", "g30_scope")))
    if not any(p.provenance.get("g30_scope") == "cross_mode_policy_candidate" for p in candidates):
        return None
    action_map = {str(a.id): a for a in ir_slice.actions}
    rows = []
    for policy in candidates:
        actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
        target = TargetState.with_health(f"generic_cross_mode_target_L{int(level)}", float(representative_hp(level)))
        runtime = CombatRuntime(actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)), auto_attacks=ir_slice.auto_attacks)
        entry_id = str(policy.provenance.get("entry_action_id") or "")
        if entry_id:
            entry = action_map.get(entry_id)
            if entry is None:
                continue
            eligibility = action_eligibility(action=entry, actor=actor, target=target)
            if not eligibility.eligible:
                continue
            runtime.schedule_action(entry)
            if actor.gcd_ready_s > actor.current_time_s:
                runtime.advance_to(actor.gcd_ready_s)
        execution = execute_priority_policy(policy=policy, actions=ir_slice.actions, runtime=runtime, max_actions=256)
        transitions = [
            {"from_mode_id": e.payload.get("from_mode_id"), "to_mode_id": e.payload.get("to_mode_id"), "time_s": float(e.time_s)}
            for e in execution.timeline.events if e.kind == "ModeChanged"
        ]
        rows.append({
            "policy_id": policy.id, "label": policy.label,
            "candidate_kind": "cross_mode" if policy.provenance.get("g30_scope") else ("cat" if policy.provenance.get("g26_scope") else "bear"),
            "seconds_per_mob": (None if not execution.timeline.target_defeated else float(execution.timeline.target_death_s)),
            "target_defeated": bool(execution.timeline.target_defeated), "stop_reason": execution.stopped_reason,
            "mode_transitions": transitions,
            "selected_action_ids": [str(x["action_id"]) for x in execution.selected_actions],
        })
    valid = [r for r in rows if r["seconds_per_mob"] is not None]
    if not valid:
        return {"status": "unavailable", "candidates": rows, "legacy_fallback": False}
    selected = min(valid, key=lambda r: float(r["seconds_per_mob"]))
    cross = next((r for r in valid if r["candidate_kind"] == "cross_mode"), None)
    delta = None if cross is None else float(cross["seconds_per_mob"]) - float(selected["seconds_per_mob"])
    return {
        "status": "selected", "selected_policy_id": selected["policy_id"], "selected_candidate_kind": selected["candidate_kind"],
        "selected_seconds_per_mob": selected["seconds_per_mob"], "candidate_count": len(rows), "valid_candidate_count": len(valid),
        "cross_mode_policy_id": (None if cross is None else cross["policy_id"]),
        "cross_mode_seconds_per_mob": (None if cross is None else cross["seconds_per_mob"]),
        "cross_mode_delta_vs_selected_seconds_per_mob": delta,
        "cross_mode_transitions": ([] if cross is None else cross["mode_transitions"]),
        "cross_mode_action_ids": ([] if cross is None else cross["selected_action_ids"]),
        "candidates": rows, "legacy_fallback": False,
    }


def _fixed_action_combat_evaluation(ir_slice, *, level: int):
    """Evaluate one fixed source-backed direct Action against canonical target HP.

    This is deliberately not policy search: G10 proves runtime -> Evaluation using
    one mechanically supported Action. G11 owns the first real multi-action policy.
    """
    action = next((
        candidate for candidate in ir_slice.actions
        if any(isinstance(effect, DamageEffect) for effect in candidate.effects)
        and not any(isinstance(effect, PeriodicEffect) for effect in candidate.effects)
    ), None)
    if action is None:
        return None, None, None
    actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
    target_hp = float(representative_hp(level))
    target = TargetState.with_health(
        f"canonical_leveling_target_L{int(level)}", target_hp,
        source_status="source_backed_canonical_leveling_reference",
        authority="src.shared.leveling.objective.MOB_BASE_HP",
        source_basis="CMaNGOS warrior-class BaseHealthExp0 ordinary melee target curve",
        level=int(level),
    )
    runtime = CombatRuntime(actor=actor, target=target, spell_power=float(actor.stats.get("spell_power", 0.0)))
    stop_reason = None
    for _ in range(256):
        if not target.alive:
            break
        eligibility = action_eligibility(action=action, actor=actor)
        if not eligibility.eligible and eligibility.reason == "action not ready: gcd/cooldown":
            runtime.advance_to(eligibility.next_ready_s)
            eligibility = action_eligibility(action=action, actor=actor)
        if not eligibility.eligible:
            stop_reason = eligibility.reason
            break
        runtime.schedule_action(action)
    runtime.run_until_idle()
    timeline = runtime.result()
    if not timeline.target_defeated:
        return None, timeline, {"action_id": action.id, "stop_reason": stop_reason or "target_not_defeated"}
    talent_application = dict(ir_slice.provenance.get("talent_application") or {})
    evaluation = evaluation_from_combat_timeline(
        timeline,
        action_name_by_id={action.id: action.name},
        provenance={
            "producer": "generic_event_runtime",
            "game_ir_action_id": action.id,
            "action_provenance": [dict(x) for x in action.provenance],
            "target": dict(target.metadata),
            "spell_power": 0.0,
            "talent_application": talent_application,
        },
        fidelity={
            "rating": "expected_value_naked_actor_combat_slice",
            "source_backed_actor": True,
            "source_backed_target_hp": True,
            "limitations": [
                "fixed single-action seed; policy search starts G11",
                ("naked source-backed actor; gear not yet applied; explicit source-backed talent seed applied" if talent_application else "naked source-backed actor; gear/talents not yet applied"),
                "expected-value damage; hit/crit/resist/variance not yet resolved",
                "recovery and travel are not part of this combat-only Evaluation",
            ],
        },
    )
    return evaluation, timeline, {
        "action_id": action.id, "action_name": action.name,
        "selection": "first mechanically supported direct-only Action; not policy search",
        "target_health": target_hp, "target_source_status": target.metadata.get("source_status"),
    }

_JOINT_TALENT_POLICY_CACHE: dict[tuple[int, str], tuple[object, object]] = {}


def _joint_search_cache_key(source_ir_slice, *, level: int) -> tuple[int, str]:
    payload = json.dumps(
        source_ir_slice.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return int(level), hashlib.sha256(payload).hexdigest()


def clear_generic_joint_search_cache() -> None:
    _JOINT_TALENT_POLICY_CACHE.clear()


def _joint_talent_policy_bundle(source_ir_slice, *, level: int):
    """Run the supported talent + policy search stack for one source-state IR.

    This helper is the G20 scorer authority used by naked, stat-probe and geared
    states.  It contains no class/item branching; source-layer providers decide
    which gear is legal before an IR reaches this scorer.
    """
    cache_key = _joint_search_cache_key(source_ir_slice, level=level)
    cached = _JOINT_TALENT_POLICY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    candidate_bundles = {}
    talent_search_result = None

    if source_ir_slice.talents:
        def evaluate_talent_candidate(selection):
            candidate_ir, candidate_application = apply_talent_selection(
                source_ir_slice, selection, level=level,
            )
            (candidate_evaluation, candidate_execution, candidate_seed,
             candidate_structural_search, candidate_threshold_search,
             candidate_efficiency) = _searched_policy_combat_evaluation(
                candidate_ir, level=level,
            )
            selected_policy = (
                candidate_threshold_search.selected_policy
                if candidate_threshold_search is not None and candidate_threshold_search.selected_policy is not None
                else candidate_structural_search.selected_policy
                if candidate_structural_search is not None else None
            )
            cid = talent_candidate_id(selection)
            candidate_bundles[cid] = {
                "ir_slice": candidate_ir,
                "talent_application": candidate_application,
                "evaluation": candidate_evaluation,
                "execution": candidate_execution,
                "seed": candidate_seed,
                "policy_search": candidate_structural_search,
                "policy_threshold_search": candidate_threshold_search,
                "policy_search_efficiency": candidate_efficiency,
                "selected_policy": selected_policy,
            }
            return (
                None if candidate_evaluation is None else candidate_evaluation.seconds_per_mob,
                {
                    "policy_candidate_id": (
                        None if selected_policy is None
                        else selected_policy.provenance.get("candidate_id") or selected_policy.id
                    ),
                    "policy_id": (None if selected_policy is None else selected_policy.id),
                    "policy_seconds_per_mob": (
                        None if candidate_evaluation is None else candidate_evaluation.seconds_per_mob
                    ),
                    "policy_search_efficiency": dict(candidate_efficiency or {}),
                    "talent_application": candidate_application.as_dict(),
                },
            )

        talent_search_result = search_talent_allocations(
            source_ir_slice, level=level, evaluate=evaluate_talent_candidate, max_candidates=256,
        )
        selected_bundle = (
            candidate_bundles.get(talent_search_result.selected_candidate_id)
            if talent_search_result.selected_candidate_id is not None else None
        )
    else:
        evaluation, execution, seed, structural, threshold, efficiency = _searched_policy_combat_evaluation(
            source_ir_slice, level=level,
        )
        selected_policy = (
            threshold.selected_policy if threshold is not None and threshold.selected_policy is not None
            else structural.selected_policy if structural is not None else None
        )
        selected_bundle = {
            "ir_slice": source_ir_slice,
            "talent_application": None,
            "evaluation": evaluation,
            "execution": execution,
            "seed": seed,
            "policy_search": structural,
            "policy_threshold_search": threshold,
            "policy_search_efficiency": efficiency,
            "selected_policy": selected_policy,
        }
    result = (selected_bundle, talent_search_result)
    _JOINT_TALENT_POLICY_CACHE[cache_key] = result
    return result


def build_partial_generic_records(
    *,
    class_names: Iterable[str],
    selected_level: int = 20,
    ruleset: str = "forever",
) -> list[DecisionRecord]:
    """Publish explicit capability-limited records without consulting legacy.

    A record exists for each requested class identity so the product can select
    and inspect the generic backend before combat execution is implemented.  No
    objective/timing/build values are copied from the legacy backend.
    """
    level = int(selected_level)
    backend = backend_metadata()
    records: list[DecisionRecord] = []
    for class_name in class_names:
        class_key = str(class_name)
        try:
            class_display_name = get_definition(ruleset, class_key).display_name
        except ClassRegistryError:
            # G47b: source-only registered providers do not need a legacy
            # simulator facade to publish explicit generic capability records.
            class_display_name = class_key.replace("_", " ").title()
        source_ir_slice = build_game_ir_slice(class_key=class_key, level=level) if str(ruleset) == "forever" else None
        ir_slice = source_ir_slice
        talent_application = None
        talent_search_result = None
        talent_selected_bundle = None
        talent_candidate_bundles = {}
        talent_baseline_evaluation = None
        talent_selected_seed_evaluation = None
        gear_publication = {}
        stat_weights_publication = {}
        gear_selection = None
        gear_application = None
        naked_stat_sensitivity = None
        final_stat_sensitivity = None
        naked_evaluation = None
        naked_policy = None
        naked_talent_search_result = None
        naked_policy_search_result = None
        naked_policy_threshold_search_result = None
        naked_policy_search_efficiency = None
        naked_policy_execution = None
        naked_evaluation_seed = None
        mechanics_probe_game_ir = None
        if source_ir_slice is not None and source_ir_slice.talents:
            def evaluate_talent_candidate(selection):
                candidate_ir, candidate_application = apply_talent_selection(
                    source_ir_slice, selection, level=level,
                )
                (candidate_evaluation, candidate_execution, candidate_seed,
                 candidate_structural_search, candidate_threshold_search,
                 candidate_efficiency) = _searched_policy_combat_evaluation(
                    candidate_ir, level=level,
                )
                selected_policy = (
                    candidate_threshold_search.selected_policy
                    if candidate_threshold_search is not None and candidate_threshold_search.selected_policy is not None
                    else candidate_structural_search.selected_policy
                    if candidate_structural_search is not None else None
                )
                cid = talent_candidate_id(selection)
                talent_candidate_bundles[cid] = {
                    "ir_slice": candidate_ir,
                    "talent_application": candidate_application,
                    "evaluation": candidate_evaluation,
                    "execution": candidate_execution,
                    "seed": candidate_seed,
                    "policy_search": candidate_structural_search,
                    "policy_threshold_search": candidate_threshold_search,
                    "policy_search_efficiency": candidate_efficiency,
                    "selected_policy": selected_policy,
                }
                return (
                    None if candidate_evaluation is None else candidate_evaluation.seconds_per_mob,
                    {
                        "policy_candidate_id": (
                            None if selected_policy is None
                            else selected_policy.provenance.get("candidate_id") or selected_policy.id
                        ),
                        "policy_id": (None if selected_policy is None else selected_policy.id),
                        "policy_seconds_per_mob": (
                            None if candidate_evaluation is None else candidate_evaluation.seconds_per_mob
                        ),
                        "policy_search_efficiency": dict(candidate_efficiency or {}),
                        "talent_application": candidate_application.as_dict(),
                    },
                )

            talent_search_result = search_talent_allocations(
                source_ir_slice,
                level=level,
                evaluate=evaluate_talent_candidate,
                max_candidates=256,
            )
            if talent_search_result.selected_candidate_id is not None:
                talent_selected_bundle = talent_candidate_bundles.get(
                    talent_search_result.selected_candidate_id
                )
            if talent_selected_bundle is not None:
                ir_slice = talent_selected_bundle["ir_slice"]
                talent_application = talent_selected_bundle["talent_application"]
        actors = (ir_slice.actor.as_dict(),) if ir_slice is not None else ()
        resources = tuple(x.as_dict() for x in ir_slice.resources) if ir_slice is not None else ()
        actions = tuple(x.as_dict() for x in ir_slice.actions) if ir_slice is not None else ()
        runtime_result = None
        runtime_sequence = None
        periodic_runtime = None
        periodic_probe = None
        direct_heal_runtime = None
        periodic_heal_runtime = None
        healing_runtime_probe = None
        combat_evaluation: Evaluation | None = None
        evaluation_timeline = None
        evaluation_seed = None
        active_policy = None
        policy_execution = None
        policy_search_result = None
        policy_threshold_search_result = None
        policy_search_efficiency = None
        if ir_slice is not None and ir_slice.actions:
            mechanics_probe_game_ir = ir_slice
            # Single-Actor mechanics probes must not select a Summon action
            # without registering its companion/timer. The full multi-Actor
            # decision path still receives the unfiltered Game IR.
            probe_action = next((
                a for a in ir_slice.actions
                if a.owner_actor_id == ir_slice.actor.id
                and not any(isinstance(effect, SummonEffect) for effect in a.effects)
            ), None)
            actor_state = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
            probe_target = TargetState.with_health(
                "runtime_probe_target",
                RUNTIME_PROBE_TARGET_HEALTH,
                source_status="synthetic_runtime_probe",
                purpose="exercise generic event runtime before source-backed target modelling lands",
            )
            runtime_result = execute_action(
                action=probe_action or ir_slice.actions[0],
                actor=actor_state,
                target=probe_target,
                spell_power=0.0,
            )
            sequence_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
            sequence_target = TargetState.with_health(
                "runtime_state_probe_target",
                1000000.0,
                source_status="synthetic_runtime_probe",
                purpose="exercise generic repeated Action state progression without claiming target fidelity",
            )
            runtime_sequence = execute_repeated_actions(
                action=probe_action or ir_slice.actions[0],
                actor=sequence_actor,
                target=sequence_target,
                count=3,
                spell_power=0.0,
            )
            periodic_action = next((
                candidate for candidate in ir_slice.actions
                if any(isinstance(effect, PeriodicEffect) for effect in candidate.effects)
            ), None)
            if periodic_action is not None:
                periodic_effect = next(
                    effect for effect in periodic_action.effects if isinstance(effect, PeriodicEffect)
                )
                refresh_at_s = float(periodic_effect.duration_s) / 2.0
                periodic_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
                # G37: a self-contained mechanics probe is not a combat opener.
                # Explicitly seed required actor Resource costs (for example Rage)
                # rather than assuming every periodic action is castable at t=0.
                periodic_seed_costs = {}
                for cost in periodic_action.costs:
                    if str(cost.resource_id) in periodic_actor.resources:
                        before_seed = float(periodic_actor.resources[str(cost.resource_id)])
                        enough = 2.0 * float(cost.amount)
                        periodic_actor.resources[str(cost.resource_id)] = min(
                            float(periodic_actor.resource_capacity.get(str(cost.resource_id), enough)),
                            max(before_seed, enough),
                        )
                        if periodic_actor.resources[str(cost.resource_id)] != before_seed:
                            periodic_seed_costs[str(cost.resource_id)] = float(periodic_actor.resources[str(cost.resource_id)])
                periodic_target = TargetState.with_health(
                    "runtime_periodic_probe_target",
                    1000000.0,
                    source_status="synthetic_runtime_probe",
                    purpose="exercise generic Aura/PeriodicEffect apply-replace-tick-expiry semantics",
                )
                periodic_runtime = execute_action_timeline(
                    scheduled_actions=((0.0, periodic_action), (refresh_at_s, periodic_action)),
                    actor=periodic_actor, target=periodic_target, spell_power=0.0,
                )
                periodic_probe = {
                    "action_id": periodic_action.id,
                    "aura_id": periodic_effect.aura_id,
                    "refresh_at_s": refresh_at_s,
                    "refresh_schedule_status": "synthetic_mechanics_probe_not_policy",
                    "synthetic_starting_resource_seed": periodic_seed_costs,
                    "target_source_status": "synthetic_runtime_probe",
                }
            direct_heal_action = next((
                candidate for candidate in ir_slice.actions
                if any(isinstance(effect, HealEffect) for effect in candidate.effects)
            ), None)
            periodic_heal_action = next((
                candidate for candidate in ir_slice.actions
                if any(isinstance(effect, PeriodicHealEffect) for effect in candidate.effects)
            ), None)
            healing_runtime_probe = {}
            if direct_heal_action is not None:
                heal_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
                if "health" in heal_actor.resources and "health" in heal_actor.resource_capacity:
                    heal_actor.resources["health"] = 0.2 * float(heal_actor.resource_capacity["health"])
                    heal_context = TargetState.with_health("runtime_heal_probe_context", 1.0, source_status="synthetic_runtime_probe")
                    direct_heal_runtime = execute_action(
                        action=direct_heal_action, actor=heal_actor, target=heal_context, spell_power=0.0,
                    )
                    healing_runtime_probe["direct"] = {
                        "action_id": direct_heal_action.id,
                        "health_after": heal_actor.resource_amount("health"),
                        "events": [e.as_dict() for e in direct_heal_runtime.events if e.kind == "Heal"],
                    }
            if periodic_heal_action is not None:
                hot_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
                if "health" in hot_actor.resources and "health" in hot_actor.resource_capacity:
                    hot_actor.resources["health"] = 0.2 * float(hot_actor.resource_capacity["health"])
                    hot_context = TargetState.with_health("runtime_hot_probe_context", 1.0, source_status="synthetic_runtime_probe")
                    periodic_heal_runtime = execute_action(
                        action=periodic_heal_action, actor=hot_actor, target=hot_context, spell_power=0.0,
                    )
                    healing_runtime_probe["periodic"] = {
                        "action_id": periodic_heal_action.id,
                        "health_after": hot_actor.resource_amount("health"),
                        "heal_events": [e.as_dict() for e in periodic_heal_runtime.events if e.kind == "Heal"],
                        "aura_events": [e.as_dict() for e in periodic_heal_runtime.events if e.kind in {"AuraApplied", "AuraReplaced", "AuraExpired"}],
                    }
            if not healing_runtime_probe:
                healing_runtime_probe = None
            if talent_application is not None:
                talent_selected_seed_evaluation, _talent_seed_execution, _talent_seed_meta = _policy_combat_evaluation(
                    ir_slice, level=level
                )
            if talent_selected_bundle is not None:
                policy_evaluation = talent_selected_bundle["evaluation"]
                policy_execution = talent_selected_bundle["execution"]
                policy_seed = talent_selected_bundle["seed"]
                policy_search_result = talent_selected_bundle["policy_search"]
                policy_threshold_search_result = talent_selected_bundle["policy_threshold_search"]
                policy_search_efficiency = talent_selected_bundle["policy_search_efficiency"]
            else:
                policy_evaluation, policy_execution, policy_seed, policy_search_result, policy_threshold_search_result, policy_search_efficiency = _searched_policy_combat_evaluation(
                    ir_slice, level=level
                )
            if policy_evaluation is not None:
                combat_evaluation = policy_evaluation
                evaluation_timeline = policy_execution.timeline
                evaluation_seed = policy_seed
                active_policy = policy_seed.get("policy") if policy_seed else None
            else:
                combat_evaluation, evaluation_timeline, evaluation_seed = _fixed_action_combat_evaluation(
                    ir_slice, level=level
                )
            if talent_application is not None and source_ir_slice is not None:
                baseline_eval, _baseline_execution, _baseline_seed = _policy_combat_evaluation(source_ir_slice, level=level)
                if baseline_eval is None:
                    baseline_eval, _baseline_timeline, _baseline_seed = _fixed_action_combat_evaluation(source_ir_slice, level=level)
                talent_baseline_evaluation = baseline_eval

        # G21: preserve G19 naked authority, then run an explicit bounded shared
        # gear <-> stat-weights <-> talent <-> policy fixed point.  The runtime
        # remains a pure scorer; all dimension changes are visible here.
        if combat_evaluation is not None and source_ir_slice is not None:
            naked_evaluation = combat_evaluation
            naked_policy = active_policy
            naked_talent_search_result = talent_search_result
            naked_policy_search_result = policy_search_result
            naked_policy_threshold_search_result = policy_threshold_search_result
            naked_policy_search_efficiency = policy_search_efficiency
            naked_policy_execution = policy_execution
            naked_evaluation_seed = evaluation_seed

            def joint_score(candidate_source_ir):
                bundle, _search = _joint_talent_policy_bundle(candidate_source_ir, level=level)
                ev = None if bundle is None else bundle.get("evaluation")
                return None if ev is None else ev.seconds_per_mob

            try:
                def fp_evaluate(candidate_source_ir):
                    bundle, search = _joint_talent_policy_bundle(candidate_source_ir, level=level)
                    if bundle is None or bundle.get("evaluation") is None:
                        raise ValueError("joint scorer produced no evaluation")
                    selected = bundle.get("selected_policy")
                    return {
                        "seconds_per_mob": bundle["evaluation"].seconds_per_mob,
                        "talent_candidate_id": (None if search is None else search.selected_candidate_id),
                        "policy_candidate_id": (None if selected is None else selected.provenance.get("candidate_id") or selected.id),
                    }

                sensitivity_cache = {}
                def fp_weights(candidate_source_ir):
                    key = _joint_search_cache_key(candidate_source_ir, level=level)
                    if key not in sensitivity_cache:
                        sensitivity_cache[key] = measure_stat_sensitivities(
                            candidate_source_ir, stats=EXECUTABLE_CASTER_GEAR_STATS, score=joint_score,
                        )
                    return sensitivity_cache[key].as_dict().get("values", {})

                selection_by_id = {}
                def fp_select(weights):
                    selection = select_named_gear(class_key=class_key, level=level, stat_weights=weights)
                    item_ids = {str(slot): int(item.get("item_id")) for slot, item in selection.slots.items()}
                    candidate_id = "gear:" + ",".join(f"{slot}={item_ids[slot]}" for slot in sorted(item_ids))
                    payload = {**selection.as_dict(), "candidate_id": candidate_id, "item_ids": item_ids}
                    selection_by_id[candidate_id] = selection
                    return payload

                application_by_id = {}
                def fp_apply(base_ir, gear):
                    selection = selection_by_id[str(gear["candidate_id"])]
                    applied_ir, application = apply_gear_selection(
                        base_ir, aggregate_stats=selection.aggregate_stats,
                        selected_items=tuple(selection.slots.values()),
                        source="canonical_sqlite_forever_catalogue",
                    )
                    application_by_id[str(gear["candidate_id"])] = application
                    return applied_ir

                fixed_point = run_optimizer_fixed_point(
                    source_ir_slice, evaluate_state=fp_evaluate, measure_weights=fp_weights,
                    select_gear=fp_select, apply_gear=fp_apply, max_iterations=4,
                )
                selected_fp = fixed_point.selected
                if selected_fp.gear_candidate_id != "none":
                    gear_selection = selection_by_id[selected_fp.gear_candidate_id]
                    geared_source_ir, gear_application = apply_gear_selection(
                        source_ir_slice, aggregate_stats=gear_selection.aggregate_stats,
                        selected_items=tuple(gear_selection.slots.values()),
                        source="canonical_sqlite_forever_catalogue",
                    )
                    geared_bundle, geared_talent_search = _joint_talent_policy_bundle(geared_source_ir, level=level)
                    if geared_bundle is not None and geared_bundle.get("evaluation") is not None:
                        ir_slice = geared_bundle["ir_slice"]
                        talent_application = geared_bundle["talent_application"]
                        talent_search_result = geared_talent_search
                        combat_evaluation = geared_bundle["evaluation"]
                        policy_execution = geared_bundle["execution"]
                        evaluation_timeline = None if policy_execution is None else policy_execution.timeline
                        evaluation_seed = geared_bundle["seed"]
                        policy_search_result = geared_bundle["policy_search"]
                        policy_threshold_search_result = geared_bundle["policy_threshold_search"]
                        policy_search_efficiency = geared_bundle["policy_search_efficiency"]
                        selected_policy = geared_bundle.get("selected_policy")
                        active_policy = None if selected_policy is None else selected_policy.as_dict()
                        naked_stat_sensitivity = sensitivity_cache[_joint_search_cache_key(source_ir_slice, level=level)]
                        final_stat_sensitivity = sensitivity_cache.get(_joint_search_cache_key(geared_source_ir, level=level))
                        if final_stat_sensitivity is None:
                            final_stat_sensitivity = measure_stat_sensitivities(
                                geared_source_ir, stats=EXECUTABLE_CASTER_GEAR_STATS, score=joint_score,
                            )
                        gear_publication = {
                            "status": "selected_named_catalogue_gear",
                            "selection_method": "explicit_bounded_optimizer_fixed_point",
                            "fixed_point_complete": bool(fixed_point.converged),
                            "fixed_point": fixed_point.as_dict(),
                            "item_count": len(gear_selection.slots),
                            "slots": {str(k): dict(v) for k, v in gear_selection.slots.items()},
                            "aggregate_stats": {str(k): float(v) for k, v in gear_selection.aggregate_stats.items()},
                            "applied_stats": dict(gear_application.applied_stats),
                            "unsupported_stats": dict(gear_application.unsupported_stats),
                            "selection_weights": {str(k): float(v) for k, v in gear_selection.selection_weights.items()},
                            "naked_seconds_per_mob": naked_evaluation.seconds_per_mob,
                            "geared_seconds_per_mob": combat_evaluation.seconds_per_mob,
                            "delta_seconds_per_mob": combat_evaluation.seconds_per_mob - naked_evaluation.seconds_per_mob,
                            "source": "canonical_sqlite_forever_catalogue",
                        }
                        stat_weights_publication = final_stat_sensitivity.as_dict()
                        stat_weights_publication["gear_selection_basis"] = naked_stat_sensitivity.as_dict()
                        stat_weights_publication["fixed_point_state_identity"] = selected_fp.state_identity
                else:
                    gear_publication = {
                        "status": "unavailable", "selection_method": "explicit_bounded_optimizer_fixed_point",
                        "fixed_point_complete": bool(fixed_point.converged), "fixed_point": fixed_point.as_dict(),
                        "error": "bounded fixed point selected naked state",
                    }
            except (ValueError, RuntimeError, KeyError) as exc:
                gear_publication = {
                    "status": "unavailable", "selection_method": "explicit_bounded_optimizer_fixed_point",
                    "fixed_point_complete": False, "error": f"{type(exc).__name__}: {exc}",
                }

        # Publication collections must reflect the active (possibly geared) IR.
        actors = (ir_slice.actor.as_dict(),) if ir_slice is not None else ()
        resources = tuple(x.as_dict() for x in ir_slice.resources) if ir_slice is not None else ()
        actions = (
            tuple(x.as_dict() for x in ir_slice.actions) + tuple(x.as_dict() for x in ir_slice.auto_attacks)
            if ir_slice is not None else ()
        )
        modes = tuple(x.as_dict() for x in ir_slice.modes) if ir_slice is not None else ()

        mode_runtime_probe = None
        if ir_slice is not None and ir_slice.modes:
            mode_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
            enter_candidates = tuple(
                action for action in ir_slice.actions
                if any(isinstance(effect, ModeChangeEffect) and effect.target_mode_id != mode_actor.current_mode_id for effect in action.effects)
                and action_eligibility(action=action, actor=mode_actor).eligible
            )
            enter_action = next((
                action for action in enter_candidates
                if str(action.metadata.get("g23_scope") or "") == "mode_entry"
            ), None) or (enter_candidates[0] if enter_candidates else None)
            if enter_action is not None:
                initial_mode_id = mode_actor.current_mode_id
                initial_stats = dict(mode_actor.stats)
                initial_resources = dict(mode_actor.resources)
                initial_active = dict(mode_actor.resource_active)
                mode_context = TargetState.with_health(
                    "runtime_mode_probe_context", 1.0, source_status="synthetic_runtime_probe",
                    purpose="exercise generic ModeChangeEffect without class dispatch",
                )
                enter_runtime = CombatRuntime(actor=mode_actor, target=mode_context, spell_power=0.0)
                enter_runtime.schedule_action(enter_action)
                enter_runtime.run_until_idle()
                entered_mode_id = mode_actor.current_mode_id
                entered_stats = dict(mode_actor.stats)
                entered_resources = dict(mode_actor.resources)
                entered_active = dict(mode_actor.resource_active)
                mode_actor.current_time_s = max(mode_actor.current_time_s, mode_actor.gcd_ready_s)
                exit_action = next((
                    action for action in ir_slice.actions
                    if any(isinstance(effect, ModeChangeEffect) and effect.target_mode_id == initial_mode_id for effect in action.effects)
                    and action_eligibility(action=action, actor=mode_actor).eligible
                ), None)
                exit_events = []
                if exit_action is not None:
                    if action_eligibility(action=exit_action, actor=mode_actor).eligible:
                        exit_runtime = CombatRuntime(actor=mode_actor, target=mode_context, spell_power=0.0)
                        exit_runtime.schedule_action(exit_action)
                        exit_runtime.run_until_idle()
                        exit_events = [event.as_dict() for event in exit_runtime.result().events]
                mode_runtime_probe = {
                    "initial_mode_id": initial_mode_id,
                    "enter_action_id": enter_action.id,
                    "entered_mode_id": entered_mode_id,
                    "exit_action_id": None if exit_action is None else exit_action.id,
                    "final_mode_id": mode_actor.current_mode_id,
                    "initial_stats": initial_stats,
                    "entered_stats": entered_stats,
                    "final_stats": dict(mode_actor.stats),
                    "initial_resources": initial_resources,
                    "entered_resources": entered_resources,
                    "final_resources": dict(mode_actor.resources),
                    "initial_resource_active": initial_active,
                    "entered_resource_active": entered_active,
                    "final_resource_active": dict(mode_actor.resource_active),
                    "enter_events": [event.as_dict() for event in enter_runtime.result().events],
                    "exit_events": exit_events,
                    "legacy_fallback": False,
                }

        auto_attack_runtime_probe = None
        if ir_slice is not None and ir_slice.auto_attacks and ir_slice.modes:
            probe_auto_attacks = tuple(a for a in ir_slice.auto_attacks
                                       if a.owner_actor_id == ir_slice.actor.id)
            auto_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
            historical_auto_modes = {
                str(attack.required_mode_id) for attack in probe_auto_attacks
                if str(attack.metadata.get("g24_scope") or "")
            }
            auto_mode_candidates = tuple(
                action for action in ir_slice.actions
                if any(
                    isinstance(effect, ModeChangeEffect)
                    and any(attack.required_mode_id == effect.target_mode_id for attack in probe_auto_attacks)
                    for effect in action.effects
                )
                and action_eligibility(action=action, actor=auto_actor).eligible
            )
            enter_auto_mode = next((
                action for action in auto_mode_candidates
                if any(
                    isinstance(effect, ModeChangeEffect) and str(effect.target_mode_id) in historical_auto_modes
                    for effect in action.effects
                )
            ), None) or (auto_mode_candidates[0] if auto_mode_candidates else None)
            initial_auto_ready = any(
                attack.required_mode_id is None
                or str(attack.required_mode_id) == str(auto_actor.current_mode_id)
                for attack in probe_auto_attacks
            )
            if probe_auto_attacks and (enter_auto_mode is not None or initial_auto_ready):
                auto_target = TargetState.with_health(
                    "runtime_auto_attack_probe_target", RUNTIME_PROBE_TARGET_HEALTH,
                    source_status="synthetic_runtime_probe",
                    purpose="exercise generic AutoAttack swing timer and expected hit outcome",
                )
                auto_runtime = CombatRuntime(
                    actor=auto_actor, target=auto_target, spell_power=0.0,
                    auto_attacks=probe_auto_attacks,
                )
                if enter_auto_mode is not None:
                    auto_runtime.schedule_action(enter_auto_mode)
                gcd_ready_after_enter = float(auto_actor.gcd_ready_s)
                auto_runtime.run_until_idle()
                auto_result = auto_runtime.result()
                swing_events = [event for event in auto_result.events if event.kind == "AutoAttackSwing"]
                outcome_events = [event for event in auto_result.events if event.kind == "AutoAttackOutcome"]
                damage_events = [
                    event for event in auto_result.events
                    if event.kind == "Damage" and bool(event.payload.get("auto_attack")) and bool(event.payload.get("applied", True))
                ]
                first_swing_s = None if not swing_events else float(swing_events[0].time_s)
                auto_attack_runtime_probe = {
                    "enter_action_id": (None if enter_auto_mode is None else enter_auto_mode.id),
                    "active_mode_id": auto_actor.current_mode_id,
                    "initial_mode_already_auto_eligible": enter_auto_mode is None,
                    "auto_attack_ids": [attack.id for attack in ir_slice.auto_attacks],
                    "swing_count": len(swing_events),
                    "outcome_count": len(outcome_events),
                    "damage_event_count": len(damage_events),
                    "first_swing_s": first_swing_s,
                    "gcd_ready_after_enter_s": gcd_ready_after_enter,
                    "first_swing_during_gcd": bool(
                        first_swing_s is not None and first_swing_s + 1e-12 < gcd_ready_after_enter
                    ),
                    "auto_attack_damage": float(auto_result.auto_attack_damage),
                    "target_defeated": bool(auto_result.target_defeated),
                    "target_death_s": auto_result.target_death_s,
                    "first_outcome": (None if not outcome_events else dict(outcome_events[0].payload)),
                    "events": [event.as_dict() for event in auto_result.events],
                    "legacy_fallback": False,
                }

        energy_runtime_probe = None
        if ir_slice is not None and ir_slice.modes:
            energy_resource = next((
                resource for resource in ir_slice.resources
                if str(resource.id) == "energy" and float(resource.regeneration_per_s) > 0.0
            ), None)
            claw_action = next((action for action in ir_slice.actions if str(action.family_key) == "claw"), None)
            if energy_resource is not None and claw_action is not None:
                energy_actor = ActorState.from_ir(ir_slice.actor, ir_slice.resources, ir_slice.modes)
                enter_cat = next((
                    action for action in ir_slice.actions
                    if any(isinstance(effect, ModeChangeEffect) and effect.target_mode_id == "cat" for effect in action.effects)
                    and action_eligibility(action=action, actor=energy_actor).eligible
                ), None)
                if enter_cat is not None:
                    energy_target = TargetState.with_health(
                        "runtime_energy_probe_target", 10000.0, source_status="synthetic_runtime_probe",
                        purpose="exercise generic passive resource regeneration and Claw Energy gating",
                    )
                    energy_runtime = CombatRuntime(actor=energy_actor, target=energy_target, spell_power=0.0)
                    energy_runtime.schedule_action(enter_cat)
                    energy_runtime.advance_to(float(energy_actor.gcd_ready_s))
                    first_time = float(energy_actor.current_time_s)
                    first_before = float(energy_actor.resource_amount("energy") or 0.0)
                    energy_runtime.schedule_action(claw_action)
                    first_after = float(energy_actor.resource_amount("energy") or 0.0)
                    energy_runtime.advance_to(first_time + float(claw_action.gcd_s))
                    second_time = float(energy_actor.current_time_s)
                    second_before = float(energy_actor.resource_amount("energy") or 0.0)
                    energy_runtime.schedule_action(claw_action)
                    second_after = float(energy_actor.resource_amount("energy") or 0.0)
                    blocked_time = second_time + float(claw_action.gcd_s)
                    energy_runtime.advance_to(blocked_time)
                    blocked = action_eligibility(action=claw_action, actor=energy_actor)
                    blocked_energy_value = float(energy_actor.resource_amount("energy") or 0.0)
                    rate = float(energy_resource.regeneration_per_s)
                    needed = max(0.0, float(claw_action.costs[0].amount) - float(energy_actor.resource_amount("energy") or 0.0))
                    wait_more = (needed / rate) if rate > 0.0 else 0.0
                    third_time = float(energy_actor.current_time_s) + wait_more
                    energy_runtime.advance_to(third_time)
                    third_before = float(energy_actor.resource_amount("energy") or 0.0)
                    third_eligibility = action_eligibility(action=claw_action, actor=energy_actor)
                    if third_eligibility.eligible:
                        energy_runtime.schedule_action(claw_action)
                    third_after = float(energy_actor.resource_amount("energy") or 0.0)
                    energy_result = energy_runtime.result()
                    claw_damage = [
                        event for event in energy_result.events
                        if event.kind == "Damage" and str(event.action_id or "") == str(claw_action.id) and bool(event.payload.get("applied", True))
                    ]
                    energy_runtime_probe = {
                        "resource_id": "energy", "capacity": float(energy_resource.capacity or 0.0),
                        "regeneration_per_s": rate, "regeneration_model": energy_resource.metadata.get("regeneration_model"),
                        "action_id": claw_action.id, "action_cost": float(claw_action.costs[0].amount),
                        "claw_times_s": [first_time, second_time, third_time],
                        "energy_before": [first_before, second_before, third_before],
                        "energy_after": [first_after, second_after, third_after],
                        "blocked_time_s": blocked_time, "blocked_energy": blocked_energy_value,
                        "blocked_reason": blocked.reason,
                        "third_eligible_after_regen": bool(third_eligibility.eligible),
                        "claw_damage_events": len(claw_damage),
                        "first_claw_damage": (None if not claw_damage else float(claw_damage[0].payload.get("amount", 0.0))),
                        "resource_regen_event_count": len([event for event in energy_result.events if event.kind == "ResourceRegenerated"]),
                        "combo_points_target_bound_g26": True,
                        "legacy_fallback": False,
                    }

        combo_point_policy_probe = None
        if ir_slice is not None:
            combo_point_policy_probe = _builder_finisher_policy_search_probe(ir_slice, level=level)
            if combo_point_policy_probe is not None and combo_point_policy_probe.get("status") != "selected":
                combo_point_policy_probe = None

        event_resource_gain_probe = _event_resource_gain_probe(ir_slice)
        incoming_damage_probe = _incoming_damage_probe(ir_slice)
        event_trigger_damage_probe = _event_trigger_damage_probe(ir_slice, level=level)
        mode_action_policy_probe = None
        cross_mode_policy_probe = None
        if ir_slice is not None:
            mode_action_policy_probe = _mode_action_policy_search_probe(ir_slice, level=level)
            cross_mode_policy_probe = _cross_mode_policy_search_probe(ir_slice, level=level)
            if mode_action_policy_probe is not None and mode_action_policy_probe.get("status") != "selected":
                mode_action_policy_probe = None

        # G37 publishes executed policy decisions, not merely declared rule names.
        # Source adapters opt in through metadata; no class-specific simulator.
        warrior_generic_decision = None
        if (source_ir_slice is not None
                and source_ir_slice.provenance.get("g37_proof_scope")
                and evaluation_timeline is not None and combat_evaluation is not None
                and policy_execution is not None):
            seed_evaluation, seed_execution, _ = _policy_combat_evaluation(
                source_ir_slice, level=level,
            )
            trace = evaluation_timeline
            executed = [str(x["action_id"]) for x in policy_execution.selected_actions]
            seed_actions = [] if seed_execution is None else [
                str(x["action_id"]) for x in seed_execution.selected_actions
            ]
            selected_gain_events = [e for e in trace.events if e.kind == "ResourceEventGain"
                                    and e.payload.get("resource_id") == "rage"]
            warrior_generic_decision = {
                "status": "executed", "class_name": class_key, "level": level,
                "scope": source_ir_slice.provenance.get("g37_proof_scope"),
                "numeric_authority": source_ir_slice.provenance.get("numeric_scope"),
                "selected_seconds_per_mob": combat_evaluation.seconds_per_mob,
                "selected_kill_s": trace.target_death_s,
                "selected_recovery_s": (None if combat_evaluation.recovery_s_per_100 is None
                                        else combat_evaluation.recovery_s_per_100 / 100),
                "selected_policy_id": (None if not active_policy else active_policy.get("id")),
                "selected_declared_rule_action_ids": ([] if not active_policy else [
                    str(x["action_id"]) for x in active_policy.get("rules", [])]),
                "selected_executed_action_ids": executed,
                "selected_auto_attack_only": not executed and trace.auto_attack_damage > 0,
                "selected_auto_attack_damage": float(trace.auto_attack_damage),
                "selected_rage_gain_events": len(selected_gain_events),
                "selected_rage_gained": sum(float(e.payload.get("gained", 0)) for e in selected_gain_events),
                "seed_seconds_per_mob": (None if seed_evaluation is None else seed_evaluation.seconds_per_mob),
                "seed_executed_action_ids": seed_actions,
                "improvement_s": (None if seed_evaluation is None else
                                  seed_evaluation.seconds_per_mob - combat_evaluation.seconds_per_mob),
                "source_spell_ids": [2687] + [int(x.id.split(":")[-1])
                                  for x in source_ir_slice.actions if x.family_key in {"rend", "thunder_clap"}],
                "unsupported": [str(x.get("code")) for x in source_ir_slice.unsupported_semantics],
                "legacy_fallback": False,
            }

        # G38 data-driven Rogue slice uses the exact same policy/executor as
        # Cat, including target-bound CP.  Only the source provenance opts into
        # publishing this *bounded* numeric proof; no Rogue gameplay dispatch.
        rogue_generic_decision = None
        if (source_ir_slice is not None
                and source_ir_slice.provenance.get("g38_proof_scope")
                and combat_evaluation is not None and evaluation_timeline is not None
                and policy_execution is not None):
            seed_evaluation, seed_execution, _ = _policy_combat_evaluation(source_ir_slice, level=level)
            trace = evaluation_timeline
            finished = [e for e in trace.events if e.kind == "Damage"
                        and e.payload.get("resolution") == "expected_value_resource_snapshot"
                        and bool(e.payload.get("applied", True))]
            spent = [e for e in trace.events if e.kind == "ResourceChanged"
                     and e.payload.get("resource_id") == "combo_points"
                     and e.payload.get("operation") == "set"]
            threshold = None
            for rule in (active_policy or {}).get("rules", []):
                if str(rule.get("id")) == "rogue_finisher":
                    threshold = next((float(cond["value"]) for cond in rule.get("conditions", [])
                                      if cond.get("kind") == "resource_threshold"
                                      and cond.get("resource_id") == "combo_points"), None)
            rogue_generic_decision = {
                "status": "executed", "class_name": class_key, "level": level,
                "scope": source_ir_slice.provenance["g38_proof_scope"],
                "numeric_authority": source_ir_slice.provenance.get("numeric_scope"),
                "selected_seconds_per_mob": combat_evaluation.seconds_per_mob,
                "selected_kill_s": trace.target_death_s,
                "selected_recovery_s": (None if combat_evaluation.recovery_s_per_100 is None
                                        else combat_evaluation.recovery_s_per_100 / 100),
                "seed_seconds_per_mob": None if seed_evaluation is None else seed_evaluation.seconds_per_mob,
                "improvement_s": None if seed_evaluation is None else
                    seed_evaluation.seconds_per_mob - combat_evaluation.seconds_per_mob,
                "selected_combo_point_threshold": threshold,
                "selected_executed_action_ids": [str(x["action_id"]) for x in policy_execution.selected_actions],
                "seed_executed_action_ids": ([] if seed_execution is None else
                                             [str(x["action_id"]) for x in seed_execution.selected_actions]),
                "finisher_hit_count": len(finished),
                "finisher_resource_snapshots": [float(e.payload["resource_amount_snapshot"]) for e in finished],
                "finisher_damage": [float(e.payload["amount"]) for e in finished],
                "finisher_resource_consumption_events": len(spent),
                "white_auto_damage": trace.auto_attack_damage,
                "source_spell_ids": [int(a.id.split(":")[-1]) for a in source_ir_slice.actions],
                "unsupported": [str(x.get("code")) for x in source_ir_slice.unsupported_semantics],
                "legacy_fallback": False,
            }

        # Class-neutral caster/ranged-auto evidence published by source adapter opt-in.
        priest_generic_decision = None
        if (source_ir_slice is not None
                and source_ir_slice.provenance.get("g40_proof_scope")
                and evaluation_timeline is not None and combat_evaluation is not None
                and policy_execution is not None):
            trace = evaluation_timeline
            priest_generic_decision = {
                "status": "executed", "class_name": class_key, "level": level,
                "scope": source_ir_slice.provenance["g40_proof_scope"],
                "numeric_authority": source_ir_slice.provenance.get("numeric_scope"),
                "selected_seconds_per_mob": combat_evaluation.seconds_per_mob,
                "wand_damage": float(trace.auto_attack_damage),
                "wand_swing_count": sum(e.kind == "AutoAttackSwing" and
                    str(e.payload.get("auto_attack_id", "")).startswith("priest:auto:wand")
                    for e in trace.events),
                "smite_damage": sum(float(e.payload.get("amount", 0)) for e in trace.events
                    if e.kind == "Damage" and str(e.action_id or "").startswith("smite:")
                    and bool(e.payload.get("applied", True))),
                "dot_damage": float(trace.periodic_damage),
                "source_spell_ids": [int(a.id.split(":")[-1]) for a in source_ir_slice.actions],
                "executed_action_ids": [str(a["action_id"]) for a in policy_execution.selected_actions],
                "unsupported": [str(x.get("code")) for x in source_ir_slice.unsupported_semantics],
                "legacy_fallback": False,
            }

        # G45: class-neutral caster + exclusive wand proof; no legacy Mage scorer.
        mage_generic_decision = None
        if (source_ir_slice is not None
                and source_ir_slice.provenance.get("g45_proof_scope")
                and evaluation_timeline is not None and combat_evaluation is not None
                and policy_execution is not None):
            trace = evaluation_timeline
            mage_generic_decision = {
                "status": "executed", "class_name": class_key, "level": level,
                "scope": source_ir_slice.provenance["g45_proof_scope"],
                "numeric_authority": source_ir_slice.provenance.get("numeric_scope"),
                "selected_seconds_per_mob": combat_evaluation.seconds_per_mob,
                "wand_damage": float(trace.auto_attack_damage),
                "wand_swing_count": sum(e.kind == "AutoAttackSwing" and
                    str(e.action_id or "") == "mage:auto:wand" for e in trace.events),
                "control_actions": [
                    {"action_id": action.id, "control_id": effect.control_id,
                     "duration_s": float(effect.duration_s),
                     "runtime_status": "timed_state_executable",
                     "mob_movement_or_survival_benefit": "not_modelled"}
                    for action in source_ir_slice.actions
                    for effect in action.effects
                    if isinstance(effect, ControlEffect)
                ],
                "executed_control_events": sum(e.kind == "ControlApplied" for e in trace.events),
                "source_spell_ids": [int(a.id.split(":")[-1]) for a in source_ir_slice.actions],
                "executed_action_ids": [str(a["action_id"]) for a in policy_execution.selected_actions],
                "unsupported": [str(x.get("code")) for x in source_ir_slice.unsupported_semantics],
                "legacy_fallback": False,
            }

        # Generic hybrid proof: source adapter opts in; no Shaman combat dispatch.
        shaman_generic_decision = None
        if (source_ir_slice is not None
                and source_ir_slice.provenance.get("g41_proof_scope")
                and evaluation_timeline is not None and combat_evaluation is not None
                and policy_execution is not None):
            trace = evaluation_timeline
            shaman_generic_decision = {
                "status": "executed", "class_name": class_key, "level": level,
                "scope": source_ir_slice.provenance["g41_proof_scope"],
                "numeric_authority": source_ir_slice.provenance.get("numeric_scope"),
                "seconds_per_mob": combat_evaluation.seconds_per_mob,
                "white_damage": float(trace.damage_by_actor.get("player", 0.0)) - sum(float(e.payload.get("amount",0)) for e in trace.events if e.kind == "Damage" and e.actor_id == "player" and not e.payload.get("auto_attack") and e.payload.get("applied",True)),
                "searing_totem_damage": float(trace.damage_by_actor.get("shaman:searing_totem", 0.0)),
                "searing_totem_swings": sum(e.kind == "AutoAttackSwing" and e.actor_id == "shaman:searing_totem" for e in trace.events),
                "searing_totem_spawned": any(e.kind == "SummonSpawn" and e.actor_id == "shaman:searing_totem" for e in trace.events),
                "white_swings": sum(e.kind == "AutoAttackSwing" and
                    str(e.action_id or "").startswith("shaman:auto:")
                    for e in trace.events),
                "shock_damage": sum(float(e.payload.get("amount",0)) for e in trace.events
                    if e.kind == "Damage" and str(e.action_id or "").startswith("earth_shock:")
                    and bool(e.payload.get("applied",True))),
                "lightning_damage": sum(float(e.payload.get("amount",0)) for e in trace.events
                    if e.kind == "Damage" and str(e.action_id or "").startswith("lightning_bolt:")
                    and bool(e.payload.get("applied",True))),
                "rockbiter_rank": next((a.id for a in source_ir_slice.actions
                    if a.family_key == "rockbiter_imbue"), None),
                "rockbiter_ap_bonus": next((float(m.value) for mode in source_ir_slice.modes
                    if mode.id == "rockbiter" for m in mode.stat_modifiers
                    if m.target_stat == "attack_power"), None),
                "executed_action_ids": [str(a["action_id"]) for a in policy_execution.selected_actions],
                "unsupported": [str(x.get("code")) for x in source_ir_slice.unsupported_semantics],
                "legacy_fallback": False,
            }

        hunter_pet_policy_probe = (
            _hunter_pet_slice_proof(level)
            if str(ruleset) == "forever" and class_key.lower() == "hunter" and 24 <= level < 32
            else None
        )
        unsupported_list = [
            mechanic for mechanic in GENERIC_UNSUPPORTED_MECHANICS
            if (mechanic != "class_pet_policy_modifiers" or hunter_pet_policy_probe is None)
            and (mechanic != "canonical_game_ir" or ir_slice is None)
            and (mechanic != "combat_event_runtime" or runtime_result is None)
            and (mechanic != "action_effect_execution" or runtime_result is None)
            and (mechanic != "combat_evaluation" or combat_evaluation is None)
            and (mechanic != "recovery_evaluation" or combat_evaluation is None or combat_evaluation.recovery_s_per_100 is None)
            and (mechanic != "resource_state_evaluation" or runtime_sequence is None)
            and (mechanic != "gcd_cooldown_readiness" or runtime_sequence is None)
            and (mechanic != "periodic_effect_runtime" or periodic_runtime is None)
            and (mechanic != "aura_refresh_replace" or periodic_runtime is None)
            and (mechanic != "policy_execution" or active_policy is None or combat_evaluation is None)
            and (mechanic != "policy_search" or policy_search_result is None or policy_search_result.selected_policy is None or combat_evaluation is None)
            and (mechanic != "policy_threshold_search" or policy_threshold_search_result is None or policy_threshold_search_result.selected_policy is None or combat_evaluation is None)
            and (mechanic != "talent_modifier_evaluation" or talent_application is None or combat_evaluation is None)
            and (mechanic != "talent_search" or talent_search_result is None or talent_search_result.selected_candidate_id is None or combat_evaluation is None)
            and (mechanic != "gear_optimization" or not gear_publication or gear_publication.get("status") != "selected_named_catalogue_gear")
            and (mechanic != "stat_weight_evaluation" or not stat_weights_publication)
            and (mechanic != "mode_transition_runtime" or mode_runtime_probe is None)
            and (mechanic != "auto_attack_runtime" or auto_attack_runtime_probe is None)
            and (mechanic != "energy_resource_runtime" or energy_runtime_probe is None)
            and (mechanic != "target_bound_resource_runtime" or combo_point_policy_probe is None)
            and (mechanic != "builder_finisher_policy_search" or combo_point_policy_probe is None)
            and (mechanic != "event_driven_resource_gain" or event_resource_gain_probe is None)
            and (mechanic != "incoming_player_damage_runtime" or incoming_damage_probe is None)
            and (mechanic != "armor_mitigation_runtime" or incoming_damage_probe is None)
            and (mechanic != "survivability_state" or incoming_damage_probe is None)
            and (mechanic != "incoming_resource_trigger_basis" or incoming_damage_probe is None)
            and (mechanic != "mode_action_policy_search" or mode_action_policy_probe is None)
            and (mechanic != "cross_mode_policy_search" or cross_mode_policy_probe is None)
            and (mechanic != "event_trigger_runtime" or event_trigger_damage_probe is None)
            and (
                mechanic != "level_frontier_generation"
                or not (
                    talent_search_result is not None
                    and talent_search_result.selected_candidate_id is not None
                    and bool(talent_search_result.candidates)
                    and gear_publication.get("status") == "selected_named_catalogue_gear"
                )
            )
            and (
                mechanic != "exact_tuning_for_approximate_overlays"
                or (ir_slice is not None and bool(ir_slice.unsupported_semantics))
            )
        ]
        if runtime_result is not None:
            unsupported_list.append("direct_damage_variance_roll")
        if combat_evaluation is not None:
            if combat_evaluation.travel_s_per_100 is None:
                unsupported_list.append("travel_evaluation")
            unsupported_list.append("combat_attack_table_resolution")
            if incoming_damage_probe is None:
                unsupported_list.append("incoming_player_damage_runtime")
            unsupported_list.append("canonical_player_health_authority")
        if active_policy is not None and combat_evaluation is not None:
            if any(str(x.get("execution_status") or "").startswith("deferred_") for x in active_policy.get("maintenance", [])):
                unsupported_list.append("maintenance_aura_effect_execution")
            if event_trigger_damage_probe is None and any(x.get("family_key") == "thorns" for x in active_policy.get("maintenance", [])):
                unsupported_list.append("incoming_hit_trigger_runtime")
        if hunter_pet_policy_probe is not None:
            unsupported_list.extend("hunter_pet_" + gap for gap in hunter_pet_policy_probe["unsupported"])
        if warrior_generic_decision is not None:
            unsupported_list.extend("warrior_" + x for x in warrior_generic_decision["unsupported"])
        if rogue_generic_decision is not None:
            unsupported_list.extend("rogue_" + x for x in rogue_generic_decision["unsupported"])
        unsupported = tuple(dict.fromkeys(unsupported_list))
        actor_state_ready = bool(ir_slice is not None and ir_slice.actor.state_status == "source_backed_starting_state")
        actor_resource_definitions = (
            tuple(x for x in ir_slice.resources if getattr(x, "scope", "actor") != "target")
            if ir_slice is not None
            else ()
        )
        resource_state_ready = bool(
            ir_slice is not None
            and actor_resource_definitions
            and all(
                x.state_status in {
                    "source_backed_starting_state",
                    "qualified_proxy_starting_state",
                    "mode_managed_resource_definition",
                    "event_driven_resource_definition",
                }
                and x.capacity is not None
                for x in actor_resource_definitions
            )
        )
        capability_status = (
            "combat_recovery_evaluation" if active_policy is not None and combat_evaluation is not None and combat_evaluation.recovery_s_per_100 is not None
            else "multi_action_policy_evaluation" if active_policy is not None and combat_evaluation is not None
            else "combat_evaluation" if combat_evaluation is not None
            else "periodic_event_runtime_probe" if periodic_runtime is not None
            else "stateful_event_runtime_probe" if runtime_sequence is not None
            else "event_runtime_probe" if runtime_result is not None
            else "game_ir_starting_state" if actor_state_ready and resource_state_ready
            else "game_ir_partial" if ir_slice is not None
            else "capability_limited"
        )
        objective = {
            "status": ("combat_recovery_evaluation" if combat_evaluation is not None and combat_evaluation.recovery_s_per_100 is not None else "combat_evaluation" if combat_evaluation is not None else "runtime_probe" if runtime_result is not None else "unsupported"),
            "score_s_per_100": None,
            "mobs_per_hour": None,
            "evaluation_scope": None,
            "optimization_ready": False,
        }
        timing = {
            "status": ("combat_recovery_partial" if combat_evaluation is not None and combat_evaluation.recovery_s_per_100 is not None else "combat_evaluation_partial" if combat_evaluation is not None else "runtime_probe" if runtime_result is not None else "unsupported"),
            "contract": None,
            "seconds_per_mob": None,
            "kill_seconds_per_mob": None,
            "recovery_seconds_per_mob": None,
            "travel_seconds_per_mob": None,
            "complete": False,
            "consistent": False,
            "event_consistent": False,
        }
        if runtime_result is not None:
            objective.update({
                "single_action_damage": float(runtime_result.total_damage),
                "probe_target_start_health": float(runtime_result.target_start_health),
                "probe_target_end_health": float(runtime_result.target_end_health),
                "probe_target_defeated": bool(runtime_result.target_defeated),
            })
            timing.update({
                "action_elapsed_s": float(runtime_result.elapsed_s),
                "target_death_s": runtime_result.target_death_s,
            })
        if combat_evaluation is not None:
            published = combat_evaluation.published_fields()
            objective.update({
                "score_s_per_100": published["score_s_per_100"],
                "mobs_per_hour": published["mobs_per_hour"],
                "evaluation_scope": published["evaluation_scope"],
                "optimization_ready": published["optimization_ready"],
                "target_start_health": combat_evaluation.diagnostics.get("target_start_health"),
                "target_end_health": combat_evaluation.diagnostics.get("target_end_health"),
                "action_count": combat_evaluation.diagnostics.get("action_count"),
                "damage": dict(combat_evaluation.diagnostics.get("damage") or {}),
            })
            event_consistent = bool((combat_evaluation.diagnostics.get("timing_consistency") or {}).get("consistent"))
            timing.update({
                "contract": published["timing_contract"],
                "seconds_per_mob": published["seconds_per_mob"],
                "kill_seconds_per_mob": published["kill_seconds_per_mob"],
                "recovery_seconds_per_mob": published["recovery_seconds_per_mob"],
                "travel_seconds_per_mob": published["travel_seconds_per_mob"],
                "complete": published["timing_complete"],
                "consistent": published["timing_consistent"],
                "event_consistent": event_consistent,
                "target_death_s": combat_evaluation.diagnostics.get("target_death_s"),
            })
        talent_publication = {}
        if ir_slice is not None and ir_slice.talents:
            baseline_seconds = (talent_baseline_evaluation.seconds_per_mob if talent_baseline_evaluation is not None else None)
            selected_seconds = (talent_selected_seed_evaluation.seconds_per_mob if talent_selected_seed_evaluation is not None else (combat_evaluation.seconds_per_mob if combat_evaluation is not None else None))
            talent_search_payload = talent_search_result.as_dict() if talent_search_result is not None else None
            no_talent_joint = next((
                candidate for candidate in (talent_search_result.candidates if talent_search_result is not None else ())
                if candidate.candidate_id == "talents:none"
            ), None)
            talent_publication = {
                "status": "joint_talent_policy_search" if talent_search_result is not None and talent_search_result.selected_candidate_id is not None else "definitions_only",
                "ranks": (dict(talent_application.selection) if talent_application is not None else {}),
                "available_points": (talent_application.available_points if talent_application is not None else max(0, level - 9)),
                "spent_points": (talent_application.spent_points if talent_application is not None else 0),
                "definitions": [talent.as_dict() for talent in ir_slice.talents],
                "applied_modifiers": ([dict(x) for x in talent_application.applied_modifiers] if talent_application is not None else []),
                "evaluation_comparison": {
                    "baseline_seconds_per_mob": baseline_seconds,
                    "selected_seconds_per_mob": selected_seconds,
                    "delta_seconds_per_mob": (None if baseline_seconds is None or selected_seconds is None else selected_seconds - baseline_seconds),
                    "baseline_score_s_per_100": (talent_baseline_evaluation.score_s_per_100 if talent_baseline_evaluation is not None else None),
                    "selected_score_s_per_100": (talent_selected_seed_evaluation.score_s_per_100 if talent_selected_seed_evaluation is not None else (combat_evaluation.score_s_per_100 if combat_evaluation is not None else None)),
                    "comparison_scope": "fixed canonical seed policy to isolate talent effect",
                    "active_searched_seconds_per_mob": (combat_evaluation.seconds_per_mob if combat_evaluation is not None else None),
                },
                "joint_search_comparison": {
                    "no_talents_searched_seconds_per_mob": (None if no_talent_joint is None else no_talent_joint.seconds_per_mob),
                    "selected_talents_and_policy_seconds_per_mob": (None if combat_evaluation is None else combat_evaluation.seconds_per_mob),
                    "delta_seconds_per_mob": (
                        None if no_talent_joint is None or no_talent_joint.seconds_per_mob is None or combat_evaluation is None
                        else combat_evaluation.seconds_per_mob - float(no_talent_joint.seconds_per_mob)
                    ),
                },
                "search": talent_search_payload,
                "search_performed": bool(talent_search_result is not None and talent_search_result.selected_candidate_id is not None),
            }

        records.append(DecisionRecord(
            record_id=f"{ruleset}:{class_key}:generic:{level}:{'game-ir' if ir_slice is not None else 'capability'}",
            backend=backend,
            identity={
                "ruleset": str(ruleset),
                "class_name": class_key,
                "race": None,
                "level": level,
                "target_level": level,
                "route": ("generic_game_ir" if ir_slice is not None else "generic_partial"),
                "decision_mode": ("game_ir_partial" if ir_slice is not None else "capability_only"),
                "profile": None,
            },
            objective=objective,
            timing=timing,
            gear=gear_publication,
            stat_weights=stat_weights_publication,
            talents=talent_publication,
            actors=actors,
            resources=resources,
            actions=actions,
            policy=(active_policy or {
                "kind": "priority_policy",
                "priority": [],
                "structure_status": "unsupported_until_multi_action_seed",
            }),
            modes=modes,
            capability={
                "status": capability_status,
                "decision_publication": True,
                "combat_evaluation": combat_evaluation is not None,
                "recovery_evaluation": bool(combat_evaluation is not None and combat_evaluation.recovery_s_per_100 is not None),
                "direct_heal_runtime": direct_heal_runtime is not None,
                "periodic_heal_runtime": periodic_heal_runtime is not None,
                "optimization_ready": bool(combat_evaluation is not None and combat_evaluation.optimization_ready),
                "single_action_runtime": runtime_result is not None,
                "action_effect_execution": runtime_result is not None,
                "resource_state_evaluation": runtime_sequence is not None,
                "gcd_cooldown_readiness": runtime_sequence is not None,
                "repeated_action_state_progression": runtime_sequence is not None,
                "periodic_effect_runtime": periodic_runtime is not None,
                "aura_refresh_replace": periodic_runtime is not None,
                "game_ir": ir_slice is not None,
                "game_ir_action_count": len(actions),
                "mode_ir": bool(ir_slice is not None and ir_slice.modes),
                "mode_transition_runtime": mode_runtime_probe is not None,
                "mode_ids": ([] if ir_slice is None else [mode.id for mode in ir_slice.modes]),
                "actor_starting_state": actor_state_ready,
                "resource_starting_state": resource_state_ready,
                "tuning_overlays": bool(ir_slice is not None and ir_slice.overlays),
                "field_provenance": bool(ir_slice is not None and ir_slice.actions),
                "unsupported_semantic_count": len(ir_slice.unsupported_semantics) if ir_slice is not None else 0,
                "event_runtime": runtime_result is not None,
                "policy_ir": bool(ir_slice is not None and ir_slice.policies),
                "policy_execution": active_policy is not None and combat_evaluation is not None,
                "multi_action_policy": bool(active_policy and len({x.get("action_id") for x in (policy_execution.selected_actions if policy_execution else ())}) > 1),
                "maintenance_policy": bool(active_policy and active_policy.get("maintenance")),
                "maintenance_execution": False,
                "policy_search": bool(policy_search_result is not None and policy_search_result.selected_policy is not None and combat_evaluation is not None),
                "policy_search_dimensions": (list(policy_threshold_search_result.search_dimensions) if policy_threshold_search_result is not None and policy_threshold_search_result.selected_policy is not None else ["action_inclusion_exclusion", "priority_order"] if policy_search_result is not None and policy_search_result.selected_policy is not None else []),
                "policy_threshold_search": bool(policy_threshold_search_result is not None and policy_threshold_search_result.selected_policy is not None and combat_evaluation is not None),
                "policy_search_pruning": bool(policy_search_efficiency is not None and int(policy_search_efficiency.get("dominance_pruned_requests", 0)) > 0),
                "policy_search_cache": bool(policy_search_efficiency is not None and int(policy_search_efficiency.get("cache_hits", 0)) > 0),
                "talent_modifier_evaluation": talent_application is not None and combat_evaluation is not None,
                "talent_search": bool(talent_search_result is not None and talent_search_result.selected_candidate_id is not None and combat_evaluation is not None),
                "talent_search_scope": ("executable_talent_ir" if talent_search_result is not None else None),
                "talent_search_executable_families": (list(talent_search_result.executable_talent_ids) if talent_search_result is not None else []),
                "gear_optimization": bool(gear_publication.get("status") == "selected_named_catalogue_gear"),
                "gear_optimization_scope": ("explicit_bounded_optimizer_fixed_point" if gear_publication.get("status") == "selected_named_catalogue_gear" else None),
                "stat_weight_evaluation": bool(stat_weights_publication),
                "optimizer_fixed_point": bool(gear_publication.get("fixed_point_complete") is True),
                "optimizer_fixed_point_dimensions": (list((gear_publication.get("fixed_point") or {}).get("dimensions", [])) if gear_publication else []),
                "level_frontier_generation": bool(
                    talent_search_result is not None
                    and talent_search_result.selected_candidate_id is not None
                    and bool(talent_search_result.candidates)
                    and gear_publication.get("status") == "selected_named_catalogue_gear"
                ),
                "level_frontier_scope": (
                    "bounded_native_generic_candidate_result"
                    if talent_search_result is not None
                    and talent_search_result.selected_candidate_id is not None
                    and bool(talent_search_result.candidates)
                    and gear_publication.get("status") == "selected_named_catalogue_gear"
                    else None
                ),
                "auto_attack_ir": bool(ir_slice is not None and ir_slice.auto_attacks),
                "auto_attack_runtime": auto_attack_runtime_probe is not None,
                "auto_attack_scope": (
                    "generic_repeated_swing_timer_expected_outcome"
                    if auto_attack_runtime_probe is not None else None
                ),
                "energy_resource_runtime": energy_runtime_probe is not None,
                "energy_resource_scope": (
                    "generic_active_resource_continuous_regen_and_action_cost_gating"
                    if energy_runtime_probe is not None else None
                ),
                "target_bound_resource_runtime": combo_point_policy_probe is not None,
                "target_bound_resource_scope": (
                    "generic_per_target_resource_lifecycle" if combo_point_policy_probe is not None else None
                ),
                "builder_finisher_policy_search": combo_point_policy_probe is not None,
                "builder_finisher_policy_search_scope": (
                    "generic_target_resource_threshold_search" if combo_point_policy_probe is not None else None
                ),
                "event_driven_resource_gain": event_resource_gain_probe is not None,
                "event_driven_resource_gain_scope": (
                    "generic_resource_event_rule_gain_cap_and_spend" if event_resource_gain_probe is not None else None
                ),
                "incoming_player_damage_runtime": incoming_damage_probe is not None,
                "incoming_player_damage_scope": (
                    "generic_expected_incoming_attack_mitigation_health_loss" if incoming_damage_probe is not None else None
                ),
                "armor_mitigation_runtime": incoming_damage_probe is not None,
                "survivability_state": incoming_damage_probe is not None,
                "incoming_resource_trigger_basis": incoming_damage_probe is not None,
                "incoming_resource_trigger_basis_scope": (
                    "generic_projection_from_resolved_incoming_attack_fields" if incoming_damage_probe is not None else None
                ),
                "mode_action_policy_search": mode_action_policy_probe is not None,
                "mode_action_policy_search_scope": (
                    "generic_mode_entry_resource_generation_and_action_priority_search"
                    if mode_action_policy_probe is not None else None
                ),
                "cross_mode_policy_search": cross_mode_policy_probe is not None,
                "cross_mode_policy_search_scope": ("generic_policy_ir_mode_transition_candidate_selection" if cross_mode_policy_probe is not None else None),
                "event_trigger_runtime": event_trigger_damage_probe is not None,
                "event_trigger_runtime_scope": ("generic_runtime_event_to_damage_effect" if event_trigger_damage_probe is not None else None),
                "timed_summon_lifecycle": True,
                "timed_summon_scope": "source_duration_synthetic_damage_not_class_route",
                "actor_damage_attribution": True,
                "multi_actor_event_queue": True,
                "multi_actor_scope": "synthetic_two_actor_mechanics_probe_not_class_pet_fidelity",
                "shaman_native_generic_decision": shaman_generic_decision is not None,
                "mage_native_generic_decision": mage_generic_decision is not None,
                "priest_native_generic_decision": priest_generic_decision is not None,
                "priest_native_generic_scope": (None if priest_generic_decision is None else priest_generic_decision["scope"]),
                "rogue_native_generic_decision": rogue_generic_decision is not None,
                "rogue_native_generic_scope": (None if rogue_generic_decision is None else rogue_generic_decision["scope"]),
                "warrior_native_generic_decision": warrior_generic_decision is not None,
                "warrior_native_generic_scope": (
                    None if warrior_generic_decision is None else warrior_generic_decision["scope"]),
                "class_pet_policy_modifiers": hunter_pet_policy_probe is not None,
                "class_pet_policy_scope": (
                    "source_rank_hunter_cat_L24_L31_generic_actor_links_and_bounded_policy"
                    if hunter_pet_policy_probe is not None else None
                ),
                "build_search": False,
                "route_solving": False,
            },
            fidelity={
                "rating": capability_status,
                "note": (
                    "Canonical combat + post-combat recovery Evaluation is produced from the same generic ActorState; executable Talent IR allocations and policy are searched jointly. Talent search scope is explicitly limited to families with normalized executable modifiers. Named gear, exact-scorer stat sensitivities, executable talents and policy now run through an explicit bounded fixed-point loop; travel and full attack-table fidelity remain explicit gaps; generic incoming physical mitigation/survivability and projected Rage basis are executable."
                    if combat_evaluation is not None else
                    "Source-backed Game IR executes direct and periodic effects through the persistent generic event runtime, including Aura replace refresh, ticks and expiry; target fidelity and policy search remain unsupported."
                    if periodic_runtime is not None else
                    "Source-backed Game IR executes through the generic event runtime with Mana spending, action eligibility and GCD/cooldown readiness; target fidelity and policy search remain unsupported."
                    if runtime_sequence is not None else
                    "Source-backed Game IR executes through the generic event runtime as a single-action probe; full target modelling and policy search remain unsupported."
                    if runtime_result is not None else
                    "Source-backed Game IR and actor/resource starting state are published; no executable Action is available for this record."
                    if actor_state_ready and resource_state_ready else
                    "Source-backed Game IR is published; actor/resource starting state is not yet complete and combat execution remains unsupported."
                    if ir_slice is not None else
                    "Generic backend publishes independently; this class has no source-backed Game IR slice yet."
                ),
            },
            provenance={
                "source": "generic_backend_native",
                "producer": GENERIC_IMPLEMENTATION,
                "class_display_name": class_display_name,
                "legacy_fallback": False,
                "game_ir": (ir_slice.as_dict() if ir_slice is not None else None),
                "source_game_ir": (source_ir_slice.as_dict() if source_ir_slice is not None else None),
                "mechanics_probe_game_ir": (mechanics_probe_game_ir.as_dict() if mechanics_probe_game_ir is not None else None),
                "naked_evaluation": (naked_evaluation.as_dict() if naked_evaluation is not None else None),
                "naked_policy": naked_policy,
                "naked_talent_search": (naked_talent_search_result.as_dict() if naked_talent_search_result is not None else None),
                "naked_policy_search": (naked_policy_search_result.as_dict() if naked_policy_search_result is not None else None),
                "naked_policy_threshold_search": (naked_policy_threshold_search_result.as_dict() if naked_policy_threshold_search_result is not None else None),
                "naked_policy_search_efficiency": naked_policy_search_efficiency,
                "naked_policy_execution": (naked_policy_execution.as_dict() if naked_policy_execution is not None else None),
                "naked_evaluation_seed": naked_evaluation_seed,
                "gear_selection": (gear_selection.as_dict() if gear_selection is not None else None),
                "gear_application": (gear_application.as_dict() if gear_application is not None else None),
                "naked_stat_sensitivity": (naked_stat_sensitivity.as_dict() if naked_stat_sensitivity is not None else None),
                "stat_sensitivity": (final_stat_sensitivity.as_dict() if final_stat_sensitivity is not None else None),
                "optimizer_fixed_point": gear_publication.get("fixed_point"),
                "semantic_overlays": ([dict(x) for x in ir_slice.overlays] if ir_slice is not None else []),
                "unsupported_semantics": ([dict(x) for x in ir_slice.unsupported_semantics] if ir_slice is not None else []),
                "talent_application": (talent_application.as_dict() if talent_application is not None else None),
                "talent_search": (talent_search_result.as_dict() if talent_search_result is not None else None),
                "talent_baseline_evaluation": (talent_baseline_evaluation.as_dict() if talent_baseline_evaluation is not None else None),
                "runtime_execution": (runtime_result.as_dict() if runtime_result is not None else None),
                "runtime_sequence": (runtime_sequence.as_dict() if runtime_sequence is not None else None),
                "mode_runtime_probe": mode_runtime_probe,
                "auto_attack_runtime_probe": auto_attack_runtime_probe,
                "energy_runtime_probe": energy_runtime_probe,
                "combo_point_policy_probe": combo_point_policy_probe,
                "event_resource_gain_probe": event_resource_gain_probe,
                "incoming_damage_probe": incoming_damage_probe,
                "mode_action_policy_probe": mode_action_policy_probe,
                "cross_mode_policy_probe": cross_mode_policy_probe,
                "event_trigger_damage_probe": event_trigger_damage_probe,
                "multi_actor_runtime_probe": _multi_actor_engine_proof(),
                "timed_summon_runtime_probe": _timed_summon_engine_proof(),
                "hunter_pet_policy_probe": hunter_pet_policy_probe,
                "shaman_generic_decision": shaman_generic_decision,
                "mage_generic_decision": mage_generic_decision,
                "priest_generic_decision": priest_generic_decision,
                "rogue_generic_decision": rogue_generic_decision,
                "warrior_generic_decision": warrior_generic_decision,
                "periodic_runtime": (periodic_runtime.as_dict() if periodic_runtime is not None else None),
                "periodic_runtime_probe": periodic_probe,
                "healing_runtime_probe": healing_runtime_probe,
                "evaluation": (combat_evaluation.as_dict() if combat_evaluation is not None else None),
                "evaluation_timeline": (evaluation_timeline.as_dict() if evaluation_timeline is not None else None),
                "evaluation_seed": evaluation_seed,
                "policy_execution": (policy_execution.as_dict() if policy_execution is not None else None),
                "policy_search": (policy_search_result.as_dict() if policy_search_result is not None else None),
                "policy_threshold_search": (policy_threshold_search_result.as_dict() if policy_threshold_search_result is not None else None),
                "policy_search_efficiency": policy_search_efficiency,
                "runtime_probe": ({
                    "target_source_status": "synthetic_runtime_probe",
                    "target_health": RUNTIME_PROBE_TARGET_HEALTH,
                    "resource_costs_applied": True,
                    "action_eligibility": True,
                    "gcd_cooldown_readiness": True,
                    "damage_resolution": "expected_value",
                } if runtime_result is not None else None),
            },
            unsupported_mechanics=unsupported,
            compatibility={},
        ))
    return records

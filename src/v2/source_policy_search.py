"""Bounded source-button → executable Policy IR → combat+recovery search.

No class, level, action-name or canonical-policy membership branches. Default
is offensive *single-target naked-actor* search; optional sourced auto/resource
fallback extends this without implementing mode transitions or leveling routes.
Candidate generation is exhaustive only within its declared, fail-closed scope.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import permutations, product
from typing import Mapping
from math import isfinite

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import (
    PolicyCondition, PolicyDefinition, PolicyRuleDefinition, DamageEffect,
    ResourceChangeEffect, PeriodicResourceEffect, ResourceScaledPeriodicEffect, ResourceScaledDirectDamageEffect, TargetStatDebuffEffect, TargetSchoolPowerEffect, StatusAuraEffect, EventEmitEffect, ControlEffect,
)
from src.game.runtime.effect_capabilities import effect_role
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.source_action_coverage import audit_source_action_coverage
from src.game.runtime.state import ActorState
from src.game.runtime.simulator import expected_auto_attack_swing

def _direct(effect):
    return effect_role(effect) == 'direct_damage'


def _periodic_damage(effect):
    return effect_role(effect) == 'periodic_damage'


def _damage(effect):
    return effect_role(effect) in ('direct_damage', 'periodic_damage')



def _safe_action(action, *, allow_resource_actions: bool = False) -> tuple[bool, str | None]:
    # Search envelope restricts *roles*, never independent effect class lists.
    # Unsupported engine types are rejected separately, not silently scored.
    roles = [effect_role(effect) for effect in action.effects]
    if any(role is None for role in roles):
        return False, 'unexecutable_effect'
    allowed_roles = {'direct_damage', 'periodic_damage', 'control', 'target_debuff', 'combat_enabler'}
    if allow_resource_actions:
        allowed_roles.add('resource')
    if any(role not in allowed_roles for role in roles):
        return False, 'effect_outside_single_target_offensive_scope' 
    if any(getattr(e, 'target', 'enemy') != 'enemy'
           for e in action.effects if _direct(e)):
        return False, 'non_enemy_direct_damage'
    periodic = [e for e in action.effects if _periodic_damage(e)]
    if len(periodic) > 1:
        return False, 'multiple_periodic_auras_not_supported'
    if any(e.target != 'enemy' or not e.aura_id or e.refresh_rule != 'replace'
           or e.duration_s <= 0 for e in periodic):
        return False, 'unsupported_periodic_condition'
    damage = any(_damage(e) for e in action.effects)
    debuff = any(isinstance(e, TargetStatDebuffEffect) for e in action.effects)
    # Enemy control can reduce *actual sourced incoming swings*, even with
    # zero direct damage. Root alone is not defensive against melee: do not
    # pretend the modeled single-target combat includes rooted pathing.
    stun = any(isinstance(e,ControlEffect) and e.control_id=='stun'
               and e.target=='enemy' and e.duration_s>0 for e in action.effects)
    resource_only = allow_resource_actions and not damage and not debuff and not stun and not any(isinstance(e,(StatusAuraEffect,EventEmitEffect)) for e in action.effects)
    if resource_only:
        if action.cooldown_s <= 0:
            return False, 'unbounded_resource_only_action'
        if not any((isinstance(e, ResourceChangeEffect) and e.operation == 'add'
                    and e.target in ('actor', 'self') and e.amount > 0) or
                   (isinstance(e, PeriodicResourceEffect) and e.operation == 'add'
                    and e.target in ('actor', 'self') and e.amount_per_tick > 0
                    and e.duration_s > 0 and e.tick_interval_s > 0 and e.aura_id)
                   for e in action.effects):
            return False, 'no_positive_resource_generation'
    elif not damage and not debuff and not stun and not any(isinstance(e,(StatusAuraEffect,EventEmitEffect)) for e in action.effects):
        return False, 'no_executable_damage_or_modeled_incoming_control'
    if stun and not damage and action.cooldown_s<=0:
        return False, 'unbounded_control_only_action'
    if action.cast_time_s < 0 or action.gcd_s < 0 or action.cooldown_s < 0:
        return False, 'invalid_action_timing'
    return True, None


def _rule_options(action, resources=None) -> tuple[tuple[PolicyCondition, ...], ...]:
    """Source-derived generator guards prevent overflowing a finite resource."""
    gains = [e for e in action.effects if isinstance(e, ResourceChangeEffect)
             and e.target in ("actor", "self") and e.operation == "add" and e.amount > 0]
    if gains and not any(_damage(e) for e in action.effects):
        by_id = {r.id: r for r in (resources or ())}
        if len(gains) != 1 or gains[0].resource_id not in by_id:
            return ((),)
        resource = by_id[gains[0].resource_id]
        if resource.capacity is not None and isfinite(resource.capacity) and resource.capacity > 0:
            # Both policies are valid search candidates. Threshold comes from IR, not a class spell name.
            return ((PolicyCondition(kind="resource_threshold", resource_id=resource.id,
                                    operator="lte", value=float(resource.capacity) / 2),), ())
    
    status = next((e for e in action.effects if isinstance(e,StatusAuraEffect)),None)
    if status is not None:
        return ((PolicyCondition(kind='aura_missing',scope='actor' if status.target in ('actor','self') else 'target',aura_id=status.aura_id),),)
    any_requirement=next((r for r in action.requirements if r.get('kind')=='aura_any_present'),None)
    if any_requirement is not None:
        return ((PolicyCondition(kind='aura_any_present',scope=any_requirement.get('scope','actor'),
                                 value=list(any_requirement['aura_ids'])),),)
    aura_requirement=next((r for r in action.requirements if r.get('kind')=='aura_present'),None)
    if aura_requirement is not None:
        return ((PolicyCondition(kind='aura_present',scope=aura_requirement.get('scope','actor'),aura_id=aura_requirement['aura_id']),),)
    stun = next((e for e in action.effects if isinstance(e,ControlEffect)
                 and e.control_id=='stun' and e.target=='enemy' and e.duration_s>0),None)
    if stun is not None:
        return ((PolicyCondition(kind='target_control_missing',value=stun.control_id),),)
    debuff = next((e for e in action.effects if isinstance(e, TargetStatDebuffEffect)), None)
    if debuff is not None:
        return ((PolicyCondition(kind='aura_missing', scope='target', aura_id=debuff.aura_id),),)
    # Finisher thresholds are derived from the executable source IR damage
    # ladder. A resource-scaled direct hit must not be treated as an unguarded
    # filler or require a class-/spell-name special case.
    scaled_direct = next((e for e in action.effects
                          if isinstance(e, ResourceScaledDirectDamageEffect)), None)
    if scaled_direct is not None:
        amounts = sorted(set(int(k) for k in scaled_direct.base_min_by_resource_amount) &
                         set(int(k) for k in scaled_direct.base_max_by_resource_amount))
        if not amounts or amounts[0] < 1:
            return ()
        return tuple((PolicyCondition(kind='resource_threshold',
                                      resource_id=scaled_direct.resource_id,
                                      operator='gte', value=float(amount)),)
                     for amount in amounts)
    periodic = next((e for e in action.effects if _periodic_damage(e)), None)
    if periodic is None:
        return ((),)
    guarded = (PolicyCondition(kind='aura_missing', scope='target', aura_id=periodic.aura_id),)
    # A pure DoT cannot be blindly spammed; a direct+DoT spell can also be
    # legitimately spammed for its direct component, so search both policies.
    if isinstance(periodic, ResourceScaledPeriodicEffect):
        amounts = sorted(int(k) for k in periodic.total_base_damage_by_resource_amount if int(k) > 0)
        if not amounts:
            return ()
        # Resource thresholds derive exclusively from the source-backed damage ladder.
        return tuple((PolicyCondition(kind='resource_threshold', resource_id=periodic.resource_id,
                                      operator='gte', value=float(amount)),) + guarded
                     for amount in amounts)
    return (guarded, ()) if any(_direct(e) for e in action.effects) else (guarded,)


def synthesize_source_policies(ir, *, level: int, max_policies: int = 96,
                               include_auto_resource_fallback: bool = False,
                               mode_id: str | None = None,
                               attacker_relative_position: str | None = None,
                               budget_mode: str = "strict") -> dict:
    """Enumerate sourced priorities with a direct or opt-in auto fallback.

    Without opt-in, only repeatable direct damage may fill indefinitely.
    With opt-in, eligible sourced actor auto-attacks provide an empty-policy
    baseline and a safe fallback for resource-gated actions. This does not
    synthesize mode entry/exit or resource thresholds. Cap overflow fails closed.
    """
    if max_policies < 1:
        raise ValueError('source policy envelope exceeds explicit bound')
    if budget_mode not in ("strict", "balanced_frontier"):
        raise ValueError("unknown policy budget mode")
    discovery = discover_source_combat_buttons(
        ir, level=level, include_resource_actions=include_auto_resource_fallback,
        mode_id=mode_id, attacker_relative_position=attacker_relative_position)
    actions = {a.id: a for a in ir.actions}
    supported, excluded = [], list(discovery['excluded'])
    semantic_warnings = []
    for action_id in discovery['action_ids']:
        action = actions[action_id]
        ok, reason = _safe_action(action, allow_resource_actions=include_auto_resource_fallback)
        if ok:
            supported.append(action)
            for index, effect in enumerate(action.effects):
                for warning in getattr(effect, 'unsupported_semantics', ()):
                    semantic_warnings.append({'action_id': action.id, 'effect_index': index,
                                              'warning': dict(warning)})
        else:
            excluded.append({'id': action_id, 'reason': reason})
    # The chosen fallback must itself be able to do damage repeatedly. A
    # periodic-only action cannot be a safe terminating fallback.
    fillers = [a for a in supported if a.cooldown_s == 0 and
               any(_direct(e) for e in a.effects) and
               (a.cast_time_s > 0 or a.gcd_s > 0)]
    auto_ids = []
    if include_auto_resource_fallback:
        actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
        if mode_id is not None and actor.current_mode_id != mode_id:
            actor.transition_mode(mode_id)  # search-only mode; real evaluation pays entry cost
        for auto in ir.auto_attacks:
            if (auto.owner_actor_id == ir.actor.id and auto.provenance
                    and (auto.required_mode_id is None or auto.required_mode_id == actor.current_mode_id)
                    and isfinite(auto.swing_time_s) and auto.swing_time_s > 0
                    and expected_auto_attack_swing(auto, actor=actor)['expected_damage'] > 0):
                auto_ids.append(auto.id)
    if not fillers and not auto_ids:
        raise ValueError('no safe sourced direct-damage fallback or eligible auto attack')
    policies = []
    # Keep the original strict exhaustive enumeration for APIs that require
    # fail-closed completeness.  Joint search uses balanced_frontier: round
    # robin across every sourced fallback, expanding 0, 1, 2, ... priority
    # actions, so a small budget cannot erase a whole caster/form branch.
    # This is explicitly a bounded search, never a complete policy claim.
    fallbacks = [*fillers, *([None] if auto_ids else [])]

    def options_for(filler):
        optional = [a for a in supported if filler is None or a.id != filler.id]
        for count in range(len(optional) + 1):
            for ordered in permutations(optional, count):
                for conditions in product(*(_rule_options(a, ir.resources) for a in ordered)):
                    yield filler, ordered, conditions

    def make_policy(filler, ordered, conditions):
        rules = tuple(PolicyRuleDefinition(
            id=f'candidate:{i}', action_id=a.id, conditions=guard,
            phase='combat', provenance={'authority': 'source_button_search'})
            for i, (a, guard) in enumerate(zip(ordered, conditions)))
        if filler is not None:
            rules += (PolicyRuleDefinition(
                id=f'candidate:{len(ordered)}', action_id=filler.id,
                phase='combat', provenance={'authority': 'source_button_search'}),)
        return PolicyDefinition(
            id=f'{ir.id}:source-search:{len(policies)}',
            label='Sourced offensive priority candidate', rules=rules,
            provenance={'authority': 'source_button_search',
                        'search_performed': True, 'source_button_discovery': True,
                        'budget_mode': budget_mode,
                        'envelope': ('auto_resource_priority_with_sourced_auto_fallback'
                                     if filler is None else 'single_target_offensive_subsets_priorities_dot_guards'),
                        'fallback_action_id': None if filler is None else filler.id,
                        'auto_attack_fallback_ids': auto_ids if filler is None else []})

    # Source-graph linked policy candidates are admitted *before* the generic
    # factorial frontier. Without this, a 32-policy budget only reaches one-
    # and two-button prefixes as the action universe grows, silently omitting
    # every legal Seal->Judgement->damage policy. No class/spell names here.
    linked_candidates = []
    if budget_mode == 'balanced_frontier':
        auras = [(a,next((e for e in a.effects if isinstance(e,StatusAuraEffect)),None))
                 for a in supported]
        auras = [(a,e) for a,e in auras if e is not None]
        consumers = [(a,e) for a in supported for e in a.effects
                     if isinstance(e,EventEmitEffect)]
        direct_fillers = [a for a in supported if any(_direct(e) for e in a.effects)]
        for aura_action,aura in auras:
            for consumer,emitter in consumers:
                if not any(t.event_kind==emitter.event_kind and t.required_aura_id==aura.aura_id
                           for t in ir.triggers):
                    continue
                guard_aura = (PolicyCondition(kind='aura_missing',scope='actor',aura_id=aura.aura_id),)
                guard_consumer = (PolicyCondition(kind='aura_present',scope='actor',aura_id=aura.aura_id),)
                for filler in direct_fillers[:2]:
                    linked_candidates.extend([
                        ((filler,consumer,aura_action),((),guard_consumer,guard_aura)),
                        ((consumer,aura_action,filler),(guard_consumer,guard_aura,())),
                    ])
        # A source-declared target-school-power Judgement is meaningful only
        # when followed by another aura's Holy damage. Build that path from
        # the trigger graph, including target debuff guards, not a hand-coded
        # class rotation or a legacy winner.
        for target_trigger in ir.triggers:
            target_effects=[e for e in target_trigger.effects if isinstance(e,TargetSchoolPowerEffect)]
            if not target_effects:continue
            opener=next(((a,e) for a,e in auras if e.aura_id==target_trigger.required_aura_id),None)
            if opener is None:continue
            for target_effect in target_effects:
                for consumer,emitter in consumers:
                    if emitter.event_kind != target_trigger.event_kind:continue
                    for finisher,finish_aura in auras:
                        if finisher.id==opener[0].id:continue
                        if not any(t.required_aura_id==finish_aura.aura_id and
                                   any(isinstance(e,DamageEffect) and e.school==target_effect.school
                                       for e in t.effects) for t in ir.triggers):
                            continue
                        for filler in direct_fillers[:1]:
                            target_missing=PolicyCondition(kind='aura_missing',scope='target',aura_id=target_effect.aura_id)
                            target_present=PolicyCondition(kind='aura_present',scope='target',aura_id=target_effect.aura_id)
                            linked_candidates.append(((filler,consumer,opener[0],finisher),(
                                (), (PolicyCondition(kind='aura_present',scope='actor',aura_id=opener[1].aura_id),target_missing),
                                (PolicyCondition(kind='aura_missing',scope='actor',aura_id=opener[1].aura_id),target_missing),
                                (PolicyCondition(kind='aura_missing',scope='actor',aura_id=finish_aura.aura_id),target_present))))
        # Fair source-family admission: reserve enough room for each linked
        # mechanic before generic prefixes. A bounded run remains bounded.
        for ordered,conditions in linked_candidates:
            if len(policies)>=max_policies:break
            policies.append(make_policy(None,ordered,conditions))
    generators = [options_for(filler) for filler in fallbacks]
    if budget_mode == 'strict':
        for gen in generators:
            for filler, ordered, conditions in gen:
                policies.append(make_policy(filler, ordered, conditions))
                if len(policies) > max_policies:
                    raise ValueError('source policy envelope exceeds explicit bound')
        truncated = False
    else:
        # Bounded lookahead only consumes at most budget+fallbacks generated
        # candidates; no factorial policy materialization at higher levels.
        active = list(generators)
        while active and len(policies) < max_policies:
            next_active = []
            for gen in active:
                try:
                    filler, ordered, conditions = next(gen)
                except StopIteration:
                    continue
                policies.append(make_policy(filler, ordered, conditions))
                next_active.append(gen)
                if len(policies) >= max_policies:
                    break
            active = next_active
        # A bounded lookahead detects incomplete enumeration without exploring
        # the entire factorial universe.  If a generator has another candidate,
        # the search is definitely truncated.
        truncated = bool(active and any(next(gen, None) is not None for gen in active))
    covered = {r.action_id for p in policies for r in p.rules}
    omitted = sorted({a.id for a in supported} - covered)
    return {
        'policies': tuple(policies),
        'discovered_buttons': list(discovery['action_ids']),
        'eligible_buttons': [a.id for a in supported],
        'excluded': excluded,
        'semantic_warnings': semantic_warnings,
        'candidate_count': len(policies),
        'budget_mode': budget_mode,
        'policy_frontier_truncated': truncated,
        'source_graph_linked_candidates_generated':len(linked_candidates),
        'source_graph_linked_candidates_admitted':min(len(linked_candidates),max_policies),
        'supported_actions_not_represented': omitted,
        'auto_attack_fallback_ids': auto_ids,
        'selected_mode_id': mode_id,
        'attacker_relative_position': attacker_relative_position,
        'complete_legal_action_search': False,
        'scope': ('single_target_offensive_plus_auto_resource_naked_actor'
                  if include_auto_resource_fallback else 'single_target_offensive_subsets_priorities_dot_guards_naked_actor'),
    }


def evaluate_discovered_policy_search(*, class_key: str, level: int,
                                      talent_selection: Mapping[str, int] | None = None,
                                      ir_slice=None, max_policies: int = 96,
                                      include_auto_resource_fallback: bool = False) -> dict:
    """Actually simulate every bounded candidate, including combat and recovery.

    Failed candidates are recorded, never assigned fictitious bad scores. This
    API does not require a canonical combat policy or a sourced race. Missing
    race provenance is explicitly reported as an optimization blocker.
    """
    source = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if source is None:
        raise ValueError('no source-backed game IR')
    selection = dict(talent_selection or {})
    validate_talent_selection(source, selection, level=level)
    ir, application = apply_talent_selection(source, selection, level=level)
    envelope = synthesize_source_policies(
        ir, level=level, max_policies=max_policies,
        include_auto_resource_fallback=include_auto_resource_fallback)
    scored, rejected = [], []
    for policy in envelope['policies']:
        result, execution, details = _policy_combat_evaluation(ir, level=level, policy_override=policy)
        if result is None or execution is None or not execution.timeline.target_defeated:
            rejected.append({'policy_id': policy.id,
                             'reason': (details or {}).get('stop_reason', 'target_not_defeated')})
            continue
        scored.append({
            'policy_id': policy.id,
            'actions': [r.action_id for r in policy.rules],
            'policy': policy.as_dict(),
            'seconds_per_mob': result.published_fields()['seconds_per_mob'],
            'combat_kill_s': execution.timeline.target_death_s,
            'recovery_s': details['recovery']['total_s'],
            'auto_attack_damage': execution.timeline.auto_attack_damage,
            'ending_resources': dict(execution.timeline.resources_after),
            'selected_actions': [dict(a) for a in execution.selected_actions],
            'evaluation': result.published_fields(),
        })
    if not scored:
        raise ValueError(f'no executable source policy: {len(rejected)} candidates rejected')
    scored.sort(key=lambda r: (r['seconds_per_mob'], r['policy_id']))
    scored_actions = {a for row in scored for a in row['actions']}
    coverage = audit_source_action_coverage(ir, level=level, search_envelopes=(envelope,))
    return {
        'action_coverage': coverage,
        'status': 'EVALUATED_INCOMPLETE_COVERAGE' if coverage['blocker_count'] else 'EVALUATED_SOURCE_DISCOVERED',
        'optimization_ready': False,
        'complete_optimizer': False,
        'class_key': class_key, 'level': level, 'source_ir_id': source.id,
        'race_source_backed': bool(source.actor.metadata.get('race_key')),
        'talent_application': application.as_dict(),
        'source_discovery': {k: v for k, v in envelope.items() if k != 'policies'},
        'candidate_count': len(envelope['policies']),
        'evaluated_count': len(scored), 'rejected_count': len(rejected),
        'rejected': rejected,
        'discovered_not_evaluated': [a for a in envelope['discovered_buttons'] if a not in scored_actions],
        'winner': scored[0], 'alternatives': scored[1:],
        'missing': ['source_backed_race_if_absent', 'unresolved_effect_semantics_if_any',
                    'full_action_and_mode_search',
                    'named_gear_optimization', 'joint_gear_talent_policy_fixed_point',
                    'multi_pull_and_survival', 'continuous_route', 'independent_fidelity'],
    }

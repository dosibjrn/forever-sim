"""Auditable, bounded generic combat+recovery trace; not a joint optimizer."""
from __future__ import annotations
from dataclasses import replace
from typing import Mapping

from src.game.data.forever import build_game_ir_slice
from src.game.talents import validate_talent_selection, apply_talent_selection
from src.v2.generic_backend import _policy_combat_evaluation
from src.game.level_legality import LevelState, validate_level_transition, require_exact_talent_ranks


def evaluate_level_trace(*, class_key: str, level: int, talent_selection: Mapping[str, int], candidate_action_ids: tuple[str, ...]) -> dict:
    source = build_game_ir_slice(class_key=class_key, level=level)
    if source is None or not source.policies:
        raise ValueError('no source-backed level/policy')
    require_exact_talent_ranks(talent_selection)
    validate_talent_selection(source, talent_selection, level=level)
    ir, talent_application = apply_talent_selection(source, talent_selection, level=level)
    seed = ir.policies[0]
    ids = {action.id for action in ir.actions}
    if not candidate_action_ids or len(set(candidate_action_ids)) != len(candidate_action_ids):
        raise ValueError('candidate actions must be nonempty and unique')
    if not set(candidate_action_ids).issubset(ids):
        raise ValueError('unavailable action requested')
    combat_rules = tuple(rule for rule in seed.rules if rule.phase == 'combat')
    allowed = {rule.action_id for rule in combat_rules}
    if not set(candidate_action_ids).issubset(allowed):
        raise ValueError('action unavailable in canonical combat policy')
    selected = tuple(rule for action_id in candidate_action_ids for rule in combat_rules if rule.action_id == action_id)
    policy = replace(seed, id=seed.id + ':trace:' + ','.join(candidate_action_ids), rules=selected + tuple(r for r in seed.rules if r.phase != 'combat'))
    result, execution, details = _policy_combat_evaluation(ir, level=level, policy_override=policy)
    if result is None or execution is None or not execution.timeline.target_defeated:
        raise ValueError('candidate did not defeat target')
    timeline = execution.timeline
    recovery = details['recovery']
    return {
        'status': 'EVALUATED', 'optimization_ready': False,
        'class_key': class_key, 'level': int(level),
        'talent': talent_application.as_dict(),
        'available_actions': [{'id': a.id, 'name': a.name, 'source': str(a.provenance)} for a in ir.actions],
        'candidate_actions': list(candidate_action_ids), 'policy': policy.as_dict(),
        'gear': {'scenario': 'source_actor_naked', 'named_items': [], 'gear_search_performed': False},
        'target': {'health': details['target_health'], 'source_status': details['target_source_status']},
        'combat': {'kill_s': timeline.target_death_s, 'resources_before': dict(timeline.resources_before),
                   'resources_after': dict(timeline.resources_after),
                   'event_count': len(timeline.events), 'selected_actions': [dict(x) for x in execution.selected_actions]},
        'recovery': recovery,
        'next_state': {'resources': dict(recovery['resources_after']), 'time_s': recovery['end_time_s']},
        'evaluation': result.published_fields(),
        'missing': ['named_gear_optimization', 'joint_talent_gear_policy_search', 'travel_timing', 'risk_validation', 'route_legality', 'independent_fidelity'],
    }


def compare_level_candidates(*, class_key: str, level: int, talent_selection: Mapping[str, int], candidates: Mapping[str, tuple[str, ...]]) -> dict:
    if len(candidates) < 2:
        raise ValueError('at least two candidates required')
    traces = {name: evaluate_level_trace(class_key=class_key, level=level, talent_selection=talent_selection, candidate_action_ids=actions) for name, actions in candidates.items()}
    best = min(traces, key=lambda k: traces[k]['evaluation']['seconds_per_mob'])
    worst = max(traces, key=lambda k: traces[k]['evaluation']['seconds_per_mob'])
    return {'status': 'EVALUATED', 'winner': best, 'runner_up': worst,
            'difference_seconds_per_mob': traces[worst]['evaluation']['seconds_per_mob'] - traces[best]['evaluation']['seconds_per_mob'],
            'traces': traces, 'complete_optimizer': False}


def evaluate_legal_level_continuation(*, parent: LevelState, child: LevelState) -> dict:
    """Evaluate child only after an independent legal source-scenario step.

    The P00b scorer alone accepted an arbitrary child build (including a
    refunded L10 point). This gate rejects it *before* combat is evaluated.
    """
    proof = validate_level_transition(parent, child)
    child_trace = evaluate_level_trace(
        class_key=child.class_key, level=child.level,
        talent_selection=child.talents, candidate_action_ids=child.action_ids)
    return {"status": "EVALUATED_LEGAL_CONTINUATION", "transition": proof,
            "child_trace": child_trace, "optimization_ready": False}


def evaluate_mode_auto_attack_trace(*, class_key: str, level: int,
                                    talent_selection: Mapping[str, int],
                                    entry_action_id: str) -> dict:
    """Score a source-declared mode-entry + automatic-attack policy.

    This is not a class-specific rotation. A valid mode, sourced entry/exit
    actions and an actual AutoAttackDefinition are all required.  The exit is
    executed through the generic runtime before drinking/recovery, rather
    than assuming a free mode reset. It does not claim enemy-attack fidelity.
    """
    from src.game.model import ModeChangeEffect, PolicyDefinition, PolicyRuleDefinition

    source = build_game_ir_slice(class_key=class_key, level=level)
    if source is None or not source.policies:
        raise ValueError('no source-backed level/policy')
    require_exact_talent_ranks(talent_selection)
    validate_talent_selection(source, talent_selection, level=level)
    ir, talent_application = apply_talent_selection(source, talent_selection, level=level)
    actions = {a.id: a for a in ir.actions}
    entry = actions.get(entry_action_id)
    if entry is None or not entry.provenance or len(entry.effects) != 1 or not isinstance(entry.effects[0], ModeChangeEffect):
        raise ValueError('mode entry action unavailable or not sourced')
    initial_modes = [m for m in ir.modes if m.initial]
    if len(initial_modes) != 1:
        raise ValueError('mode candidate needs one source-defined initial mode')
    initial = initial_modes[0]
    target_mode = entry.effects[0].target_mode_id
    modes = [m for m in ir.modes if m.id == target_mode and not m.initial]
    if len(modes) != 1 or entry.id not in initial.enabled_action_ids:
        raise ValueError('mode entry not enabled from initial mode')
    if not any(r.get('kind') == 'mode_is' and r.get('value') == initial.id for r in entry.requirements):
        raise ValueError('mode entry missing initial-mode requirement')
    attacks = [a for a in ir.auto_attacks if a.required_mode_id == target_mode and a.provenance]
    if not attacks:
        raise ValueError('mode candidate lacks source-backed auto attack')
    exits = [a for a in ir.actions
             if a.id in modes[0].enabled_action_ids and a.provenance
             and len(a.effects) == 1 and isinstance(a.effects[0], ModeChangeEffect)
             and a.effects[0].target_mode_id == initial.id]
    if len(exits) != 1:
        raise ValueError('mode candidate needs one source-backed exit')
    exit_action = exits[0]
    policy = PolicyDefinition(
        id=f'{ir.id}:source-mode-auto:{entry.id}',
        label='Source mode entry + automatic attacks',
        rules=(PolicyRuleDefinition(id='source_mode_entry', action_id=entry.id),),
        provenance={'authority': 'source_mode_auto_attack_candidate', 'search_performed': False},
    )
    result, execution, details = _policy_combat_evaluation(
        ir, level=level, policy_override=policy,
        post_combat_action_ids=(exit_action.id,),
    )
    if result is None or execution is None or not execution.timeline.target_defeated:
        raise ValueError('mode auto-attack candidate did not defeat target')
    timeline = execution.timeline
    if timeline.auto_attack_damage <= 0 or not details['post_combat_mode_actions']:
        raise ValueError('mode candidate did not execute source auto attack and exit')
    recovery = details['recovery']
    return {
        'status': 'EVALUATED', 'optimization_ready': False,
        'class_key': class_key, 'level': int(level),
        'talent': talent_application.as_dict(),
        'candidate_actions': [entry.id], 'policy': policy.as_dict(),
        'gear': {'scenario': 'source_actor_naked', 'named_items': [], 'gear_search_performed': False},
        'mode': {'entry_action_id': entry.id, 'mode_id': target_mode,
                 'auto_attack_ids': [a.id for a in attacks], 'exit_action_id': exit_action.id,
                 'exit_execution': details['post_combat_mode_actions'],
                 'recovery_mode_id': details['recovery_mode_id'],
                 'entry_provenance': [dict(x) for x in entry.provenance],
                 'auto_attack_provenance': [[dict(x) for x in a.provenance] for a in attacks]},
        'target': {'health': details['target_health'], 'source_status': details['target_source_status']},
        'combat': {'kill_s': timeline.target_death_s, 'resources_before': dict(timeline.resources_before),
                   'resources_after': dict(timeline.resources_after),
                   'auto_attack_damage': timeline.auto_attack_damage,
                   'auto_attack_swing_count': sum(e.kind == 'AutoAttackSwing' for e in timeline.events),
                   'mode_change_count': sum(e.kind == 'ModeChanged' for e in timeline.events),
                   'event_count': len(timeline.events),
                   'selected_actions': [dict(x) for x in execution.selected_actions]},
        'recovery': recovery,
        'next_state': {'resources': dict(recovery['resources_after']), 'time_s': recovery['end_time_s']},
        'evaluation': result.published_fields(),
        'missing': ['named_gear_optimization', 'joint_talent_gear_policy_search',
                    'travel_timing', 'enemy_incoming_attack_and_survival',
                    'mode_attack_table_fidelity', 'route_legality', 'independent_fidelity'],
    }

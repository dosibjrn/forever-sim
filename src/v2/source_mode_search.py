"""Fail-closed source IR mode transitions for future generic policy search.

Mode graph is independent of class, level and named game actions. A discovered
path is not a claim that the mode policy was scored or optimized.
"""
from __future__ import annotations

from src.game.model import ModeChangeEffect


def discover_mode_paths(ir, *, level: int, max_paths: int = 32) -> dict:
    if max_paths < 1:
        raise ValueError('mode path cap must be positive')
    initial = [m for m in ir.modes if m.initial]
    if len(initial) != 1:
        raise ValueError('exactly one source initial mode required')
    modes = {m.id: m for m in ir.modes}
    if len(modes) != len(ir.modes):
        raise ValueError('duplicate source modes')
    actions = {a.id: a for a in ir.actions}
    if len(actions) != len(ir.actions):
        raise ValueError('duplicate source action')
    transitions = []
    rejected = []
    for action in ir.actions:
        targets = [e.target_mode_id for e in action.effects if isinstance(e, ModeChangeEffect)]
        if not targets:
            continue
        reason = None
        mode_requirements = [r.get('value') for r in action.requirements if r.get('kind') == 'mode_is']
        other_reqs = [r for r in action.requirements if r.get('kind') not in ('mode_is', 'minimum_level')]
        levels = [r.get('value') for r in action.requirements if r.get('kind') == 'minimum_level']
        if not action.provenance or action.owner_actor_id != ir.actor.id:
            reason = 'missing_source_or_wrong_owner'
        elif len(targets) != 1 or len(action.effects) != 1 or targets[0] not in modes:
            reason = 'ambiguous_or_unknown_mode_effect'
        elif len(mode_requirements) != 1 or mode_requirements[0] not in modes or other_reqs:
            reason = 'ambiguous_source_mode_requirement'
        elif any(not isinstance(x, int) or level < x for x in levels):
            reason = 'level_locked_or_invalid'
        elif (modes[mode_requirements[0]].enabled_action_ids is not None
              and action.id not in modes[mode_requirements[0]].enabled_action_ids):
            reason = 'disabled_in_source_mode'
        elif any(c.resource_id not in {r.id for r in ir.resources} or c.amount < 0 for c in action.costs):
            reason = 'unknown_or_negative_resource_cost'
        elif action.cast_time_s < 0 or action.gcd_s < 0 or action.cooldown_s < 0:
            reason = 'invalid_transition_timing'
        if reason:
            rejected.append({'action_id': action.id, 'reason': reason})
        else:
            transitions.append((mode_requirements[0], targets[0], action.id))
    start = initial[0].id
    paths = []
    for source, target, enter in transitions:
        if source != start or target == start:
            continue
        exits = [a for s, t, a in transitions if s == target and t == start]
        for exit_id in exits:
            paths.append({'initial_mode': start, 'combat_mode': target,
                          'entry_action_id': enter, 'exit_action_id': exit_id,
                          'combat_auto_attack_ids': [a.id for a in ir.auto_attacks
                              if a.owner_actor_id == ir.actor.id and a.required_mode_id == target
                              and a.provenance and a.swing_time_s > 0],
                          'status': 'DISCOVERED_NOT_SCORED'})
            if len(paths) > max_paths:
                raise ValueError('source mode path envelope exceeds explicit cap')
    return {'paths': paths, 'rejected': rejected, 'initial_mode': start,
            'complete_mode_policy_search': False}


def evaluate_discovered_mode_search(*, class_key: str, level: int, ir_slice=None,
                                    max_paths: int = 32, max_policies_per_path: int = 256,
                                    schedule_incoming_attacks: bool = False,
                                    attacker_relative_position: str | None = None) -> dict:
    """Score sourced entry → in-mode priority/auto → sourced exit → recovery.

    A bounded, naked-actor single-target mode-policy comparison, not a joint
    gear/talent optimization. The actual runtime pays entry and recovery costs.
    An invalid/paid exit is rejected; it is never replaced by a free reset.
    """
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
    from src.v2.generic_backend import _policy_combat_evaluation
    from src.v2.source_policy_search import synthesize_source_policies

    ir = ir_slice if ir_slice is not None else build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        raise ValueError('no source-backed game IR')
    discovered = discover_mode_paths(ir, level=level, max_paths=max_paths)
    actions = {a.id: a for a in ir.actions}
    scored, rejected, paths = [], [], []
    for path in discovered['paths']:
        entry, exit_action = actions[path['entry_action_id']], actions[path['exit_action_id']]
        # Recovery is evaluated in the initial mode. The shared evaluator only
        # supports a sourced zero-time, zero-cost exit; reject all other cases.
        if (exit_action.costs or exit_action.cast_time_s != 0 or exit_action.gcd_s != 0
                or exit_action.cooldown_s != 0):
            rejected.append({'path': path, 'reason': 'paid_or_timed_exit_unsupported'})
            continue
        try:
            envelope = synthesize_source_policies(
                ir, level=level, max_policies=max_policies_per_path,
                include_auto_resource_fallback=True, mode_id=path['combat_mode'],
                attacker_relative_position=attacker_relative_position)
        except ValueError as exc:
            rejected.append({'path': path, 'reason': str(exc)})
            continue
        paths.append({'path': path, 'candidate_count': envelope['candidate_count'],
                      'eligible_buttons': envelope['eligible_buttons'],
                      'auto_attack_fallback_ids': envelope['auto_attack_fallback_ids'],
                      'excluded': envelope['excluded']})
        for candidate in envelope['policies']:
            entry_rule = PolicyRuleDefinition(
                id='source-mode-entry', action_id=entry.id, phase='combat',
                conditions=(PolicyCondition(kind='mode_state', value=path['initial_mode']),),
                provenance={'authority': 'source_mode_search'})
            policy = PolicyDefinition(
                id=f'{candidate.id}:via:{entry.id}', label='Sourced mode entry and in-mode priority',
                rules=(entry_rule, *candidate.rules),
                provenance={'authority': 'source_mode_search', 'search_performed': True,
                            'entry_action_id': entry.id, 'exit_action_id': exit_action.id})
            try:
                result, execution, details = _policy_combat_evaluation(
                    ir, level=level, policy_override=policy,
                    post_combat_action_ids=(exit_action.id,),
                    schedule_incoming_attacks=schedule_incoming_attacks,
                    attacker_relative_position=attacker_relative_position)
            except (ValueError, RuntimeError) as exc:
                rejected.append({'path': path, 'policy_id': policy.id,
                                 'reason': f'runtime_rejected:{exc}'})
                continue
            if result is None or execution is None or not execution.timeline.target_defeated:
                rejected.append({'path': path, 'policy_id': policy.id,
                                 'reason': (details or {}).get('stop_reason', 'target_not_defeated')})
                continue
            actions_used = [dict(row) for row in execution.selected_actions]
            if not actions_used or actions_used[0]['action_id'] != entry.id:
                rejected.append({'path': path, 'policy_id': policy.id,
                                 'reason': 'mode_entry_not_executed'})
                continue
            exit_rows = details.get('post_combat_mode_actions') or []
            if len(exit_rows) != 1 or exit_rows[0]['action_id'] != exit_action.id:
                rejected.append({'path': path, 'policy_id': policy.id,
                                 'reason': 'source_mode_exit_not_executed'})
                continue
            scored.append({'path': path, 'policy_id': policy.id,
                           'policy': policy.as_dict(), 'seconds_per_mob': result.seconds_per_mob,
                           'combat_kill_s': execution.timeline.target_death_s,
                           'recovery_s': details['recovery']['total_s'],
                           'entry_costs': [c.as_dict() for c in entry.costs],
                           'selected_actions': actions_used,
                           'auto_attack_damage': execution.timeline.auto_attack_damage,
                           'resources_after_combat': dict(execution.timeline.resources_after),
                           'post_combat_mode_actions': exit_rows,
                           'recovery_mode_id': details['recovery_mode_id'],
                           'evaluation': result.published_fields()})
    if not scored:
        reasons = sorted({str(row.get('reason', 'unknown')) for row in rejected})
        raise ValueError(f'no executable source mode policy: {len(rejected)} candidates rejected ({"; ".join(reasons)})')
    scored.sort(key=lambda row: (row['seconds_per_mob'], row['policy_id']))
    return {'status': 'EVALUATED_SOURCE_MODE_POLICY', 'optimization_ready': False,
            'complete_optimizer': False, 'class_key': class_key, 'level': level,
            'source_ir_id': ir.id, 'discovered_paths': discovered,
            'attacker_relative_position': attacker_relative_position,
            'path_envelopes': paths, 'candidate_count': sum(p['candidate_count'] for p in paths),
            'evaluated_count': len(scored), 'rejected_count': len(rejected),
            'rejected': rejected, 'winner': scored[0], 'alternatives': scored[1:],
            'missing': ['full_cross_mode_policy_search', 'gear_and_talent_search',
                        'continuous_multi_pull_recovery', 'survival', 'route', 'independent_fidelity']}

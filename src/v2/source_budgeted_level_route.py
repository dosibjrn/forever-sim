"""Bounded, *contiguous* scenario route search, reusing production L2.

This is not a complete leveling route: XP/travel, source-effect completeness,
and true inter-level resource persistence are not modeled. The route does not
collect or verify trainer, quest, item, or learned-rank acquisition evidence;
MythicSim remains authoritative for game legality.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import process_time_ns, monotonic_ns
from typing import Any

from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_legal_beam import legal_point_frontier
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted


@dataclass
class _Path:
    state: LevelState
    steps: list[dict]
    cumulative_s_per_mob: float


def _source_successors(ir, parent: LevelState | None, *, level: int,
                       max_children: int) -> list[dict[str, int]]:
    prior = dict(parent.talents) if parent else {}
    # The unchanged allocation is a legal banked-points option.  Other moves
    # are SOURCE-valid +1 point selections, not arbitrary respecs.
    choices = [prior]
    choices.extend(legal_point_frontier(ir, prior, level=level, allow_transfers=False))
    legal = []
    for selection in choices:
        validate_talent_selection(ir, selection, level=level)
        normalized = {k: int(v) for k, v in selection.items() if v}
        if normalized not in legal:
            legal.append(normalized)
    # Bounded breadth is always explicit, never called exhaustive.
    return legal[:max_children]


def search_source_bounded_level_route(*, class_key: str, start_level: int = 10,
        end_level: int = 20, max_active_paths: int = 2,
        max_children_per_path: int = 3, max_l2_per_state: int = 8,
        max_events_per_state: int = 1600, max_total_events: int = 100000,
        max_total_l2_attempts: int = 1000, use_l1: bool = False,
        max_total_cpu_ns: int | None = None,
        max_total_wall_ns: int | None = None) -> dict[str, Any]:
    """Score contiguous bounded scenario states with the existing L2 scorer.

    This function does not establish native game legality or spell acquisition.
    CPU and events are charged across all attempted states, including failed
    searches and scratch verifications. Path selection is a bounded beam based
    solely on measured full-cycle outcomes; travel and cross-level resources
    remain unmodeled.
    """
    if (start_level < 10 or end_level > 60 or end_level < start_level
            or min(max_active_paths, max_children_per_path, max_l2_per_state,
                   max_events_per_state, max_total_events, max_total_l2_attempts) < 1):
        raise ValueError('invalid bounded legal level route parameters')
    if max_total_cpu_ns is not None and max_total_cpu_ns < 1:
        raise ValueError('invalid total CPU budget')
    if max_total_wall_ns is not None and max_total_wall_ns < 1:
        raise ValueError('invalid total walltime budget')
    started = process_time_ns()
    started_wall = monotonic_ns()
    paths: list[_Path] = []
    events = attempts = partials = scored_states = blocked_states = 0
    cpu_ns = 0
    failures: list[dict[str, Any]] = []
    level_stats: list[dict[str, Any]] = []
    completed_to: int | None = None
    for level in range(start_level, end_level + 1):
        ir = build_game_ir_slice(class_key=class_key, level=level)
        if ir is None:
            failures.append({'level': level, 'reason': 'NO_SOURCE_IR_AT_LEVEL'})
            break
        parents = paths if paths else [None]
        if level > start_level and not paths:
            break
        accepted: list[_Path] = []
        proposed = evaluated = 0
        for parent in parents:
            for talents in _source_successors(ir, parent.state if parent else None,
                                               level=level, max_children=max_children_per_path):
                proposed += 1
                cpu_remaining = (None if max_total_cpu_ns is None else
                                 max_total_cpu_ns - (process_time_ns() - started))
                wall_remaining = (None if max_total_wall_ns is None else
                                  max_total_wall_ns - (monotonic_ns() - started_wall))
                if (attempts >= max_total_l2_attempts or events >= max_total_events or
                        (cpu_remaining is not None and cpu_remaining <= 0) or
                        (wall_remaining is not None and wall_remaining <= 0)):
                    failures.append({'level': level, 'reason': 'GLOBAL_COMPUTE_BUDGET_EXHAUSTED'})
                    break
                talented, _ = apply_talent_selection(ir, talents, level=level)
                cpu_remaining = (None if max_total_cpu_ns is None else
                                 max_total_cpu_ns - (process_time_ns() - started))
                wall_remaining = (None if max_total_wall_ns is None else
                                  max_total_wall_ns - (monotonic_ns() - started_wall))
                if ((cpu_remaining is not None and cpu_remaining <= 0)
                        or (wall_remaining is not None and wall_remaining <= 0)):
                    failures.append({'level':level,'reason':'GLOBAL_TIME_BUDGET_EXHAUSTED'})
                    break
                remaining_events = min(max_events_per_state,
                                       max_total_events - events)
                remaining_attempts = min(max_l2_per_state, max_total_l2_attempts - attempts)
                # A fresh best+scratch validation needs at least 3 attempts;
                # refusing to call a truncated result a verified route step.
                if remaining_attempts < 3 or remaining_events < 3:
                    failures.append({'level': level, 'reason': 'INSUFFICIENT_VERIFICATION_RESERVE'})
                    break
                out = run_source_stateful_budgeted(
                    class_key=class_key, level=level, ir_slice=talented,
                    max_l2_attempts=remaining_attempts,
                    max_event_transitions=remaining_events,
                    use_l1=use_l1, search_auto_fallback=True,
                    search_mode_paths=True, family_budget_mode='measured_balanced',
                    max_cpu_ns=cpu_remaining,max_wall_ns=wall_remaining)
                evaluated += 1
                events += int(out.get('event_transitions', 0))
                attempts += int(out.get('l2_attempts', 0))
                partials += int(out.get('l1_attempts', 0))
                cpu_ns += int(out.get('full_run_cpu_ns', 0))
                winner = out.get('winner')
                if not winner or out.get('verification_complete') is not True:
                    blocked_states += 1
                    failures.append({'level': level, 'talents': talents,
                                     'reason': out['status'],
                                     'scratch_completed': out.get('verification_completed', 0)})
                    continue
                action_ids = tuple(dict.fromkeys(a for a in (
                    *winner['prefix'], winner['fallback'])
                    if a != '__source_verified_auto_attack_only__'))
                if not action_ids:
                    # An auto-only continuation has no input button; route
                    # states still need a provable executable action identity.
                    blocked_states += 1
                    failures.append({'level': level, 'talents': talents,
                                     'reason': 'NO_ACTION_IDENTITY_FOR_LEVEL_STATE'})
                    continue
                state = LevelState(class_key=class_key, level=level,
                                   race_key=ir.actor.metadata.get('race_key'),
                                   talents=talents, action_ids=action_ids)
                # Retain only the bounded legacy scenario check here; it is
                # not native game-legality evidence.
                validate_level_state(state)
                transition = (validate_level_transition(parent.state, state)
                              if parent is not None else None)
                score = float(winner['score_s_per_mob'])
                step = {'level': level, 'source_scenario_race': state.race_key,
                        'talents': talents, 'source_action_ids': list(action_ids),
                        'prefix': winner['prefix'], 'fallback': winner['fallback'],
                        'guarded_action': winner.get('guarded_action'),
                        'guarded_conditions': winner.get('guarded_conditions', []),
                        'full_cycle_s_per_mob': score,
                        'source_context': out['source_context'],
                        'scratch_verification_complete': True,
                        'real_l2_attempts': out['l2_attempts'],
                        'real_l1_attempts': out['l1_attempts'],
                        'executor_event_transitions': out['event_transitions'],
                        'cpu_ns': out['full_run_cpu_ns'],
                        'source_legal_transition': transition}
                accepted.append(_Path(state, (parent.steps if parent else []) + [step],
                                      (parent.cumulative_s_per_mob if parent else 0.) + score))
                scored_states += 1
            if (attempts >= max_total_l2_attempts or events >= max_total_events or
                    (max_total_cpu_ns is not None and process_time_ns()-started >= max_total_cpu_ns) or
                    (max_total_wall_ns is not None and monotonic_ns()-started_wall >= max_total_wall_ns)):
                break
        if not accepted:
            if not any(x['level'] == level for x in failures):
                failures.append({'level': level, 'reason': 'NO_VERIFIED_L2_STATE'})
            break
        # Preserve multiple independently explored build families when possible,
        # but never call a bounded beam the global minimum over all talents.
        accepted.sort(key=lambda p: (p.cumulative_s_per_mob,
                         tuple(sorted(p.state.talents.items()))))
        distinct = []
        for p in accepted:
            if p.state.talents not in [q.state.talents for q in distinct]:
                distinct.append(p)
            if len(distinct) >= max_active_paths:
                break
        paths = distinct
        completed_to = level
        level_stats.append({'level': level, 'proposed_candidate_states': proposed,
                            'scorer_attempted_states': evaluated,
                            'scratch_verified_states': len(accepted),
                            'retained_paths': len(paths),
                            'cumulative_real_l2_attempts': attempts,
                            'cumulative_executor_events': events,
                            'cumulative_scorer_cpu_ns': cpu_ns})
    winner = min(paths, key=lambda p: p.cumulative_s_per_mob) if paths else None
    complete_bounded = bool(winner and completed_to == end_level)
    return {
        'status': ('EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
                   if complete_bounded else 'PARTIAL_BOUNDED_SOURCE_SCENARIO'),
        'class_key': class_key, 'requested_levels': [start_level, end_level],
        'last_contiguous_level': completed_to,
        'bounded_contiguous_levels': len(winner.steps) if winner else 0,
        'selected_route': winner.steps if winner else [],
        'sum_per_level_s_per_mob': winner.cumulative_s_per_mob if winner else None,
        'level_stats': level_stats, 'failures': failures,
        'global_budget': {'max_events': max_total_events,
                          'max_l2_attempts': max_total_l2_attempts,
                          'max_cpu_ns': max_total_cpu_ns,
                          'max_wall_ns': max_total_wall_ns},
        'compute': {'l2_attempts': attempts, 'l1_attempts': partials,
                    'event_transitions': events,
                    'scorer_cpu_ns': cpu_ns,
                    'total_cpu_ns': process_time_ns() - started,
                    'total_wall_ns': monotonic_ns() - started_wall,
                    'successful_source_legal_states': scored_states,
                    'blocked_scorer_states': blocked_states},
        'source_legal_talent_transitions': complete_bounded,
        'source_actions_level_available': complete_bounded,
        'named_gear_acquisition_verified': False,
        'travel_and_xp_timing_verified': False,
        'cross_level_resource_carry_verified': False,
        'indexed_effect_source_complete': False,
        'independent_reference_verified': False,
        'full_route_complete': False,
        'accepted_class_level_checkpoints': 0,
        'limitations': ['Representative naked source actor only, no equipment acquisition',
                        'Full L2 kill+recovery+survival independently verified per level',
                        'Levels scored separately; real XP/travel and carryover not modeled',
                        'Talent alternatives truncated by explicit source-legal beam',
                        'Missing indexed effects and source mechanics block validated checkpoints'],
    }

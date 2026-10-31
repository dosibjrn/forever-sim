"""Bounded, *contiguous* source-scenario route search, reusing production L2.

A solved corridor is NOT a complete leveling route: trainer/item acquisition,
XP/travel, source effect completeness, and true inter-level resource persistence
are not proven.  This is the bridge from isolated class-level L2 canaries to
legally linked scored states.  No spell/class name appears in the search.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from time import process_time_ns, monotonic_ns
from typing import Any
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.game.data.forever.source_acquisition_events import (
    AcquisitionCharacterState, AcquisitionEvent, apply_source_consistent_acquisition,
    audit_source_consistent_actions)
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_legal_beam import legal_point_frontier
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted


@dataclass
class _Path:
    state: LevelState
    steps: list[dict]
    cumulative_s_per_mob: float
    acquisition_state: AcquisitionCharacterState | None = None


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
        max_total_wall_ns: int | None = None,
        initial_acquisition_state: AcquisitionCharacterState | None = None,
        acquisition_events_by_level: dict[int, tuple[AcquisitionEvent, ...]] | None = None,
        world_origin_id: str | None = None,
        world_events: tuple[dict, ...] = (),
        world_db_path: str | Path | None = None) -> dict[str, Any]:
    """Score source-valid contiguous level states with real executor L2.

    CPU and events are charged across ALL attempted states including failed
    searches and scratch verifications. Path selection is a bounded beam based
    solely on measured full-cycle outcomes. Never infer travel or acquisition.
    """
    if (start_level < 10 or end_level > 60 or end_level < start_level
            or min(max_active_paths, max_children_per_path, max_l2_per_state,
                   max_events_per_state, max_total_events, max_total_l2_attempts) < 1):
        raise ValueError('invalid bounded legal level route parameters')
    if max_total_cpu_ns is not None and max_total_cpu_ns < 1:
        raise ValueError('invalid total CPU budget')
    if max_total_wall_ns is not None and max_total_wall_ns < 1:
        raise ValueError('invalid total walltime budget')
    if initial_acquisition_state is not None and (
            initial_acquisition_state.class_key.lower() != class_key.lower()
            or initial_acquisition_state.level != start_level):
        raise ValueError('acquisition initial state must match route identity/level')
    if initial_acquisition_state is None and acquisition_events_by_level:
        raise ValueError('acquisition events require explicit initial state')
    if acquisition_events_by_level and any(type(lvl) is not int or lvl < start_level
            or lvl > end_level for lvl in acquisition_events_by_level):
        raise ValueError('acquisition events outside route levels')
    # World-certified acquisition and synthetic source-consistent scenarios
    # are mutually exclusive. Current world witness is for ONE exact level;
    # never carry its currency/XP/gear or learned ranks across unseen levels.
    if world_origin_id is not None and (initial_acquisition_state is not None
            or acquisition_events_by_level or start_level != end_level):
        raise ValueError('WORLD_TRACE_SINGLE_LEVEL_AND_NO_SYNTHETIC_ACQUISITION')
    if world_origin_id is None and world_events:
        raise ValueError('WORLD_EVENTS_REQUIRE_VERIFIED_ORIGIN')
    started = process_time_ns()
    started_wall = monotonic_ns()
    paths: list[_Path] = []
    events = attempts = partials = scored_states = blocked_states = 0
    acquisition_events_charged = 0
    cpu_ns = 0
    failures: list[dict[str, Any]] = []
    level_stats: list[dict[str, Any]] = []
    completed_to: int | None = None
    world_verified_trace = None
    if world_origin_id is not None:
        # The existing canonical world verifier replays every trainer and
        # travel event against the original captured source bytes. The
        # controller NEVER accepts caller-supplied learned_spell_ids here.
        from src.game.data.forever.source_world_acquisition import verify_acquisition_trace
        from src.game.data.forever.source_world_acquisition import UnverifiedWorldEvent
        try:
            world_verified_trace = verify_acquisition_trace(
                class_key=class_key,level=start_level,anchor_id=world_origin_id,
                events=world_events,db_path=world_db_path)
        except (UnverifiedWorldEvent,ValueError) as exc:
            return {'status':'BLOCKED_UNVERIFIED_WORLD_ACQUISITION',
                'class_key':class_key,'requested_levels':[start_level,end_level],
                'last_contiguous_level':None,'bounded_contiguous_levels':0,
                'selected_route':[],'accepted_class_level_checkpoints':0,
                'full_route_complete':False,'world_acquisition_verified':False,
                'failures':[{'level':start_level,'reason':str(exc)}],
                'compute':{'l2_attempts':0,'event_transitions':0,
                           'acquisition_event_attempts':len(world_events),
                           'total_cpu_ns':process_time_ns()-started,
                           'total_wall_ns':monotonic_ns()-started_wall}}
        initial_acquisition_state = AcquisitionCharacterState(
            class_key=class_key,level=start_level,
            zone_id=world_verified_trace['zone_id'],
            copper=world_verified_trace['remaining_copper'],
            learned_spell_ids=frozenset(world_verified_trace['verified_learned_spell_ids']))
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
                if (attempts >= max_total_l2_attempts or events + acquisition_events_charged >= max_total_events or
                        (cpu_remaining is not None and cpu_remaining <= 0) or
                        (wall_remaining is not None and wall_remaining <= 0)):
                    failures.append({'level': level, 'reason': 'GLOBAL_COMPUTE_BUDGET_EXHAUSTED'})
                    break
                talented, _ = apply_talent_selection(ir, talents, level=level)
                acquired_state = None
                acquisition_records = []
                if initial_acquisition_state is not None:
                    acquired_state = (parent.acquisition_state if parent is not None
                                      else initial_acquisition_state)
                    acquired_state = replace(acquired_state, level=level)
                    try:
                        for event in (acquisition_events_by_level or {}).get(level, ()):
                            if events + acquisition_events_charged >= max_total_events:
                                raise ValueError('global event budget exhausted by acquisition')
                            # Even failed acquisition attempts consume the
                            # shared event-attempt budget.
                            acquisition_events_charged += 1
                            acquired_state, record = apply_source_consistent_acquisition(
                                acquired_state, event)
                            acquisition_records.append(record)
                    except ValueError as exc:
                        blocked_states += 1
                        failures.append({'level':level, 'talents':talents,
                                         'reason':'SOURCE_ACQUISITION_EVENT_BLOCKED',
                                         'detail':str(exc)})
                        continue
                    # Restrict the SAME production Game IR passed to the
                    # existing controller. An indexed but unlearned rank is
                    # never allowed into its policy search.
                    talented = replace(talented, actions=tuple(a for a in talented.actions
                        if len(_source_spell_ids(a)) == 1 and
                        next(iter(_source_spell_ids(a))) in acquired_state.learned_spell_ids))
                    if not talented.actions:
                        blocked_states += 1
                        failures.append({'level':level, 'talents':talents,
                                         'reason':'NO_SOURCE_ACQUIRED_EXECUTABLE_ACTIONS'})
                        continue
                # Charge acquisition events and parsing CPU/wall time to the
                # SAME global budget as L2, including failed candidate work.
                cpu_remaining = (None if max_total_cpu_ns is None else
                                 max_total_cpu_ns - (process_time_ns() - started))
                wall_remaining = (None if max_total_wall_ns is None else
                                  max_total_wall_ns - (monotonic_ns() - started_wall))
                if ((cpu_remaining is not None and cpu_remaining <= 0)
                        or (wall_remaining is not None and wall_remaining <= 0)):
                    failures.append({'level':level,'reason':'ACQUISITION_USED_GLOBAL_TIME_BUDGET'})
                    break
                remaining_events = min(max_events_per_state,
                                       max_total_events - events - acquisition_events_charged)
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
                                   talents=talents, action_ids=action_ids,
                                   world_origin_id=world_origin_id,
                                   world_acquisition_events=(tuple(world_events)
                                       if world_verified_trace is not None else ()))
                # Source legality is independent of runtime winning scores.
                # World mode REPLAYS the actual canonical source trace here,
                # after the optimizer found a policy, to prevent both stale
                # source IDs and unsupported policy substitutions.
                validate_level_state(state,require_world_acquisition=(
                    world_verified_trace is not None),world_db_path=world_db_path)
                if acquired_state is not None:
                    acquired_audit = audit_source_consistent_actions(talented, acquired_state, action_ids)
                    if not acquired_audit['source_consistent']:
                        blocked_states += 1
                        failures.append({'level':level,'talents':talents,
                                         'reason':'POLICY_USES_UNACQUIRED_RANK',
                                         'blockers':acquired_audit['blockers']})
                        continue
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
                        'source_legal_transition': transition,
                        'source_consistent_acquisition': bool(acquired_state is not None),
                        'source_acquisition_events': acquisition_records,
                        'world_acquisition_verified': world_verified_trace is not None}
                accepted.append(_Path(state, (parent.steps if parent else []) + [step],
                                      (parent.cumulative_s_per_mob if parent else 0.) + score,
                                      acquired_state))
                scored_states += 1
            if (attempts >= max_total_l2_attempts or events + acquisition_events_charged >= max_total_events or
                    (max_total_cpu_ns is not None and process_time_ns()-started >= max_total_cpu_ns) or
                    (max_total_wall_ns is not None and monotonic_ns()-started_wall >= max_total_wall_ns)):
                break
        if not accepted:
            if not any(x['level'] == level for x in failures):
                failures.append({'level': level, 'reason': 'NO_VERIFIED_SOURCE_LEGAL_L2_STATE'})
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
        level_stats.append({'level': level, 'proposed_source_legal_states': proposed,
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
                    'event_transitions': events, 'acquisition_event_attempts': acquisition_events_charged,
                    'charged_total_events': events + acquisition_events_charged,
                    'scorer_cpu_ns': cpu_ns,
                    'total_cpu_ns': process_time_ns() - started,
                    'total_wall_ns': monotonic_ns() - started_wall,
                    'successful_source_legal_states': scored_states,
                    'blocked_scorer_states': blocked_states},
        'source_legal_talent_transitions': complete_bounded,
        'source_player_action_filter_applied': initial_acquisition_state is not None,
        'source_consistent_local_acquisition_events': sum(
            len(step['source_acquisition_events']) for step in (winner.steps if winner else [])),
        'initial_learned_spells_are_assumed_not_verified': (initial_acquisition_state is not None and world_verified_trace is None),
        'initial_acquisition_state_world_proven': world_verified_trace is not None,
        'source_actions_level_available': complete_bounded,
        'named_gear_acquisition_verified': False,
        'ability_trainer_quest_rune_acquisition_verified': bool(world_verified_trace is not None and complete_bounded),
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

"""Source-legal, paid cross-talent refinement on an independently found named gear.

A shared L2 attempt/event budget pays for EVERY legal neighbor evaluation,
including blocked results, and for fresh policy search on the best new talent.
No old build, spell identity, or hidden score oracle enters the proposal logic.
This is a stage of the existing joint optimizer, not a second combat engine.
"""
from __future__ import annotations
from time import process_time_ns
from math import isfinite
from src.game.talent_frontier import source_legal_talent_neighbors, allocation_key
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_budgeted_gear import _fixed_opening_score
from src.v2.source_stateful_adapter import stateful_policy_as_prefix
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded


def refine_named_gear_talents(*, ir, class_key: str, level: int, incumbent: dict,
                               max_l2_attempts: int, max_event_transitions: int,
                               schedule_incoming_attacks: bool = True,
                               reserve_fresh_policy_attempts: int = 10,
                               max_neighborhood_rounds: int = 4,
                               search_guarded_continuations: bool = True,
                               search_mode_paths: bool = True,
                               family_budget_mode: str = 'measured_balanced') -> dict:
    """Explore actual one-point legal edits under winning named gear+policy.

    Best *fixed-policy* scores are separately tracked from a fresh policy search;
    the result may be a stronger bounded challenger, never a global optimum.
    """
    if max_l2_attempts < 1 or max_event_transitions < 1:
        raise ValueError('positive shared budgets required')
    if reserve_fresh_policy_attempts < 0 or reserve_fresh_policy_attempts >= max_l2_attempts:
        raise ValueError('fresh policy reserve must leave at least one neighbor attempt')
    start=process_time_ns()
    selected=incumbent['gear_policy_result']['winner']
    gear=selected['gear']; policy_record=selected['winner']
    if not gear or not policy_record:
        raise ValueError('source named gear and real winning policy required')
    for item in gear['slots'].values():
        if item.get('required_level_origin') != 'observed' or int(item['required_level']) > level:
            raise ValueError('nonobserved or over-level named gear')
    best_allocation=dict(incumbent['allocation'])
    best_score=float(incumbent['score_s_per_mob'])
    if not isfinite(best_score) or best_score<=0:
        raise ValueError('finite positive real incumbent score required')
    original_score=best_score
    attempts=events=verified=blocked=0
    visited={allocation_key(best_allocation)}
    observations=[]
    rounds=[]
    for round_id in range(max_neighborhood_rounds):
        if attempts >= max_l2_attempts-reserve_fresh_policy_attempts or events >= max_event_transitions:
            break
        neighbors=source_legal_talent_neighbors(ir,best_allocation,level=level)
        round_best=None
        round_start=attempts
        for candidate in neighbors['neighbors']:
            key=candidate.allocation
            if key in visited:
                continue
            if attempts >= max_l2_attempts-reserve_fresh_policy_attempts or events >= max_event_transitions:
                break
            visited.add(key)
            attempts += 1  # even failed evaluations consume budget
            observed_events=0
            score=None; reason=None
            try:
                talented,_=apply_talent_selection(ir,dict(key),level=level)
                geared,application=apply_gear_selection(talented,
                    aggregate_stats=gear['aggregate_stats'],
                    selected_items=tuple(gear['slots'].values()),
                    source='canonical_sqlite_forever_catalogue')
                if application.unsupported_stats:
                    raise ValueError('non-executable named gear stats')
                def meter(count):
                    nonlocal observed_events
                    observed_events += int(count)
                score=_fixed_opening_score(geared,policy_record,level,
                    schedule_incoming_attacks,meter=meter,
                    max_events=max_event_transitions-events)
            except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
                observed_events += int(exc.events_processed)
                reason=type(exc).__name__
            except (ValueError,RuntimeError,KeyError) as exc:
                reason=f'{type(exc).__name__}: {exc}'
            events += observed_events
            if events > max_event_transitions:
                raise AssertionError('cross-talent hard event budget exceeded')
            ok=score is not None and isfinite(score) and score>0
            verified+=int(ok);blocked+=int(not ok)
            record={'allocation':dict(key),'operation':candidate.operation,
                    'score_s_per_mob':float(score) if ok else None,
                    'events':observed_events,'attempt':attempts,
                    'status':'FULL_L2_FIXED_POLICY' if ok else 'BLOCKED_L2',
                    'reason':reason}
            observations.append(record)
            if ok and float(score) < best_score-1e-10 and (
                    round_best is None or (float(score),key)<(round_best[0],round_best[1])):
                round_best=(float(score),key)
        rounds.append({'round':round_id,'parent_allocation':dict(best_allocation),
                       'paid_attempts':attempts-round_start,
                       'best_improvement':None if round_best is None else round_best[0]})
        if round_best is None:
            break
        best_score,best_key=round_best
        best_allocation=dict(best_key)
    fresh=None
    if allocation_key(best_allocation)!=allocation_key(incumbent['allocation']) and (
            max_l2_attempts-attempts>0 and max_event_transitions-events>0):
        talented,_=apply_talent_selection(ir,best_allocation,level=level)
        geared,application=apply_gear_selection(talented,
            aggregate_stats=gear['aggregate_stats'],
            selected_items=tuple(gear['slots'].values()),
            source='canonical_sqlite_forever_catalogue')
        if application.unsupported_stats:
            raise ValueError('non-executable named gear stats')
        fresh=stateful_policy_as_prefix(class_key=class_key,level=level,
            max_evaluations=min(reserve_fresh_policy_attempts,max_l2_attempts-attempts),
            ir_slice=geared,schedule_incoming_attacks=schedule_incoming_attacks,
            max_event_transitions=max_event_transitions-events,use_l1=False,
            use_prefix_cache=False,search_guarded_continuations=search_guarded_continuations,
            search_mode_paths=search_mode_paths,family_budget_mode=family_budget_mode)
        attempts+=fresh['attempted'];events+=fresh['event_transitions']
        verified+=fresh['evaluated'];blocked+=fresh['blocked']
    if attempts>max_l2_attempts or events>max_event_transitions or attempts!=verified+blocked:
        raise AssertionError('cross-talent shared L2 accounting violation')
    fresh_winner=None if fresh is None else fresh.get('winner')
    return {'status':'SOURCE_LEGAL_BOUNDED_REFINEMENT',
            'original_allocation':dict(incumbent['allocation']),
            'original_s_per_mob':original_score,
            'best_fixed_allocation':best_allocation,
            'best_fixed_s_per_mob':best_score,
            'fixed_policy_improvement_s':original_score-best_score,
            'fixed_policy_record':policy_record,
            'fixed_named_gear':gear,
            'fresh_policy_winner':fresh_winner,
            'fresh_policy_score_s_per_mob':None if fresh_winner is None else float(fresh_winner['score_s_per_mob']),
            'fresh_policy_attempts':0 if fresh is None else fresh['attempted'],
            'fresh_policy_events':0 if fresh is None else fresh['event_transitions'],
            'fresh_policy_is_better_than_original':bool(fresh_winner and float(fresh_winner['score_s_per_mob'])<original_score),
            'fresh_policy_is_better_than_fixed':bool(fresh_winner and float(fresh_winner['score_s_per_mob'])<best_score),
            'attempted':attempts,'evaluated':verified,'blocked':blocked,
            'event_transitions':events,'controller_cpu_ns':process_time_ns()-start,
            'visited_legal_allocations':len(visited),'rounds':rounds,
            'observations':observations,
            'all_candidates_generated_from_canonical_source_neighbors':True,
            'no_heldout_fixture_in_search':True,
            'gear_not_reoptimized_after_talent_refinement':True,
            'source_complete':False,'global_optimum_proven':False}

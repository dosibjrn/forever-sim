"""Source-only two-profile discovery: never read a held-out winner before search.

This is a budgeted experiment orchestrating the EXISTING joint source optimizer,
not a new combat engine or a source of hardcoded game-specific facts.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from time import monotonic, process_time
from dataclasses import replace
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def fresh_replay(*, class_key: str, level: int, winner: dict):
    """Zero cache, zero old oracle; production execution and source legality."""
    source=build_game_ir_slice(class_key=class_key,level=level)
    talented,_=apply_talent_selection(source,winner['allocation'],level=level)
    gear=winner['gear_policy_result']['winner']['gear']
    if not gear or any(v.get('required_level_origin')!='observed'
                           or int(v['required_level'])>level for v in gear['slots'].values()):
        raise ValueError('ITEM_REQUIRED_LEVEL_NOT_OBSERVED_LEGAL')
    geared,application=apply_gear_selection(talented,
        aggregate_stats=gear['aggregate_stats'], selected_items=tuple(gear['slots'].values()),
        source='canonical_sqlite_forever_catalogue')
    if application.unsupported_stats:
        raise ValueError('UNSUPPORTED_NAMED_GEAR_STATS')
    record=winner['gear_policy_result']['winner']['winner']
    policy=_make_policy(geared,record['fallback'],
        guarded_action=record.get('guarded_action'),
        guarded_conditions=tuple(_condition_from_record(g) for g in record.get('guarded_conditions',())))
    score,execution,details=_policy_combat_evaluation(geared,level=level,
        policy_override=policy,opening_action_ids=tuple(record['prefix']),
        schedule_incoming_attacks=True)
    if (score is None or execution is None or not execution.timeline.target_defeated
            or details.get('actor_survived') is not True
            or not ordered_prefix_executed(execution,record['prefix'])):
        raise ValueError('COLD_FULL_L2_FAILED')
    expected=float(winner['score_s_per_mob'])
    if abs(score.seconds_per_mob-expected)>1e-9:
        raise ValueError(f'COLD_SCORE_MISMATCH {score.seconds_per_mob} != {expected}')
    return {'score_s_per_mob':float(score.seconds_per_mob),
            'kill_s':float(execution.timeline.target_death_s),
            'recovery_s':float(details['recovery']['total_s']),
            'event_transitions':int(details['event_transitions_new']),
            'target_defeated':True,'actor_survived':True,
            'source_item_required_levels_observed':True,
            'full_L2_same_engine':True,'search_cache_disabled':True}


def worker(class_key: str, level: int)->dict:
    started=monotonic(); cpu_started=process_time()
    # Generic source search hyperparameters; NO legacy oracle module, fixture,
    # class-specific spell/talent/item fact, or previous winning build is loaded.
    common={'class_key':class_key,'level':level,
        'max_evaluations':135,'evaluations_per_talent':45,'initial_search':12,
        'search_per_gear':10,'max_gear_states':2,
        'policy_search_backend':'stateful','stateful_use_l1':False,
        'stateful_search_guarded_continuations':True,
        'stateful_search_mode_paths':True,
        'stateful_family_budget_mode':'measured_balanced',
        'max_event_transitions':16000,'required_level_policy':'observed',
        'gear_role_exploration':True,
        'probe_stats':('agility','strength','stamina'),
        'probe_deltas':(5.0,20.0),'talent_corridor_reserve':3}
    profiles=[('source_joint_fast', {
        **common,'max_evaluations':205, 'max_event_transitions':22000,
        'post_talent_refinement_budget':70,
    }),('source_joint_wide', {
        **common,'max_evaluations':800,'evaluations_per_talent':52,
        'post_talent_refinement_budget':130,'max_event_transitions':100000,
        'talent_corridor_reserve':9,'max_gear_states':4,'initial_search':10,
        'search_per_gear':16,'probe_stats':('agility','strength','stamina','spirit','armor','dodge_rating'),
        'probe_deltas':(5.0,20.0),
    })]
    runs=[]; contenders=[]
    for profile,args in profiles:
        began=monotonic()
        result=run_source_budgeted_joint_talents(**args)
        winner=result.get('winner')
        if not winner or result['attempted']>args['max_evaluations'] or result['event_transitions']>args['max_event_transitions']:
            raise ValueError('SEARCH_MISSING_WINNER_OR_BUDGET_VIOLATION')
        contenders.append((float(winner['score_s_per_mob']),profile,winner))
        runs.append({'profile':profile,'wall_s':monotonic()-began,
                     's_per_mob':float(winner['score_s_per_mob']),
                     'attempts':result['attempted'],
                     'events':result['event_transitions'],
                     'rejected_or_blocked':result['blocked'],
                     'talent_states':result['talent_states_evaluated'],
                     'pending_legal_talent_states':result['pending_legal_talent_states'],
                     'global_optimum_proven':result['complete_search'],
                     'source_complete':False})
    score,profile,winner=min(contenders,key=lambda v:(v[0],v[1]))
    replay=fresh_replay(class_key=class_key,level=level,winner=winner)
    return {'schema':'wf299_30s_blind_joint_discovery_v1',
            'objective':'real kill+recovery+survival seconds per mob',
            'class_key':class_key,'level':level,
            'profile_results':runs,
            'selected_profile':profile,'winner':winner,
            'fresh_scratch_replay':replay,
            'worker_wall_s_including_imported_processing':monotonic()-started,
            'worker_cpu_s':process_time()-cpu_started,
            'old_fixture_not_imported_or_read_before_or_after_search':True,
            'global_optimum_proven':False,'source_complete':False,
            'formal_checkpoint_accepted':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--class-key',required=True)
    p.add_argument('--level',required=True,type=int);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    evidence=worker(a.class_key,a.level)
    # Atomic durable evidence only after BOTH profiles and cold replay pass.
    staging=a.output.with_name(a.output.name+'.tmp')
    staging.write_text(json.dumps(evidence,indent=2,default=str)+'\n')
    os.replace(staging,a.output)
    print(json.dumps({'score_s_per_mob':evidence['winner']['score_s_per_mob'],
                      'worker_wall_s':evidence['worker_wall_s_including_imported_processing'],
                      'profiles':evidence['profile_results'],
                      'formal_checkpoint_accepted':False}))

"""Reproducible real Forever source gear + adaptive ordered-prefix feedback."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.generic_backend import _policy_combat_evaluation
from src.game.gear import apply_gear_selection


def run(*, class_key='druid',level=10,budget=120,initial_search=None,search_per_gear=24):
    if initial_search is None:
        initial_search=40 if class_key=='mage' else 24
    verification_reserved = 2 if class_key=='druid' and level==10 else 0
    if budget <= verification_reserved:
        raise ValueError('budget must include reserved independent challenger replays')
    result=run_source_budgeted_gear(class_key=class_key,level=level,
        max_evaluations=budget-verification_reserved,initial_search=initial_search,
        search_per_gear=search_per_gear)
    # Explicit separate historical priority candidate: baseline .233 used a
    # naked source-priority Wrath-only Druid L10 policy. Not a full OG build.
    if class_key=='druid' and level==10:
        ir=build_game_ir_slice(class_key='druid',level=10)
        old=('wrath:5177',)
        matches=[p for p in synthesize_source_policies(ir,level=level,max_policies=96)['policies']
                 if tuple(x.action_id for x in p.rules)==old]
        if len(matches)!=1:
            raise ValueError('frozen historical naked priority candidate missing')
        candidate,execution,details=_policy_combat_evaluation(ir,level=level,
            policy_override=matches[0],schedule_incoming_attacks=True)
        result['historical_naked_priority_challenger']={
            'baseline':'.233', 'same_objective':True, 'same_naked_gear':True,
            'evaluated_independently':True,
            'seconds_per_mob':candidate.seconds_per_mob if candidate else None,
            'selected_actions':[dict(x) for x in execution.selected_actions],
            'valid_gear_build_comparison':False,
            'reason':'Historic .233 naked priority policy; not a complete named OG gear/talent configuration.'}
        gear = result['winner']['gear']
        if gear is None:
            raise ValueError('no named gear winner for equal-gear historical challenge')
        geared,_=apply_gear_selection(ir,aggregate_stats=gear['aggregate_stats'],
            selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
        gear_priority,gear_exec,_=_policy_combat_evaluation(geared,level=level,
            policy_override=matches[0],schedule_incoming_attacks=True)
        result['same_named_gear_historical_priority_challenger']={
            'baseline':'.233 priority policy',
            'scenario':'same gear, level, source, incoming+recovery as discovered winning gear',
            'evaluated_independently':True, 'same_named_gear':True,
            'seconds_per_mob':gear_priority.seconds_per_mob if gear_priority else None,
            'selected_actions':[dict(x) for x in gear_exec.selected_actions],
            'valid_policy_only_comparison':True,
            'valid_full_OG_comparison':False}
    result['verification_reserved_attempts']=verification_reserved
    result['search_budget']=budget-verification_reserved
    result['total_budget_including_verification']=budget
    result['total_real_simulator_attempts']=result['attempted']+verification_reserved
    assert result['total_real_simulator_attempts']<=budget
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',default='druid')
    p.add_argument('--level',type=int,default=10)
    p.add_argument('--budget',type=int,default=120)
    p.add_argument('--initial-search',type=int,default=None)
    p.add_argument('--search-per-gear',type=int,default=24)
    p.add_argument('--output',default='WF259_REAL_GEAR_POLICY_REPLAY.json')
    args=p.parse_args()
    r=run(class_key=args.class_key,level=args.level,budget=args.budget,
          initial_search=args.initial_search,search_per_gear=args.search_per_gear)
    Path(args.output).write_text(json.dumps(r,indent=2,default=str)+'\n')
    print(json.dumps({'status':r['status'],'attempted':r['attempted'],
                      'evaluated':r['evaluated'],'blocked':r['blocked'],
                      'winner_s_per_mob':r['winner']['winner']['score_s_per_mob'],
                      'gear_states':r['named_gear_states_evaluated']}))

"""WF324 Druid L20 paid talent screening followed by existing blind 2→100-mob selection.

Known older WF303 build is NEVER an input to the search or finalist selection.
It is evaluated separately in wf324_persistent_same_source.py as a held-out challenger.
"""
from __future__ import annotations
import json,os
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS


def run(db:Path, *,screening=65,limit=320,event_cap=55000,screen_candidates=64,finalists=12):
    kw={**JOINT_ARGS,'max_evaluations':limit,'evaluations_per_talent':38,
        'initial_search':12,'search_per_gear':9,'max_gear_states':2,
        'max_event_transitions':event_cap,'talent_screening_attempts':screening}
    with ability_source_scope(db):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
        begin=process_time_ns()
        joint=run_source_budgeted_joint_talents(**kw,ir_slice=ir)
        after_search=process_time_ns()
        finalist_result=select_persistent_finalists(class_key='druid',level=20,joint_result=joint,
            screen_mobs=2,finalist_mobs=100,max_finalists=finalists,
            max_screen_candidates=screen_candidates,
            source_legal_neighbors_per_seed=0,max_screen_wall_s=8,max_finalist_wall_s=12)
        elapsed=process_time_ns()-begin
    def summarize(row):
        return {'allocation':row['allocation'],
            'single_mob_stage_score':row['single_mob_stage_score'],
            'screen_mean_s_per_mob':row['screen_mean_s_per_mob'],
            'hundred_mob':row['persistent'],
            'paid_candidate_origin':row['stage'].get('paid_candidate_origin',row['stage'].get('operation')),
            'source_policy_and_gear_reused':row['source_policy_and_gear_reused']}
    return {'status':'BOUNDED_NOT_CHECKPOINT','class_key':'druid','level':20,
        'db_path':str(db),'screening_attempts':screening,
        'joint_attempted':joint['attempted'],'joint_evaluated':joint['evaluated'],
        'joint_blocked':joint['blocked'],'joint_events':joint['event_transitions'],
        'distinct_talents_paid_L2':joint['distinct_talent_allocations_paid_L2'],
        'fresh_gear_policy_talent_states':joint['talent_states_evaluated'],
        'search_cpu_s':(after_search-begin)/1e9,'total_cpu_s':elapsed/1e9,
        'paid_candidate_stages':finalist_result['paid_candidate_stages'],
        'screened_2mob':finalist_result['screen_evaluated'],
        'finalists_100mob':finalist_result['finalists_evaluated'],
        'complete_100mob':sum(x['persistent']['status']=='COMPLETE' for x in finalist_result['finalists']),
        'winner':summarize(finalist_result['winner']) if finalist_result['winner'] else None,
        'finalists':[summarize(x) for x in finalist_result['finalists']],
        'full_source_legal_coverage':False,'validated_checkpoint':False,
        'limitations':finalist_result['limitations']}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--screening',type=int,default=65)
    a=p.parse_args()
    r=run(a.db,screening=a.screening)
    a.output.write_text(json.dumps(r,indent=2))
    print(json.dumps({k:v for k,v in r.items() if k not in ('finalists','db_path')},indent=2))

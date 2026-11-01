"""Follow up a blind hundred-mob finalist with independently reoptimized sourced gear/policy.

The talent allocation is from THIS run's measured source paid candidates, never old fixtures.
"""
from __future__ import annotations
import json, argparse
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from src.game.talents import validate_talent_selection
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS


def run(*,db:Path,discovery:dict,budget:int=180,event_cap:int=30000):
    if discovery.get('validated_checkpoint') is not False or not discovery.get('winner'):
        raise ValueError('needs an independently discovered bounded winner')
    allocation=dict(discovery['winner']['allocation'])
    kwargs={**JOINT_ARGS,'max_evaluations':budget,'evaluations_per_talent':58,
            'initial_search':18,'search_per_gear':12,'max_gear_states':3,
            'max_event_transitions':event_cap,'talent_screening_attempts':0}
    with ability_source_scope(db):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
        validate_talent_selection(ir,allocation,level=20)
        begin=process_time_ns()
        new=run_source_budgeted_joint_talents(**kwargs,ir_slice=ir,initial_allocation=allocation)
        middle=process_time_ns()
        newfinal=select_persistent_finalists(class_key='druid',level=20,joint_result=new,
            screen_mobs=2,finalist_mobs=100,max_finalists=8,max_screen_candidates=28,
            max_screen_wall_s=9,max_finalist_wall_s=12)
        finish=process_time_ns()
    w=newfinal['winner']
    return {'status':'BOUNDED_NOT_CHECKPOINT','only_class':'druid','only_level':20,
      'source':'WF324 blind own finalist; not held-out baseline','initial_allocation_from_discovery':allocation,
      'attempted':new['attempted'],'evaluated':new['evaluated'],'blocked':new['blocked'],
      'events':new['event_transitions'],'search_cpu_s':(middle-begin)/1e9,
      'total_cpu_s':(finish-begin)/1e9,
      'candidate_stages':newfinal['paid_candidate_stages'],'screened':newfinal['screen_evaluated'],
      'finalists':newfinal['finalists_evaluated'],
      'winner':None if not w else {'allocation':w['allocation'],
         'mean_s_per_mob':w['persistent']['mean_s_per_mob'],
         'persistent':w['persistent'],'source_gear':w['stage']['gear_policy_result']['winner']['gear'],
         'source_policy':w['stage']['gear_policy_result']['winner']['winner']},
      'validated_checkpoint':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--discovery',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); d=json.loads(a.discovery.read_text());x=run(db=a.db,discovery=d)
    a.output.write_text(json.dumps(x,indent=2)); print(json.dumps({k:v for k,v in x.items() if k!='winner'},indent=2));print('winner',x['winner'] and {k:x['winner'][k] for k in ['allocation','mean_s_per_mob']})

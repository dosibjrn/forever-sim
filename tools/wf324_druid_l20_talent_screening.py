"""WF324: independently measured Druid L20 talent breadth on the existing scorer.

Evidence tool only; does not approve checkpoint or change source facts.
"""
from __future__ import annotations
import json, argparse
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_stateful_budgeted import _make_policy,_condition_from_record
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS


def run(db_path:Path,*,screening:int=65,limit:int=320,event_cap:int=55000):
    kwargs={**JOINT_ARGS, 'max_evaluations':limit, 'evaluations_per_talent':38,
        'initial_search':12,'search_per_gear':9,'max_gear_states':2,
        'max_event_transitions':event_cap,'talent_screening_attempts':screening}
    with ability_source_scope(db_path):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db_path)
        t0=process_time_ns()
        search=run_source_budgeted_joint_talents(**kwargs,ir_slice=ir)
        used_cpu_ns=process_time_ns()-t0
        win=search['winner']
        if win is None:
            raise AssertionError('no Druid L20 L2 winner')
        talent_ir,_=apply_talent_selection(ir,win['allocation'],level=20)
        selection=win['gear_policy_result']['winner']
        if selection is None or selection.get('gear') is None:
            raise AssertionError('winner was not named-gear scored')
        gear=selection['gear']
        for slot,item in gear['slots'].items():
            if int(item['required_level'])>20 or item['required_level_origin']!='observed':
                raise AssertionError(f'unsupported level/gear {slot} {item}')
        gear_ir,_=apply_gear_selection(talent_ir,aggregate_stats=gear['aggregate_stats'],
            selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
        record=selection['winner']
        policy=_make_policy(gear_ir,record['fallback'],
            guarded_action=record.get('guarded_action'),
            guarded_conditions=tuple(_condition_from_record(c) for c in record.get('guarded_conditions',())))
        scored, execution, detail = _policy_combat_evaluation(gear_ir,level=20,
            policy_override=policy,opening_action_ids=tuple(record['prefix']),
            schedule_incoming_attacks=True)
        if not(scored and execution and execution.timeline.target_defeated and
            detail.get('actor_survived') and ordered_prefix_executed(execution,record['prefix'])):
            raise AssertionError('independent scratch L2 replay invalid')
        if abs(scored.seconds_per_mob-win['score_s_per_mob'])>1e-8:
            raise AssertionError('winner scratch score mismatch')
        if search['attempted']!=search['evaluated']+search['blocked']:
            raise AssertionError('paid L2 attempt accounting broken')
        if search['attempted']>limit or search['event_transitions']>event_cap:
            raise AssertionError('shared L2 hard budget broken')
        return {
            'status':'BOUNDED_NOT_CHECKPOINT',
            'settings':kwargs,
            'score_s_per_mob':win['score_s_per_mob'],
            'allocation':win['allocation'],
            'gear':gear,
            'policy':record,
            'attempted':search['attempted'],
            'evaluated':search['evaluated'],
            'blocked':search['blocked'],
            'event_transitions':search['event_transitions'],
            'cpu_ns':used_cpu_ns,
            'screened_talent_states':search['talent_screening_attempts'],
            'distinct_talent_states_paid_L2':search['distinct_talent_allocations_paid_L2'],
            'fresh_talent_gear_policy_states':search['talent_states_evaluated'],
            'scratch_replay':{'score_s_per_mob':scored.seconds_per_mob,
                'events':detail['event_transitions_new'],
                'kill_s':execution.timeline.target_death_s,
                'recovery_s':detail['recovery']['total_s']},
            'screening':search['talent_screening_evidence'],
            'stages':[{k:v for k,v in s.items() if k not in ('gear_policy_result','talent_application')}
                      for s in search['stages']],
            'coverage_limitations':search['limitations'],
        }


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--screening',type=int,default=65)
    args=p.parse_args()
    x=run(args.db,screening=args.screening)
    args.output.write_text(json.dumps(x,indent=2,default=str)+'\n')
    print(json.dumps({k:x[k] for k in ('score_s_per_mob','allocation','attempted','evaluated','blocked','event_transitions','cpu_ns','screened_talent_states','distinct_talent_states_paid_L2','fresh_talent_gear_policy_states','scratch_replay')},indent=2))
if __name__=='__main__':main()

"""Compare one real paid joint controller with/without source-tree corridors."""
from __future__ import annotations
import json,sys
from pathlib import Path
from time import process_time_ns,monotonic_ns
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf282_source_role_heldout_benchmark import frozen_heldout

ARGS=dict(class_key='druid',level=20,max_evaluations=160,
    evaluations_per_talent=24,initial_search=7,search_per_gear=12,
    max_gear_states=1,policy_search_backend='stateful',
    stateful_use_l1=False,stateful_search_guarded_continuations=True,
    stateful_search_mode_paths=True,stateful_family_budget_mode='measured_balanced',
    max_event_transitions=20000,required_level_policy='observed',
    gear_role_exploration=True,probe_stats=('agility','strength'),probe_deltas=(5.0,))

def run(reserve):
    cpu,wall=process_time_ns(),monotonic_ns()
    r=run_source_budgeted_joint_talents(**ARGS,talent_corridor_reserve=reserve)
    cpu,wall=process_time_ns()-cpu,monotonic_ns()-wall
    curve=[]
    event_cumulative=0
    incumbent=None
    for stage in r['stages']:
        event_cumulative+=stage.get('event_transitions',0)
        value=stage.get('score_s_per_mob')
        if value is not None:
            incumbent=value if incumbent is None else min(incumbent,value)
        curve.append({'events':event_cumulative,'best_s_per_mob':incumbent,
                      'attempts':stage['budget_end']})
    return {'reserve':reserve,'attempted':r['attempted'],'events':r['event_transitions'],
        'score_vs_actual_events_at_stage_boundaries':curve,
        'cpu_ns':cpu,'wall_ns':wall,'best':r['winner']['score_s_per_mob'] if r['winner'] else None,
        'winner_allocation':r['winner']['allocation'] if r['winner'] else None,
        'stages':[{'allocation':s['allocation'],'operation':s['operation'],
                   'score':s.get('score_s_per_mob'),'attempted':s['attempted'],
                   'events':s.get('event_transitions'),'status':s['status']} for s in r['stages']],
        'source_corridors_reserved':r['source_corridors_reserved'],
        'source_corridors_evaluated':r['source_corridors_evaluated'],
        'source_corridors_unvisited':r['source_corridors_unvisited'],
        'best_vs_budget':r['best_vs_budget'],
        'source_complete':False,'heldout_seeded':False,
        'budget_respected':r['attempted']<=ARGS['max_evaluations'] and r['event_transitions']<=ARGS['max_event_transitions']}

if __name__=='__main__':
    result={'args':ARGS,'baseline':run(0),'corridors':run(6),'heldout':frozen_heldout()}
    result['same_caps']=True
    result['same_actual_compute']=result['baseline']['events']==result['corridors']['events'] and result['baseline']['attempted']==result['corridors']['attempted']
    cap=min(result['baseline']['events'],result['corridors']['events'])
    result['common_observed_event_checkpoint']=cap
    for name in ('baseline','corridors'):
        curve=result[name]['score_vs_actual_events_at_stage_boundaries']
        result[name]['best_at_common_event_checkpoint']=next((row['best_s_per_mob'] for row in reversed(curve) if row['events']<=cap),None)
    Path(sys.argv[1]).write_text(json.dumps(result,indent=2,default=str))
    for name in ('baseline','corridors'):
        r=result[name];print(name,r['best'],r['attempted'],r['events'],r['cpu_ns']/1e6,'ms',r['winner_allocation'],flush=True)
    print('heldout',result['heldout']['score_s_per_mob'],flush=True)

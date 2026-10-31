"""Reproduce WF262 stateful W261-in-W260 real gear/talent replay."""
from __future__ import annotations

import argparse, json
from pathlib import Path
from time import process_time_ns
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def replay(*,class_key='druid',level=10,max_evaluations=90,
           event_cap=2900,use_l1=True,use_prefix_cache=True):
    start=process_time_ns()
    result=run_source_budgeted_joint_talents(class_key=class_key,level=level,
        max_evaluations=max_evaluations,
        evaluations_per_talent=(38 if class_key=='mage' else 36),
        initial_search=(10 if class_key=='mage' else 8),
        search_per_gear=(10 if class_key=='mage' else 8),
        max_gear_states=2,policy_search_backend='stateful',
        max_event_transitions=event_cap,stateful_use_l1=use_l1,
        stateful_use_prefix_cache=use_prefix_cache)
    result['measured_total_process_cpu_ns']=process_time_ns()-start
    result['measurement_method']='time.process_time_ns including controller and source adapter, no background work'
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',default='druid')
    p.add_argument('--level',type=int,default=10)
    p.add_argument('--budget',type=int,default=90)
    p.add_argument('--event-cap',type=int,default=2900)
    p.add_argument('--no-l1',action='store_true')
    p.add_argument('--no-cache',action='store_true')
    p.add_argument('--output',default='WF262_REAL_JOINT_STATEFUL_REPLAY.json')
    a=p.parse_args()
    r=replay(class_key=a.class_key,level=a.level,max_evaluations=a.budget,
        event_cap=a.event_cap,use_l1=not a.no_l1,
        use_prefix_cache=not a.no_cache)
    Path(a.output).write_text(json.dumps(r,indent=2,default=str)+'\n')
    print(json.dumps({'class':r['class_key'],'level':r['level'],
      'status':r['status'],'l2_attempts':r['attempted'],
      'event_transitions':r['event_transitions'],
      'l1_attempts':r['stateful_l1_attempts'],
      'winner_talents':r['winner']['allocation'] if r['winner'] else None,
      'winner_seconds_per_mob':r['winner']['score_s_per_mob'] if r['winner'] else None,
      'process_cpu_ms':round(r['measured_total_process_cpu_ns']/1e6,3)}))

if __name__=='__main__': main()

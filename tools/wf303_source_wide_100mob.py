"""Source-only WIDE independent search + 100 persistent CombatRuntime mobs.

No gold build or historical result enters search. Search is not capped at 30 s;
only candidate experiments may be stopped early if demonstrably poor.
"""
from __future__ import annotations
import argparse,json,os
from time import monotonic
from pathlib import Path
from src.v2.source_persistent_joint_finalists import run_source_persistent_profile_search

def run(class_key='druid',level=20):
    common=dict(evaluations_per_talent=52,initial_search=10,search_per_gear=16,
        max_gear_states=4,policy_search_backend='stateful',
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,stateful_family_budget_mode='measured_balanced',
        required_level_policy='observed',gear_role_exploration=True,
        probe_stats=('agility','strength','stamina','spirit','armor','dodge_rating'),
        probe_deltas=(5.,20.),talent_corridor_reserve=9,
        post_talent_refinement_budget=130,
        max_evaluations=800,max_event_transitions=100000)
    return run_source_persistent_profile_search(class_key=class_key,level=level,
      profiles=(('source_wide_no_oracle',common),),screen_mobs=2,finalist_mobs=100,
      max_finalists=5,max_screen_candidates=15,source_legal_neighbors_per_seed=0,
      max_screen_wall_s=2.,max_finalist_wall_s=4.)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();r=run();f=a.output.with_suffix('.tmp');f.write_text(json.dumps(r,indent=2,default=str));os.replace(f,a.output)
 print(json.dumps({'status':r['screening']['status'],'wall_s':r['wall_s'],
 'joint_attempts':r['total_search_attempts'],'joint_events':r['total_search_events'],
 'winner':r['persistent_winner']['persistent']['mean_s_per_mob'] if r['persistent_winner'] else None,
 'screened':r['screening']['screen_evaluated'],'finalists':r['screening']['finalists_evaluated'],
 'single_score':r['persistent_winner']['single_mob_stage_score'] if r['persistent_winner'] else None}))

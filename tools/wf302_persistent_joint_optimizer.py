"""Run source-derived joint search with real 2-mob screening and 100-mob finals.

No old builds, hardcoded class abilities, fixture winners or XP/world modeling.
The 30-second heuristic limits throwaway exploration, not exhaustive proof.
"""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from src.v2.source_persistent_joint_finalists import run_source_persistent_profile_search
from src.game.recovery_between_pulls import BetweenPullPolicy


def run(class_key:str,level:int,*,second_profile:bool=False,max_finalists:int=8,
        max_screen_candidates:int=40,neighbor_proposals_per_seed:int=0,
        recovery_mana_fractions:tuple[float,...]=(0.1,0.3))->dict:
    common={'evaluations_per_talent':45,'initial_search':12,'search_per_gear':10,
        'max_gear_states':2,'policy_search_backend':'stateful',
        'stateful_use_l1':False,'stateful_search_guarded_continuations':True,
        'stateful_search_mode_paths':True,'stateful_family_budget_mode':'measured_balanced',
        'required_level_policy':'observed','gear_role_exploration':True,
        'probe_stats':('agility','strength','stamina'),
        'probe_deltas':(5.,20.),'talent_corridor_reserve':3}
    profiles=[('source_fast',dict(common,max_evaluations=205,max_event_transitions=22000,
        post_talent_refinement_budget=70))]
    if second_profile:
        profiles.append(('source_independent_broad',dict(common,max_evaluations=310,
            max_event_transitions=36000,post_talent_refinement_budget=85,
            talent_corridor_reserve=6,max_gear_states=3)))
    recovery_policies=(None,*(BetweenPullPolicy(health_fraction=0.5,mana_fraction=fraction)
                              for fraction in dict.fromkeys(recovery_mana_fractions)))
    return run_source_persistent_profile_search(class_key=class_key,level=level,
        profiles=tuple(profiles),screen_mobs=2,finalist_mobs=100,
        max_finalists=max_finalists,max_screen_candidates=max_screen_candidates,
        source_legal_neighbors_per_seed=neighbor_proposals_per_seed,
        recovery_policies=recovery_policies)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--second-profile',action='store_true')
    p.add_argument('--finalists',type=int,default=8)
    p.add_argument('--screen-candidates',type=int,default=40)
    p.add_argument('--source-legal-neighbor-per-seed',type=int,default=0)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--recovery-mana-fraction',type=float,action='append',default=None,
                   help='Repeat to search source-paid recovery thresholds alongside full recovery (default: 0.1, 0.3)')
    a=p.parse_args()
    result=run(a.class_key,a.level,second_profile=a.second_profile,
        max_finalists=a.finalists,max_screen_candidates=a.screen_candidates,
        neighbor_proposals_per_seed=a.source_legal_neighbor_per_seed,
        recovery_mana_fractions=tuple(a.recovery_mana_fraction) if a.recovery_mana_fraction is not None else (0.1,0.3))
    staging=a.output.with_suffix(a.output.suffix+'.tmp')
    staging.write_text(json.dumps(result,default=str,indent=2)+'\n')
    os.replace(staging,a.output)
    best=result.get('persistent_winner')
    print(json.dumps({'status':result['screening']['status'],
        'winner_s_per_mob':best['persistent']['mean_s_per_mob'] if best else None,
        'joint_attempts':result['total_search_attempts'],
        'screened':result['screening']['screen_evaluated'],
        'hundred_mob_finalists':result['screening']['finalists_evaluated'],
        'wall_s':result['wall_s'],
        'formal_checkpoint_accepted':False}))

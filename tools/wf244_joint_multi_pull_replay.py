"""Reproducible source-independent joint sample plus exact held-out .240 Feral."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import search_joint_repeated_pulls,replay_exact_challenger
from tools.wf243_joint_multi_pull_replay import frozen_policy


def run(*,allocations=20,screen_gears=1,finalists=1,policy_cap=16,pulls=3,
        refinement_budget=0,refinement_rounds=1):
    root=Path(__file__).resolve().parents[1]
    fixture=json.loads((root/'fixtures/wf243_heldout_feral_l20.json').read_text())
    key,level=fixture['class_key'],fixture['level']
    independent=search_joint_repeated_pulls(class_key=key,level=level,pulls=pulls,
        max_allocations=allocations,screening_gear_count=screen_gears,
        finalists=finalists,policy_cap=policy_cap,
        held_out_allocation=fixture['talent_allocation'],
        refinement_budget=refinement_budget,refinement_rounds=refinement_rounds, strategy='sample')
    ir=build_game_ir_slice(class_key=key,level=level)
    gears=_gear_envelope(key,level,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    matching=[g for g in gears if g['id']==fixture['gear_id']]
    if len(matching)!=1:
        raise ValueError('frozen challenger gear unavailable or ambiguous')
    gear=matching[0]
    slots={k:int(v['item_id']) for k,v in gear['selection'].slots.items()}
    if slots!={k:int(v['item_id']) for k,v in fixture['gear_slots'].items()}:
        raise ValueError('frozen challenger gear mismatch')
    old=replay_exact_challenger(class_key=key,level=level,gear=gear,
        allocation=fixture['talent_allocation'],policy=frozen_policy(fixture['policy']),
        pulls=pulls,post_combat_action_ids=(fixture['policy']['provenance']['exit_action_id'],))
    winner=independent['independent_winner']
    return {'version':'0.11.48.244','status':'EVALUATED_BOUNDED',
        'source':'canonical_sqlite','independent_search':independent,
        'held_out_frozen_challenger':old,
        'same_engine_and_objective':True,
        'delta_new_minus_old_s_per_mob':winner['seconds_per_mob']-old['seconds_per_mob'],
        'global_optimum_proven':False,
        'budgets':{'allocations':allocations,'screen_gears':screen_gears,
                   'finalists':finalists,'policy_cap':policy_cap,'pulls':pulls}}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--allocations',type=int,default=20)
    parser.add_argument('--screen-gears',type=int,default=1)
    parser.add_argument('--finalists',type=int,default=1)
    parser.add_argument('--policy-cap',type=int,default=16)
    parser.add_argument('--pulls',type=int,default=3)
    parser.add_argument('--refinement-budget',type=int,default=0)
    parser.add_argument('--refinement-rounds',type=int,default=1)
    parser.add_argument('--output',default='WF244_INDEPENDENT_JOINT_REPEATED_PULL.json')
    args=parser.parse_args()
    result=run(allocations=args.allocations,screen_gears=args.screen_gears,
        finalists=args.finalists,policy_cap=args.policy_cap,pulls=args.pulls,
        refinement_budget=args.refinement_budget,refinement_rounds=args.refinement_rounds)
    Path(args.output).write_text(json.dumps(result,indent=2))
    winner=result['independent_search']['independent_winner']
    print(json.dumps({'winner_s_per_mob':winner['seconds_per_mob'],
        'winner_talents':winner['talent_allocation'],
        'winner_gear':winner['gear_id'],
        'winner_policy':winner['best_policy']['policy'],
        'old_s_per_mob':result['held_out_frozen_challenger']['seconds_per_mob'],
        'allocation_coverage':result['independent_search']['allocation_coverage'],
        'budgets':result['budgets']},indent=2))

"""Run source-backed supported-talent subset search; never certify checkpoint optimum."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_subset_search import search_executable_talent_subspace


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--class-key',required=True)
    parser.add_argument('--level',type=int,required=True)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--bonus-talent-points',type=int,default=0)
    parser.add_argument('--max-enumerations',type=int,default=100000)
    parser.add_argument('--max-policies',type=int,default=4)
    parser.add_argument('--max-wall-s',type=float,default=30.)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    ir=build_game_ir_slice(class_key=args.class_key,level=args.level,ability_db_path=args.database)
    result=search_executable_talent_subspace(ir=ir,level=args.level,
        bonus_talent_points=args.bonus_talent_points,max_enumerations=args.max_enumerations,
        max_policies=args.max_policies,max_wall_s=args.max_wall_s)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print('attempted',result['attempted_runs'],'/',result['expected_100mob_runs'],
          'fully_evaluated',result['complete_supported_subspace_evaluated'],
          'wall',round(result['wall_s'],2),'winner',result['winner'])

if __name__=='__main__':main()

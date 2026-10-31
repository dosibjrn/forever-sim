"""Reproducible generic talent × gear × APL × recovery 100mob experiment."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (search_bounded_joint_frontier,
    source_gear_seed_stage)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--class-key',required=True)
    p.add_argument('--level',type=int,required=True)
    p.add_argument('--talent-database',type=Path,required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--stage',type=Path)
    group.add_argument('--gear-evidence',type=Path)
    p.add_argument('--talented',action=argparse.BooleanOptionalAction,default=True)
    p.add_argument('--max-talents',type=int,default=2)
    p.add_argument('--max-gear-moves',type=int,default=1)
    p.add_argument('--max-policies',type=int,default=2)
    p.add_argument('--max-recovery-policies',type=int,default=2)
    p.add_argument('--max-paid-builds',type=int,default=12)
    p.add_argument('--max-wall-s',type=float,default=50.)
    p.add_argument('--per-candidate-wall-s',type=float,default=5.)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    ir=build_game_ir_slice(class_key=args.class_key,level=args.level,
        ability_db_path=args.talent_database)
    if ir is None:raise SystemExit('BLOCKED_NO_EXECUTABLE_SOURCE_IR')
    if args.stage:
        stage=json.loads(args.stage.read_text())
    else:
        evidence=json.loads(args.gear_evidence.read_text())
        gear=evidence['baseline']['gear']
        stage=source_gear_seed_stage(gear=gear,ir=ir,source_evidence=str(args.gear_evidence))
    result=search_bounded_joint_frontier(class_key=args.class_key,level=args.level,
        source_ir=ir,seed_stage=stage,max_talents=args.max_talents,
        bonus_talent_points=None if args.talented else 0,
        max_gear_moves=args.max_gear_moves,max_policies=args.max_policies,
        max_recovery_policies=args.max_recovery_policies,max_paid_builds=args.max_paid_builds,
        max_cpu_s=args.max_wall_s,per_candidate_wall_s=args.per_candidate_wall_s)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print('status',result['status'],'paid',result['paid_candidates'],
          'complete',result['complete_100mob_candidates'],
          'wall',round(result['wall_s'],2),'winner',result['winner'])

if __name__=='__main__':main()

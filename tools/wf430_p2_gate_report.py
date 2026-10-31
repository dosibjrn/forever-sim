"""Current immutable-source P2 gate result; RED exits nonzero in strict mode."""
import argparse
import json
from pathlib import Path

from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from src.game.data.forever.registry import build_game_ir_slice

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',default='druid')
    p.add_argument('--level',type=int,default=30)
    p.add_argument('--bonus-points',type=int,default=5)
    p.add_argument('--source-db',type=Path,default=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    p.add_argument('--source-build',default='1.60.1.70338')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--strict',action='store_true')
    a=p.parse_args()
    ir=build_game_ir_slice(class_key=a.class_key,level=a.level,ability_db_path=a.source_db)
    if ir is None:raise ValueError('P2_SOURCE_IR_MISSING')
    r=audit_checkpoint_p2_executor(ir,db_path=a.source_db,
        checkpoint=P2Checkpoint(a.class_key,a.level,source_build=a.source_build),
        bonus_talent_points=a.bonus_points)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print({k:r[k] for k in ('status','available_points','reachable_rank_count',
      'unreachable_rank_count','reachable_without_executor','unresolved_reachability_count')})
    if a.strict and not r['green']:raise SystemExit(1)
if __name__=='__main__':main()

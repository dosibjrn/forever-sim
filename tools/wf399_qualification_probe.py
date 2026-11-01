"""Reproducible source-IR 2D joint search with optional paid survival qualification."""
import argparse,json,time
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier

p=argparse.ArgumentParser()
p.add_argument('--budget',type=float,required=True)
p.add_argument('--max-paid',type=int,required=True)
p.add_argument('--qualification',type=int,default=0)
p.add_argument('--max-qualifiers',type=int,default=16)
p.add_argument('--finalists',type=int,default=4)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
ir=build_game_ir_slice(class_key='druid',level=30,
    ability_db_path=root/'data/forever/staged_druid_l30_talents_70338.sqlite')
stage=json.loads((root/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
stage['allocation']={'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'feral_instinct':1}
t=time.monotonic()
r=search_bounded_joint_frontier(class_key='druid',level=30,source_ir=ir,
    seed_stage=stage,max_talents=128,max_gear_moves=12,max_policies=16,
    max_recovery_policies=3,max_paid_builds=a.max_paid,
    max_cpu_s=a.budget,per_candidate_wall_s=25.,
    screen_then_finalists=True,max_finalists=a.finalists,
    pack_size=2,qualification_mobs=a.qualification or None,
    max_qualifiers=a.max_qualifiers)
r['outer_wall_s']=time.monotonic()-t
r['run_parameters']=vars(a)|{'output':str(a.output)}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(r,indent=2,default=str)+'\n')
print(json.dumps({k:r.get(k) for k in ('status','wall_s','outer_wall_s','paid_candidates','unique_full_builds','screen_complete_candidates','qualification_complete_candidates','complete_100mob_candidates','events')})+'\nWINNER '+str(r['winner']['seconds_per_mob'] if r['winner'] else None),flush=True)

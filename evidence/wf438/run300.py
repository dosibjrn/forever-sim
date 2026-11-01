import json,time,hashlib
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import source_cold_start_stage,search_bounded_joint_frontier,replay_joint_shortlist_100mob
root=Path(__file__).resolve().parents[1]/'wf438_tree';db=root/'data/forever/staged_druid_l30_talents_70338.sqlite'
ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
args=dict(class_key='druid',level=30,source_ir=ir,seed_stage=stage,bonus_talent_points=5,
 max_talents=128,max_gear_moves=16,max_policies=8,max_recovery_policies=3,
 max_paid_builds=50000,max_cpu_s=300.,screen_mobs=2,finalist_mobs=100,
 per_candidate_wall_s=1.,search_only=True,screen_evaluator_backend='direct',
 refinement_top_n=12,refinement_rounds=3,refinement_stat_axes=('spell_power','strength','agility','intellect','spirit','stamina'),
 refinement_probe_delta=20.,refinement_gear_candidates=5,refinement_policy_candidates=5,
 screen_budget_fraction=.75,pack_size=2)
print('START 300',flush=True);t=time.monotonic();r=search_bounded_joint_frontier(**args)
print('SEARCH',r['wall_s'],r['paid_candidates'],r['unique_full_builds'],r['backfill_screen_candidates'],r['events'],flush=True)
v=replay_joint_shortlist_100mob(r,source_ir=ir,seed_stage=stage,class_key='druid',level=30,bonus_talent_points=5,pack_size=2,max_per_candidate_wall_s=45.) if r['validation_shortlist'] else None
print('VALIDATE',v['status'] if v else None,[(x['status'],x['full_s_per_mob']) for x in v['rows']] if v else [],flush=True)
s={k:val for k,val in r.items() if k not in ('rows','validation_shortlist','baseline_results','refinement','talent_frontier','p4_talent_unlock_coverage')}
s['refinement']={k:val for k,val in r['refinement'].items() if k!='rows'}
s['validation']=v;s['source_sha256']=hashlib.sha256(db.read_bytes()).hexdigest()
s['params']={k:val for k,val in args.items() if k not in ('source_ir','seed_stage')}
s['shortlist']=[{k:x.get(k) for k in ('allocation','gear_move','policy','recovery','screen_s_per_mob','refinement_round')} for x in r['validation_shortlist']]
(root.parent/'wf438_outputs/WF438_300S.json').write_text(json.dumps(s,indent=2,default=str))
print('DONE',time.monotonic()-t,flush=True)

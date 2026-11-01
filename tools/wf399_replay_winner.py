"""Independently reconstruct and replay a frozen WF399 source 2D 100mob winner."""
import argparse,json
from dataclasses import replace
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.policy_evolution import _identity as policy_identity, _validated as validate_policy
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_persistent_slot_search import _source_slot_proposals,_source_weapon_package_proposals
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.v2.source_bounded_joint_frontier import (source_joint_policy_frontier,
    _recovery_variants,isolated_joint_evaluation)

p=argparse.ArgumentParser();p.add_argument('search_result',type=Path)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
record=json.loads(a.search_result.read_text());w=record['winner']
if not w or w['status']!='COMPLETE' or w['mobs']!=100:
    raise SystemExit('NO_FROZEN_COMPLETE_100MOB_WINNER')
ir=build_game_ir_slice(class_key='druid',level=30,
    ability_db_path=root/'data/forever/staged_druid_l30_talents_70338.sqlite')
compiled,_=compile_talent_runtime(ir)
stage=json.loads((root/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
stage['allocation']={'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'feral_instinct':1}
base=stage['gear_policy_result']['winner']['gear']
slots,_=_source_slot_proposals(class_key='druid',level=30,base=base,per_slot=2,max_proposals=12)
packs,_=_source_weapon_package_proposals(class_key='druid',level=30,base=base,max_packages=max(0,12-len(slots)))
gear_stages={'incumbent':stage}
for slot,item in slots:
    try:gear_stages[f'{slot}:{item.item_id}']=substituted_multi_stage(
        stage=stage,class_key='druid',level=30,swaps={slot:int(item.item_id)})
    except (ValueError,KeyError):pass
for swaps in packs:
    try:gear_stages['package:'+repr(sorted(swaps.items()))]=substituted_multi_stage(
        stage=stage,class_key='druid',level=30,swaps=swaps)
    except (ValueError,KeyError):pass
candidate=prepare_candidate(class_key='druid',level=30,stage=gear_stages[w['gear_move']],
    allocation_override=w['allocation'],source_ir=compiled,allow_partial_gear_stats=True)
if w['policy']!='incumbent':
    policies=source_joint_policy_frontier(compiled,stage,max_policies=16,include_mode_cycles=True)
    matches=[pol for label,pol in policies if label==w['policy']
             and policy_identity(pol)==w['policy_signature']]
    if len(matches)!=1:raise SystemExit('POLICY_IDENTITY_NOT_UNIQUE')
    validate_policy(matches[0],candidate.ir.actions)
    candidate=replace(candidate,policy=matches[0])
if policy_identity(candidate.policy)!=w['policy_signature']:
    raise SystemExit('FROZEN_POLICY_MISMATCH')
recovery=dict(_recovery_variants(compiled,stage,max_recovery_policies=3))[w['recovery']]
r=isolated_joint_evaluation(candidate,level=30,mobs=100,recovery_policy=recovery,
    pack_size=2,timeout_s=55.)
r['expected_mean_s_per_mob']=w['seconds_per_mob']
r['expected_events']=w['full_events']
r['match']=(r['status']=='COMPLETE' and r['events']==w['full_events']
            and abs(r['mean_s_per_mob']-w['seconds_per_mob'])<1e-9)
r['winner_identity']={k:w[k] for k in ('allocation','gear_move','policy','policy_signature','recovery')}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({k:r.get(k) for k in ('status','mean_s_per_mob','events','match','outer_wall_s')}))
if not r['match']:raise SystemExit(2)

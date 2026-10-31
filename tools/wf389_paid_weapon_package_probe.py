"""WF389 bounded diagnostic: source gear-package proposals -> existing paid 100mob."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic,process_time

from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from src.v2 import source_persistent_slot_search as search


def run(*,stage_path:Path,class_key:str,level:int,output:Path,
        max_proposals:int=10,package_budget:int=5,max_cpu_s:float=75.) -> dict:
    stage_bytes=stage_path.read_bytes()
    stage=json.loads(stage_bytes)
    cert=checkpoint_item_l0(class_key=class_key,level=level)
    real=search.evaluate_persistent_candidate
    attempts=[]
    t0=monotonic();c0=process_time()
    def traced(candidate,*,level,mobs,**kwargs):
        gear=candidate.source_stage['gear_policy_result']['winner']['gear']
        before=monotonic();cpu=process_time()
        result=real(candidate,level=level,mobs=mobs,**kwargs)
        attempts.append({'mobs':mobs,'gear_item_ids':{k:int(v['item_id']) for k,v in gear['slots'].items()},
            'weapon_hands':int(gear['slots']['weapon']['weapon_hands']),
            'offhand':int(gear['slots']['offhand']['item_id']) if 'offhand' in gear['slots'] else None,
            'status':result.get('status'),'mob_completed':result.get('mob_completed',result.get('count')),
            'mean_s_per_mob':result.get('mean_s_per_mob'),
            'events':result.get('events'),'wall_s':monotonic()-before,'cpu_s':process_time()-cpu})
        return result
    search.evaluate_persistent_candidate=traced
    try:
        result=search.search_persistent_gear_slots(class_key=class_key,level=level,seed_stage=stage,
            rounds=1,per_slot=2,max_proposals_per_round=max_proposals,
            max_weapon_packages_per_round=package_budget,screen_mobs=4,
            finalist_mobs=100,max_finalists=max_proposals,max_cpu_s=max_cpu_s,
            max_events=200000,p3_certificate=cert,allow_unattested_diagnostic=True,
            allow_partial_gear_stats=True)
    finally:
        search.evaluate_persistent_candidate=real
    out={'status':result['status'],'class_key':class_key,'level':level,
         'stage_sha256':hashlib.sha256(stage_bytes).hexdigest(),
         'source_membership_verified':cert['source_membership_verified'],
         'p3_pass':cert['p3_pass'],'p3_l0_assessed':cert['l0_assessed_count'],
         'p3_source_items':cert['legal_item_count'],
         'rounds':result.get('rounds',[]),'search_attempts':result.get('attempts'),
         'unique_full_builds':result.get('unique_full_builds'),
         'unique_full_100mob_builds':result.get('unique_full_100mob_builds'),
         'weapon_package_attempts':result.get('weapon_package_attempts'),
         'weapon_package_full_100mob':result.get('weapon_package_full_100mob'),
         'full_100mob_evaluations':result.get('full_100mob_evaluations'),
         'search_events':result.get('events'),'search_wall_s':result.get('wall_s'),
         'search_cpu_s':result.get('cpu_s'),'total_wall_s':monotonic()-t0,
         'total_cpu_s':process_time()-c0,
         'winner_s_per_mob':result.get('winner',{}).get('mean_s_per_mob'),
         'baseline_s_per_mob':result.get('initial',{}).get('mean_s_per_mob'),
         'evaluations':attempts,'diagnostic_only':True,
         'formal_checkpoint_accepted':False,
         'held_out_druid_l30_s_per_mob':16.2876,
         'spatial_mode':'sequential_zero_spacing_not_2d_simultaneous_pack',
         'independent_joint_30_300_run':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,indent=2,sort_keys=True))
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--class-key',required=True)
    parser.add_argument('--level',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-proposals',type=int,default=10)
    parser.add_argument('--package-budget',type=int,default=5)
    parser.add_argument('--max-cpu-s',type=float,default=75.)
    args=parser.parse_args()
    out=run(stage_path=args.stage,class_key=args.class_key,level=args.level,
            output=args.output,max_proposals=args.max_proposals,
            package_budget=args.package_budget,max_cpu_s=args.max_cpu_s)
    print(json.dumps({k:v for k,v in out.items() if k!='evaluations'},indent=2))

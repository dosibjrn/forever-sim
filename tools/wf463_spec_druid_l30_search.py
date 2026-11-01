"""Cold spec-constrained Forever GameIR gear×talents×APL search + external 100mob.

Source-neutral parameters: a talent tree, minimum points and optional
combat form. This is NOT a manually seeded Druid/feral rotation.
"""
import argparse
import hashlib
import json
from pathlib import Path
from dataclasses import asdict, is_dataclass
from wf_gate_engine_fingerprint import runtime_fingerprint
from time import monotonic

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (
    source_cold_start_stage, search_bounded_joint_frontier,
    replay_joint_shortlist_100mob,
)




def source_scenario(source_ir, report, *, class_key, level, bonus_points):
    def serializable(obj):
        if is_dataclass(obj):return asdict(obj)
        if isinstance(obj,(list,tuple)):return [serializable(x) for x in obj]
        if isinstance(obj,dict):return {str(k):serializable(v) for k,v in obj.items()}
        return obj if isinstance(obj,(str,int,float,bool,type(None))) else repr(obj)
    payload={'class':class_key,'level':level,
             'enemy':report['enemy'], 'pack_size':report['pack_size'],
             'bonus_talent_points':bonus_points,
             'incoming_attacks':serializable(source_ir.incoming_attacks),
             'mitigation_rules':serializable(source_ir.mitigation_rules),
             '100mob_replay':True,'recovery_paid':True}
    identity=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()
    return identity,payload


def execute(*, db_path, class_key, level, tree, minimum_points, mode,
            gear_role, bonus_points, budget, output, max_candidates=None):
    source_ir=build_game_ir_slice(class_key=class_key,level=level,
                                 ability_db_path=db_path)
    stage=source_cold_start_stage(class_key=class_key,level=level,
        source_ir=source_ir,gear_role=gear_role)
    t=monotonic()
    r=search_bounded_joint_frontier(class_key=class_key,level=level,
        source_ir=source_ir,seed_stage=stage,
        bonus_talent_points=bonus_points,max_talents=80,max_gear_moves=8,
        max_policies=5,max_recovery_policies=2,
        max_paid_builds=max_candidates or (1000 if budget==30 else 10000),
        max_cpu_s=budget,per_candidate_wall_s=1.,
        screen_mobs=2,finalist_mobs=100,search_only=True,
        screen_evaluator_backend='direct',pack_size=2,
        refinement_top_n=4 if budget==30 else 12,
        refinement_rounds=1 if budget==30 else 3,
        refinement_stat_axes=('strength','agility','stamina','intellect',
            'spirit','spell_power'),refinement_probe_delta=20.,
        refinement_gear_candidates=3 if budget==30 else 5,
        refinement_policy_candidates=3 if budget==30 else 5,
        refinement_talent_neighbors=4 if budget==30 else 8,
        spec_tree=tree,min_spec_points=minimum_points,
        required_combat_mode=mode)
    engine_id=runtime_fingerprint(Path(__file__).resolve().parent.parent)
    scenario_id,scenario_payload=source_scenario(source_ir,r,class_key=class_key,level=level,bonus_points=bonus_points)
    print('SEARCH',tree,budget,'wall',r['wall_s'],'unique',r['unique_full_builds'],
          'screen',r['screen_complete_candidates'],'frontier',r['talent_allocations_proposed'],
          'winner',(r['search_winner'] or {}).get('screen_s_per_mob'),flush=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    def summarize(validation=None):
        return {'schema':'wf463_spec_100mob_v1','checkpoint':f'{class_key}:L{level}:{tree}',
            'source_db':str(db_path),'source_sha256':hashlib.sha256(db_path.read_bytes()).hexdigest(),
            'engine_id':engine_id,'scenario_id':scenario_id,'scenario_payload':scenario_payload,
            'spec_constraint':r['spec_constraint'],'gear_role':gear_role,
            'bonus_talent_points':bonus_points,'search_budget':budget,
            'search_wall_s':r['wall_s'],'search_full_runner_wall_s':monotonic()-t,
            'paid_attempts':r['paid_candidates'],'unique':r['unique_full_builds'],
            'screen_complete':r['screen_complete_candidates'],'events':r['events'],
            'unlock_coverage_pass':r['p4_talent_unlock_coverage_pass'],
            'unlock_coverage':r['p4_talent_unlock_coverage'],
            'talent_frontier':r['talent_frontier'],
            'joint_axis_paid_coverage':r['joint_axis_paid_coverage'],
            'refinement':{k:v for k,v in r['refinement'].items() if k!='rows'},
            'shortlist':r['validation_shortlist'],
            'validation':validation or {'status':'PENDING_OUTSIDE_SEARCH_BUDGET'},
            'accepted_checkpoints':0}
    output.write_text(json.dumps(summarize(),ensure_ascii=False,indent=2,default=str)+'\n')
    rv=(replay_joint_shortlist_100mob(r,source_ir=source_ir,seed_stage=stage,
        class_key=class_key,level=level,bonus_talent_points=bonus_points,
        pack_size=2,max_per_candidate_wall_s=35.)
        if r['validation_shortlist'] else {'status':'NO_VALIDATION_SHORTLIST'})
    output.write_text(json.dumps(summarize(rv),ensure_ascii=False,indent=2,default=str)+'\n')
    print('VALIDATION',tree,budget,rv['status'],'completed',rv.get('complete_100mob_replays'),
          'rows',[(x.get('full_s_per_mob'),x.get('status')) for x in rv.get('rows',[])],
          'file',output,flush=True)
    return summarize(rv)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=Path('data/forever/staged_druid_l30_talents_70338.sqlite'))
    p.add_argument('--class-key',default='druid')
    p.add_argument('--level',type=int,default=30)
    p.add_argument('--tree',required=True)
    p.add_argument('--min-points',type=int,default=21)
    p.add_argument('--combat-mode')
    p.add_argument('--gear-role',required=True)
    p.add_argument('--bonus-points',type=int,default=5)
    p.add_argument('--budget',type=int,choices=(30,300),required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    execute(db_path=a.db,class_key=a.class_key,level=a.level,
        tree=a.tree,minimum_points=a.min_points,mode=a.combat_mode,
        gear_role=a.gear_role,bonus_points=a.bonus_points,
        budget=a.budget,output=a.output)

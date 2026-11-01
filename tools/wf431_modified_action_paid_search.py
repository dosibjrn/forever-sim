"""WF431 reproducible source-modified-action paid 30s and 100mob evidence."""
from __future__ import annotations
from pathlib import Path
from time import perf_counter, process_time
from dataclasses import replace
import hashlib, json

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.v2.source_bounded_joint_frontier import (
    source_cold_start_stage, search_bounded_joint_frontier,
    bounded_full_point_talent_frontier, source_joint_policy_frontier,
    _source_talent_policy_variants, _prepare_joint_policy_candidate,
    _source_stat_package_proposals,
)
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def run(strategy):
    wall=perf_counter(); cpu=process_time()
    ir,coverage=compile_talent_runtime(build_game_ir_slice(
        class_key='druid',level=30,ability_db_path=DB))
    stage=source_cold_start_stage(class_key='druid',level=30,
        source_ir=ir,gear_role='druid_feral')
    talents,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=64)
    policies=source_joint_policy_frontier(ir,stage,max_policies=4,include_mode_cycles=True)
    variants,_,_=_source_talent_policy_variants(ir,talents,stage,policies,
        level=30,bonus_talent_points=5)
    index=next(i for i,a in enumerate(talents) if a.get('improved_starfire')==5)
    label,policy=next((label,p) for label,p in variants[index]
        if label.startswith('talent_modified:improved_starfire:'))
    action_id=label.split(':',2)[2]
    out={'parent':'WF430','source_build':'1.60.1.70338',
         'source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
         'talented_points':26,'rank_missing_executor':coverage['rank_missing_executor'],
         'enemy_authority':'CMANGOS_CLASSIC_PROXY_NOT_VERIFIED_FOREVER_NPC',
         'witness':{'talent_index':index,'label':label,'action_id':action_id,
                    'allocation':talents[index]},'searches':{}}
    for strategy in (strategy,):
        r=search_bounded_joint_frontier(class_key='druid',level=30,
            source_ir=ir,seed_stage=stage,bonus_talent_points=5,
            max_talents=64,max_gear_moves=8,max_policies=4,
            max_recovery_policies=2,max_paid_builds=1000,max_cpu_s=30.,
            per_candidate_wall_s=3.,screen_then_finalists=True,
            max_finalists=4,screen_mobs=4,finalist_mobs=100,
            proposal_strategy=strategy)
        witness=[row for row in r['rows'] if row['allocation'].get('improved_starfire')==5
                 and row['policy_origin']==label]
        out['searches'][strategy]={
            k:r.get(k) for k in ('status','wall_s','parent_cpu_s','worker_cpu_s_reported',
                'events','paid_candidates','unique_full_builds','screen_complete_candidates',
                'complete_100mob_candidates','full_evaluated_candidates',
                'screen_phase_wall_s','finalist_phase_wall_s','proposal_strategy')}
        out['searches'][strategy].update(
            source_modified_witness_paid_attempts=len(witness),
            source_modified_witness_completed_screens=sum(
                row.get('screen_status')=='COMPLETE' and
                int(row.get('source_action_counts',{}).get(action_id,0))>0 for row in witness),
            source_modified_witness_casts=sum(int(row.get('source_action_counts',{}).get(action_id,0))
                for row in witness),
            source_modified_witness_first_attempt=(next((i+1 for i,row in enumerate(r['rows'])
                if row['allocation'].get('improved_starfire')==5
                and row['policy_origin']==label),None)),
            winner=({k:r['winner'].get(k) for k in ('seconds_per_mob','screen_s_per_mob',
                'policy_origin','gear_move','full_events','mobs')}
                if r['winner'] else None),
            witness_rows=[{k:row.get(k) for k in ('policy_origin','gear_move','screen_status',
                'screen_s_per_mob','source_action_counts','status','seconds_per_mob')}
                for row in witness[:6]])
    packages=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    spell_stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,
        swaps=packages['spell_power'])
    candidate=_prepare_joint_policy_candidate(class_key='druid',level=30,
        stage=spell_stage,allocation=talents[index],source_ir=ir,
        allow_partial_gear_stats=True,policy_label=label,policy=policy,
        bonus_talent_points=5)
    samples=[]
    for _ in range(2):
        r=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            max_total_events=250000,max_wall_s=30,max_cpu_s=30)
        samples.append({k:r.get(k) for k in ('status','count','mean_s_per_mob','events',
            'elapsed_wall_s','elapsed_cpu_s','source_action_counts',
            'source_control_proc_attempts','source_control_proc_triggered')})
    assert all(r['status']=='COMPLETE' and r['count']==100 for r in samples)
    assert samples[0]['mean_s_per_mob']==samples[1]['mean_s_per_mob']
    assert all(r['source_action_counts'].get(action_id,0)>0 for r in samples)
    out['independent_100mob_spell_power_witness']=samples
    out['overall_wall_s']=perf_counter()-wall
    out['overall_parent_cpu_s']=process_time()-cpu
    return out


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--strategy',choices=('diagonal','marginal_screen'),required=True)
    args=parser.parse_args()
    report=run(args.strategy)
    path=ROOT/f'evidence/wf431/WF431_PAID_SOURCE_MODIFIED_APL_{args.strategy.upper()}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))

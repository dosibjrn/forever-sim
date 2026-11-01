"""WF430: real sourced Improved Starfire 100mob CombatRuntime witness.

The shared target is still a Classic proxy, not a verified Forever NPC.
Control procs are deterministic seeded Bernoulli samples, not expected-value
stun durations or a claim about the real game's RNG distribution.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from time import perf_counter,process_time
import hashlib,json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.v2.source_bounded_joint_frontier import (source_cold_start_stage,
    _source_stat_package_proposals,_recovery_variants)
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.game.model import PolicyDefinition,PolicyRuleDefinition

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
BASE={'genesis':5,'improved_wrath':5,'improved_moonfire':2,
      'natures_majesty':2,'moonglow':3,'natures_reach':2,
      'natures_splendor':1,'insect_swarm':1,'ferocity':5}
STARFIRE={**{k:v for k,v in BASE.items() if k!='ferocity'},'improved_starfire':5}

def run():
    wall=perf_counter();cpu=process_time()
    ir,coverage=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
    packages=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=packages['spell_power'])
    recovery=dict(_recovery_variants(ir,stage,2))['always']
    out={'parent':'WF429','source_build':'1.60.1.70338',
         'source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
         'rank_missing_executor':coverage['rank_missing_executor'],
         'scenario':'CMANGOS_LEVEL_CLASS_HP_PROXY_NOT_NAMED_FOREVER_NPC',
         'gear_source':'canonical_sqlite_legal_spell_power_package',
         'control_proc_resolution':'sha256_event_key_deterministic_Bernoulli_one_seed',
         'talented_enabled':True,'talent_points':26,'results':{}}
    for label,allocation in [('without_improved_starfire',BASE),('improved_starfire5',STARFIRE)]:
        candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
            allocation_override=allocation,source_ir=ir,allow_partial_gear_stats=True,
            bonus_talent_points=5)
        action=next(a for a in candidate.ir.actions if a.family_key=='starfire')
        policy=PolicyDefinition('starfire_only','Source Starfire-only mechanics witness',
            rules=(PolicyRuleDefinition('cast_starfire',action.id),),
            provenance={'authority':'source_ir_mechanics_witness'})
        candidate=replace(candidate,policy=policy,opening=())
        samples=[]
        for _ in range(2):
            r=evaluate_persistent_candidate(candidate,level=30,mobs=100,
                max_total_events=250000,max_wall_s=30,max_cpu_s=30,recovery_policy=recovery)
            samples.append({k:r.get(k) for k in ('status','count','mean_s_per_mob','events',
                'elapsed_wall_s','elapsed_cpu_s','combat_s','recovery_s',
                'source_action_counts','source_control_proc_attempts','source_control_proc_triggered')})
        assert all(r['status']=='COMPLETE' and r['count']==100 for r in samples)
        assert samples[0]['mean_s_per_mob']==samples[1]['mean_s_per_mob']
        assert samples[0]['source_control_proc_triggered']==samples[1]['source_control_proc_triggered']
        concurrent=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            pack_size=2,max_total_events=250000,max_wall_s=30,max_cpu_s=30,
            recovery_policy=recovery)
        assert concurrent['status']=='COMPLETE' and concurrent['count']==100
        out['results'][label]={'allocation':allocation,'action_id':action.id,
            'cast_time_s':action.cast_time_s,'runs':samples,
            'concurrent_2d_100mob':{k:concurrent.get(k) for k in (
                'status','count','mean_s_per_mob','events','elapsed_wall_s',
                'elapsed_cpu_s','spatial_mode','incoming_attacks_scheduled')}}
    a=out['results']['without_improved_starfire']['runs'][0]['mean_s_per_mob']
    b=out['results']['improved_starfire5']['runs'][0]['mean_s_per_mob']
    out['improvement_percent']=100*(a-b)/a
    out['wall_s']=perf_counter()-wall;out['cpu_s']=process_time()-cpu
    return out

if __name__=='__main__':
    report=run()
    path=ROOT/'evidence/wf430/WF430_STARFIRE_100MOB.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2,sort_keys=True))

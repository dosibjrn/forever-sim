"""Independent source-staged L30 paid cast pushback sensitivity diagnostic.

The Forever server base pushback is NOT verified, so 0.5s from later-era
WoW mechanics is an explicitly labeled illustrative proxy scenario. Same exact
gear, 26 points, action policy, actor and enemy attack timing before/after.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from time import perf_counter
import json,hashlib
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    source_cold_start_stage,_source_stat_package_proposals,
    source_talent_unlock_witnesses,_prepare_joint_policy_candidate,_recovery_variants)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
BASE={'genesis':5,'improved_entangling_roots':3,'improved_moonfire':2,
 'improved_wrath':5,'insect_swarm':1,'moonglow':3,'natures_majesty':2,
 'natures_reach':2,'natures_splendor':1,'vengeance':2}
GUARDED={**{k:v for k,v in BASE.items() if k not in ('improved_entangling_roots','natures_reach')},'natures_focus':5}
PROXY={'cast_pushback_on_hit_s':.5,
       'cast_pushback_source_url':'https://warcraft.wiki.gg/wiki/Pushback'}

def run():
    start=perf_counter()
    compiled,coverage=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=compiled,gear_role='druid_feral')
    packages=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=packages['spell_power'])
    rec=dict(_recovery_variants(compiled,stage,2))['always']
    out={'kind':'SOURCED_TALENT_CONDITIONAL_PROXY_BASE_PUSHBACK_100MOB',
        'source_build':'1.60.1.70338','source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'ruleset_armor_spell_source':'WF428','level':30,'talented_bonus':5,
        'source_pushback_baseline_status':'NOT_VERIFIED_ON_FOREVER',
        'illustrative_unverified_pushback_s_on_landed_hit':.5,
        'incoming_profile_url':PROXY['cast_pushback_source_url'],
        'talent_source_url':'https://wowforevertalents.com/druid/talents/nature-s-focus/',
        'talent_missing_executor_after':coverage['rank_missing_executor'],'rows':[]}
    for name,allocation in [('control_26pt',BASE),('natures_focus5_26pt',GUARDED)]:
        assert sum(allocation.values())==26
        selected,_=apply_talent_selection(compiled,allocation,level=30,bonus_talent_points=5)
        unlock=next(w for w in source_talent_unlock_witnesses(compiled,selected,stage)
                    if w['action_id'].startswith('insect_swarm:'))
        cand=_prepare_joint_policy_candidate(class_key='druid',level=30,stage=stage,
                    allocation=allocation,source_ir=compiled,allow_partial_gear_stats=True,
                    policy_label='talent_unlock:'+unlock['action_id'],policy=unlock['policy'],
                    bonus_talent_points=5)
        for profile in ('no_sourced_pushback','illustrative_later_wow_0.5s_on_hit'):
            ir=cand.ir
            if profile!='no_sourced_pushback':
                ir=replace(ir,incoming_attacks=tuple(replace(a,metadata={**a.metadata,**PROXY})
                          for a in ir.incoming_attacks))
            c=replace(cand,ir=ir)
            result=evaluate_persistent_candidate(c,level=30,mobs=100,
                max_total_events=250000,max_wall_s=25,max_cpu_s=25,
                recovery_policy=rec)
            row={'name':name,'profile':profile,'allocation':allocation,
                 'status':result.get('status'),'mobs':result.get('count'),
                 's_per_mob':result.get('mean_s_per_mob'),'events':result.get('events'),
                 'source_action_counts':result.get('source_action_counts'),
                 'elapsed_wall_s':result.get('elapsed_wall_s')}
            out['rows'].append(row)
            print(row,flush=True)
    out['total_wall_s']=perf_counter()-start
    assert all(r['status']=='COMPLETE' and r['mobs']==100 for r in out['rows'])
    return out

if __name__=='__main__':
    output=run()
    path=ROOT/'evidence/wf429/WF429_L30_26PT_PUSHBACK_100MOB.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print('RESULT_PATH',path)

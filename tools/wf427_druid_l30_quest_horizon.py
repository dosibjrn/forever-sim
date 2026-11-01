"""Paid quest-horizon replay of independently discovered L30 WF426 finalists.

No hardcoded damage, class balance, talent spell IDs, or gear. Reconstruct
fully specified winners from published evidence and canonical source stages.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.policy_evolution import _identity as policy_identity
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    source_cold_start_stage,_source_stat_package_proposals,
    source_talent_unlock_witnesses,_source_conditional_aura_policy_witnesses,
    _recovery_variants,_prepare_joint_policy_candidate)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
HORIZONS=(2,4,8,16)

def prepared_rows(winner_json:Path):
    previous=json.loads(winner_json.read_text())
    source=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    compiled,_=compile_talent_runtime(source)
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=source,gear_role='druid_feral')
    packs,_=_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)
    gear_stages={'source_stat_package:'+axis:substituted_multi_stage(
        stage=stage,class_key='druid',level=30,swaps=swaps) for axis,swaps in packs}
    gear_stages['incumbent']=stage
    recoveries=dict(_recovery_variants(compiled,stage,2))
    for row in previous['rows']:
        if row.get('mobs')!=100 or row.get('status')!='COMPLETE':continue
        label=row['policy']
        if not (label.startswith('talent_unlock:') or label.startswith('talent_condition:')):continue
        allocation=row['allocation']
        selected,_=apply_talent_selection(compiled,allocation,level=30,bonus_talent_points=5)
        if label.startswith('talent_unlock:'):
            policies={w['action_id']:w['policy'] for w in
                source_talent_unlock_witnesses(compiled,selected,stage)}
            policy=policies[label[len('talent_unlock:'):]]
        else:
            policy=dict(_source_conditional_aura_policy_witnesses(selected))[label]
        cand=_prepare_joint_policy_candidate(class_key='druid',level=30,
            stage=gear_stages[row['gear_move']],allocation=allocation,
            source_ir=compiled,allow_partial_gear_stats=True,
            policy_label=label,policy=policy,bonus_talent_points=5)
        assert policy_identity(cand.policy)==row['policy_signature']
        yield label,row,cand,recoveries

def run(winner_json:Path,*,validate_100=True):
    out={'release':'WF427','parent':'WF426','source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
         'talented_bonus_points':5,'level':30,'horizons':HORIZONS,
         'mode':'quest_end_at_final_kill_no_settlement_no_100mob_P4_gate',
         'encounter':'CMaNGOS Classic proxy, not Forever Yeti','builds':[]}
    for label,row,candidate,recoveries in prepared_rows(winner_json):
        record={'policy':label,'allocation':row['allocation'],
                'gear_move':row['gear_move'],'original_100mob_paid_full_recovery_s_per_mob':row['seconds_per_mob'],
                'recovery_choices':{}}
        for recovery_name,rec_policy in recoveries.items():
            seq={}; last=None
            for n in (*HORIZONS, *((100,) if validate_100 else ())):
                r=evaluate_persistent_candidate(candidate,level=30,mobs=n,
                    max_total_events=200000,max_wall_s=20,max_cpu_s=20,
                    recovery_policy=rec_policy,settle_final_recovery=False,trace_pulls=True)
                if r['status']!='COMPLETE' or len(r['pull_trace'])!=n:
                    seq[str(n)]={'status':r['status'],'reason':r.get('reason'),
                                 'mob_completed':r.get('mob_completed')};continue
                water=[{'after_mob':p['mob'],'water_s':round(p['water_s'],6),
                        'recovery_s':round(p['recovery_s'],6)}
                       for p in r['pull_trace'] if p['water_s']>1e-8]
                long_cd={}
                for p in r['pull_trace']:
                    for aid,used in p['long_cooldowns_used'].items():
                        long_cd.setdefault(aid,[]).append({'mob':p['mob'],'casts':used})
                seq[str(n)]={'status':'COMPLETE','total_s':r['total_s'],
                    's_per_mob':r['mean_s_per_mob'],'combat_s':r['combat_s'],
                    'recovery_s':r['recovery_s'],'full_recovery_count':sum(p['full_recovery'] for p in r['pull_trace']),
                    'water_s':sum(p['water_s'] for p in r['pull_trace']),
                    'water_breaks':water,'long_cooldown_uses':long_cd,
                    'final_resources':r['final_resources'],
                    'source_action_counts':r['source_action_counts'],
                    'events':r['events'],
                    'per_mob':r['pull_trace'] if n<=16 else None}
                last=r
            if '8' in seq and '16' in seq and all(seq[str(k)].get('status')=='COMPLETE' for k in (8,16)):
                t8=seq['8']['total_s'];t16=seq['16']['total_s'];slope=(t16-t8)/8
                prediction=t16+(100-16)*slope
                drink_mobs=[row['after_mob'] for row in seq['16']['water_breaks']]
                legal_long_cd=set()
                for pull in seq['16']['per_mob']:
                    legal_long_cd.update(pull['long_cooldown_timer_ready_at_pull'])
                seq['100_extrapolation_from_8_16']={
                    'prediction_s':prediction,'method':'last_8_mob_slope',
                    'training_horizon_mobs':16,'water_break_mobs_observed':drink_mobs,
                    'observed_water_gap_count':max(0,len(drink_mobs)-1),
                    'source_long_cooldown_actions_untested_by_policy':sorted(
                        legal_long_cd-set(seq['16']['long_cooldown_uses'])),
                    'confidence':'LOW' if len(drink_mobs)<4 or bool(legal_long_cd) else 'DIAGNOSTIC_ONLY',
                    'warning':'Not an accepted surrogate for 100mob: periodic water/cooldown phases may be absent from 16mob trace.'} 
                if seq.get('100',{}).get('status')=='COMPLETE':
                    real=seq['100']['total_s']
                    seq['100_extrapolation_from_8_16'].update({'actual_s':real,
                        'absolute_error_s':abs(prediction-real),'relative_error_fraction':(prediction-real)/real})
            record['recovery_choices'][recovery_name]=seq
        out['builds'].append(record)
    return out

if __name__=='__main__':
    import sys
    p=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'evidence/wf427/WF427_L30_COLD_FINALISTS.json'
    result=run(p)
    out=ROOT/'evidence/wf427/DRUID_L30_QUEST_HORIZONS_2_4_8_16.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'file':str(out),'builds':[
        {'policy':b['policy'],'recovery_choices':{name:{k:{x:row.get(x) for x in ('status','total_s','water_s','full_recovery_count')}
          for k,row in data.items() if k in ('2','4','8','16','100')}
          for name,data in b['recovery_choices'].items()}}
        for b in result['builds']]},ensure_ascii=False,indent=2))

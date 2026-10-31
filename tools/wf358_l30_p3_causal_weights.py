"""Real 100-mob finite-difference source-stat impacts in the current L30 build.

Unlike item-swap regression, these are controlled interventions on ONE stat
at a time, on the SAME IR/policy/gear/recovery context. Nonlinear thresholds
are recorded, never collapsed into a fabricated globally valid coefficient.
"""
import json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from dataclasses import replace
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_stat_delta,_replace_equipped_weapon_dps,executable_gear_stats
from src.game.data.forever.source_checkpoint_p3_ratings import apply_source_item_stat_delta
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf358'
POLICY=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
STEPS={'strength':(5.,20.),'agility':(20.,40.),'stamina':(5.,20.),
 'intellect':(5.,20.),'spirit':(5.,20.),'attack_power':(10.,30.),
 'spell_power':(10.,30.),'healing':(10.,30.),'mp5':(5.,10.),
 'armor':(100.,200.),'health_regeneration_per_5s':(5.,10.),
 'weapon_dps':(10.,20.),'hit':(1.,2.),'crit':(1.,2.),
 'defense':(1.,4.),'dodge':(1.,2.)}

def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf357/WF357_L30_BEST_P3_STAGE.json').read_text())
 t=monotonic();cpu=process_time();OUT.mkdir(parents=True,exist_ok=True)
 path=OUT/'WF358_L30_CAUSAL_STAT_100MOB.json'
 with tempfile.TemporaryDirectory(prefix='wf358_causal_') as tmp:
  db=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
  ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(db):
   ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
   cand=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
   base=evaluate_persistent_candidate(cand,level=30,mobs=100,max_total_events=200000,
                                      max_wall_s=14.,max_cpu_s=14.,recovery_policy=POLICY)
   if base['status']!='COMPLETE':raise RuntimeError('P3_CAUSAL_BASE_INCOMPLETE:'+str(base))
   previous=json.loads(path.read_text()) if path.exists() else None
   if previous and abs(previous['baseline']['mean_s_per_mob']-base['mean_s_per_mob'])>1e-8:
    raise ValueError('P3_CAUSAL_STALE_BASELINE')
   results=list(previous['results']) if previous else []
   done={(r['stat'],r['delta']) for r in results}
   native=set(executable_gear_stats(cand.ir))
   equipped_weapon=float(stage['gear_policy_result']['winner']['gear']['slots']['weapon']['weapon_dps'])
   for stat,steps in STEPS.items():
    for delta in steps:
     if (stat,delta) in done:continue
     try:
      if stat=='weapon_dps':newir=_replace_equipped_weapon_dps(cand.ir,equipped_weapon+delta)
      elif stat in ('hit','crit','defense','dodge'):
       newir=apply_source_item_stat_delta(cand.ir,stat,delta,level=30)
      elif stat in native:newir=apply_stat_delta(cand.ir,stat,delta)
      else:raise ValueError('NO_SOURCE_EXECUTABLE_STAT_AXIS')
      r=evaluate_persistent_candidate(replace(cand,ir=newir),level=30,mobs=100,
          max_total_events=200000,max_wall_s=14.,max_cpu_s=14.,recovery_policy=POLICY)
      row={'stat':stat,'delta':delta,'status':r['status'],
           's_per_mob':r.get('mean_s_per_mob'),'events':r.get('events'),
           'cpu_s':r.get('elapsed_cpu_s'),'wall_s':r.get('elapsed_wall_s'),
           'mobs':r.get('count'),'source_ir_intervention':True}
      if r['status']=='COMPLETE':
       row['s_saved_per_mob']=base['mean_s_per_mob']-r['mean_s_per_mob']
       row['marginal_s_saved_per_mob_per_raw_unit']=row['s_saved_per_mob']/delta
     except Exception as exc:
      row={'stat':stat,'delta':delta,'status':'UNSUPPORTED_OR_FAILED',
           'reason':type(exc).__name__+':'+str(exc)[:250]}
     results.append(row)
     print('CAUSAL',len(results),stat,delta,row['status'],row.get('s_saved_per_mob'),flush=True)
     path.write_text(json.dumps({'checkpoint':'druid:L30:unrestricted',
      'method':'one_axis_at_a_time_source_ir_100mob_intervention_conditional_recovery',
      'baseline':base,'policy':vars(POLICY),'results':results,
      'completed':sum(r['status']=='COMPLETE' for r in results),
      'attempted':len(results),'wall_s':monotonic()-t,'cpu_s':process_time()-cpu,
      'not_a_global_linear_weight':'Discrete thresholds and fixed build/rotation; do not extrapolate as an exact item score',
      'accepted_checkpoints':'1/148'},indent=2,sort_keys=True,default=str)+'\n')
 return results
if __name__=='__main__':run()

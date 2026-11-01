"""Paid 100-mob replays of cross-slot combinations of independently screened items.

Never extrapolate independent item gains additively: this uses the actual
persistent CombatRuntime and conditional recovery for every joint candidate.
"""
import json,os,sqlite3,tempfile,itertools
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob,substituted_multi_stage
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf358'
POLICY=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')

def run(limit=15):
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf357/WF357_L30_BEST_P3_STAGE.json').read_text())
 trials=json.loads((OUT/'WF358_L30_P3_TOP5_DIRECT_REPLAYS.json').read_text())
 baseline=trials['baseline']['mean_s_per_mob']
 winners=sorted((r for r in trials['results'] if r['result']['status']=='COMPLETE'
   and r['result']['mean_s_per_mob']<baseline-1e-7
   and len(r['swaps'])==1),key=lambda r:(r['result']['mean_s_per_mob'],r['slot']))
 # Limit to distinct slots; strong source-discovered alternatives only.
 best_by_slot={}
 for r in winners:best_by_slot.setdefault(r['slot'],r)
 best=list(best_by_slot.values())[:8]
 combos=[];seen=set()
 for k in (2,3,4):
  for subset in itertools.combinations(best,k):
   swaps={r['slot']:r['item_id'] for r in subset}
   key=tuple(sorted(swaps.items()))
   if key in seen:continue
   seen.add(key)
   try:substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=swaps)
   except ValueError:continue
   predicted=sum(baseline-r['result']['mean_s_per_mob'] for r in subset)
   combos.append({'swaps':swaps,'screened_independent_gain_s_per_mob':predicted})
 combos.sort(key=lambda x:-x['screened_independent_gain_s_per_mob'])
 combos=combos[:limit]
 t=monotonic();cpu=process_time();results=[];bestscore=baseline;beststage=stage
 OUT.mkdir(exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='wf358_joint_') as tmp:
  db=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
  ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  for row in combos:
   r=subprocess_stage_100mob(stage=stage,source_db_path=db,swaps=row['swaps'],timeout_s=18.,recovery_policy=POLICY)
   results.append({**row,'result':r})
   if r['status']=='COMPLETE' and r['mean_s_per_mob']<bestscore:
    bestscore=r['mean_s_per_mob']
    beststage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=row['swaps'])
    (OUT/'WF358_L30_BEST_JOINT_P3_STAGE.json').write_text(json.dumps(beststage,indent=2,sort_keys=True,default=str)+'\n')
   print('JOINT',len(results),row['swaps'],r['status'],r.get('mean_s_per_mob'),flush=True)
   (OUT/'WF358_L30_JOINT_P3_100MOB.json').write_text(json.dumps({
    'checkpoint':'druid:L30:unrestricted','status':'P3_JOINT_CALIBRATION_NOT_P4_P5',
    'baseline_s_per_mob':baseline,'best_s_per_mob':bestscore,
    'complete':sum(x['result']['status']=='COMPLETE' for x in results),
    'attempts':len(results),'wall_s':monotonic()-t,'cpu_s':process_time()-cpu,
    'source_stage':'evidence/wf357/WF357_L30_BEST_P3_STAGE.json',
    'results':results},indent=2,sort_keys=True)+'\n')
 return bestscore
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=15)
 a=p.parse_args();print('BEST',run(a.limit))

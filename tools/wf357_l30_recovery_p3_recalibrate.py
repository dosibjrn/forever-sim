"""Re-evaluate existing independently proposed legal gear swaps on corrected recovery objective."""
from pathlib import Path
import json,sqlite3,tempfile,os
from time import monotonic,process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf357'
def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf353/WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
 singles=json.loads((ROOT/'evidence/wf353/WF353_L30_P3_DIRECT_SWAP_EVIDENCE.json').read_text())['trials']
 combos=json.loads((ROOT/'evidence/wf353/WF353_L30_P3_JOINT_ITEM_EVIDENCE.json').read_text())['trials']
 policy=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
 start=monotonic();cpu=process_time();results=[]
 progress=OUT/'WF357_L30_P3_RECOVERY_RECALIBRATION.json'
 if progress.exists():results=json.loads(progress.read_text())['results']
 with tempfile.TemporaryDirectory(prefix='wf357_p3_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  jobs=[('base',{})]+[('single',{'slot':r['slot'],'item_id':r['item_id']}) for r in singles]+[('joint',{'swaps':r['swaps']}) for r in combos]
  for i,(kind,args) in enumerate(jobs):
   if i<len(results):continue
   if i>=int(os.environ.get('WF357_MAX_JOBS','31')):break
   r=subprocess_stage_100mob(stage=stage,source_db_path=src,timeout_s=12.,recovery_policy=policy,**args)
   row={'kind':kind,'input':args,'result':r}
   results.append(row)
   print(i+1,len(jobs),kind,r.get('status'),r.get('mean_s_per_mob'),flush=True)
   OUT.mkdir(exist_ok=True)
   (OUT/'WF357_L30_P3_RECOVERY_RECALIBRATION.json').write_text(json.dumps({
       'checkpoint':'druid:L30:unrestricted','p3_status':'FAIL_PARTIAL_TOP5',
       'policy':vars(policy),'tested':len(results),'complete':sum(x['result']['status']=='COMPLETE' for x in results),
       'wall_s':monotonic()-start,'cpu_s':process_time()-cpu,
       'results':results},indent=2,sort_keys=True)+'\n')
 return results
if __name__=='__main__':run()

"""Independent clean-child verification of best sourced L30 P3 joint package."""
import json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf358'
POLICY=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 prior=json.loads((OUT/'WF358_L30_JOINT_P3_100MOB.json').read_text())
 stage=json.loads((OUT/'WF358_L30_BEST_JOINT_P3_STAGE.json').read_text())
 with tempfile.TemporaryDirectory(prefix='wf358_verify_') as tmp:
  db=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
  ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  r=subprocess_stage_100mob(stage=stage,source_db_path=db,timeout_s=20.,recovery_policy=POLICY)
 if r['status']!='COMPLETE' or abs(r['mean_s_per_mob']-prior['best_s_per_mob'])>1e-7:
  raise ValueError('P3_JOINT_REPLAY_MISMATCH:'+str(r))
 result={'checkpoint':'druid:L30:unrestricted','status':'COMPLETE_REPRODUCED',
  'expected_s_per_mob':prior['best_s_per_mob'],'replay':r,
  'p3_acceptance':'NOT_YET','accepted_checkpoints':'1/148'}
 (OUT/'WF358_L30_FRESH_JOINT_REPLAY.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
 return result
if __name__=='__main__':print(json.dumps(run(),indent=2))

"""Fresh independent replay of best measured sourced gear+recovery package."""
from pathlib import Path
from hashlib import sha256
import json,sqlite3,os,tempfile
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage,subprocess_stage_100mob
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf357'
def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf353/WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
 swaps={'chest':7374,'hands':4107,'shoulder':2278,'weapon':279844}
 policy=BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
 with tempfile.TemporaryDirectory(prefix='wf357_fresh_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(src):
   best=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=swaps)
   (OUT/'WF357_L30_BEST_P3_STAGE.json').write_text(json.dumps(best,indent=2,sort_keys=True)+'\n')
   result=subprocess_stage_100mob(stage=best,source_db_path=src,timeout_s=12.,recovery_policy=policy)
  evidence={'checkpoint':'druid:L30:unrestricted','source_db_sha256':sha256(src.read_bytes()).hexdigest(),
    'stage_sha256':sha256((OUT/'WF357_L30_BEST_P3_STAGE.json').read_bytes()).hexdigest(),
    'policy':vars(policy),'swaps':swaps,'result':result,'p3':'PARTIAL_NOT_ACCEPTED','p4_p5_p6':'NOT_RUN'}
  (OUT/'WF357_L30_FRESH_REPLAY.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
  return evidence
if __name__=='__main__':
 r=run();print(json.dumps({'result':r['result'],'source_db_sha256':r['source_db_sha256']},indent=2))

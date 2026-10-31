"""Druid L30 source-staged persistent 100mob recovery comparison; no legacy seed."""
from pathlib import Path
import json,os,sqlite3,tempfile
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]
def run(mobs=100):
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf353/WF353_L30_P3_BEST_JOINT_ITEM_STAGE.json').read_text())
 with tempfile.TemporaryDirectory(prefix='wf357_recovery_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(src):
   ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
   c=prepare_candidate(class_key='druid',level=30,stage=stage,source_ir=ir,strict_l2_item_effects=True)
   modes=[('legacy_full',None),('threshold_50_20',BetweenPullPolicy(.5,.2,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')),('hot_50_20',BetweenPullPolicy(.5,.2,'rejuvenation:rank@28','cancel_mode:cat','cat_form:768')),('threshold_25_10',BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')),('threshold_10_05',BetweenPullPolicy(.1,.05,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')),('hot_25_10',BetweenPullPolicy(.25,.1,'rejuvenation:rank@28','cancel_mode:cat','cat_form:768',.15)),('hot_50_20_min30',BetweenPullPolicy(.5,.2,'rejuvenation:rank@28','cancel_mode:cat','cat_form:768',.30))]
   out={}
   for name,p in modes:
    result=evaluate_persistent_candidate(c,level=30,mobs=mobs,max_wall_s=25,max_cpu_s=25,max_total_events=200000,recovery_policy=p)
    out[name]=result
    print(name,result.get('status'),result.get('mean_s_per_mob'),result.get('reason'),result.get('between_pull_hot_casts'),result.get('between_pull_full_recoveries'),flush=True)
   return out
if __name__=='__main__':
 r=run();path=ROOT/'evidence/wf357';path.mkdir(exist_ok=True);(path/'WF357_RECOVERY_100MOB.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')

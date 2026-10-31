"""Independent source-stage recovery-policy search, P3 context only (not P4/P5)."""
from pathlib import Path
import json,os,sqlite3,tempfile
from time import monotonic,process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]
def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stage=json.loads((ROOT/'evidence/wf353/WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
 policies=(None,BetweenPullPolicy(.5,.2,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'),BetweenPullPolicy(.25,.1,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'))
 t=monotonic();cpu=process_time()
 with tempfile.TemporaryDirectory(prefix='wf357_frontier_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(src):
   outcome=select_persistent_finalists(class_key='druid',level=30,joint_result={'stages':[stage]},
       screen_mobs=2,finalist_mobs=100,max_screen_candidates=3,max_finalists=3,
       recovery_policies=policies,strict_l2_item_effects=True)
 result={'checkpoint':'druid:L30:unrestricted','status':outcome['status'],
         'wall_s':monotonic()-t,'cpu_s':process_time()-cpu,
         'screen_evaluated':outcome['screen_evaluated'],'finalists_evaluated':outcome['finalists_evaluated'],
         'paid_persistent_events':outcome['paid_persistent_events'],
         'winner':None if outcome['winner'] is None else {'recovery_policy':outcome['winner']['recovery_policy'],'persistent':outcome['winner']['persistent']},
         'finalists':[{'recovery_policy':f.get('recovery_policy'),'persistent':f['persistent']} for f in outcome['finalists']],
         'p3':'FAIL: this is one independently found gear/talent/policy stage; not all 18 slot Top5',
         'p4_p5_p6':'NOT RUN; not a 30/300s independent joint search'}
 out=ROOT/'evidence/wf357';out.mkdir(exist_ok=True)
 (out/'WF357_L30_RECOVERY_FRONTIER.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
 return result
if __name__=='__main__':
 r=run();print(json.dumps({'status':r['status'],'wall_s':r['wall_s'],'cpu_s':r['cpu_s'],
  'screen':r['screen_evaluated'],'finalists':r['finalists_evaluated'],
  'winner':r['winner']},indent=2))

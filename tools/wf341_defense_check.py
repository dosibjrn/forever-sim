from tools.wf341_rating_probe import ROOT
import json,tempfile,sqlite3,os
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.game.data.forever.source_checkpoint_p3_weights import _score
from src.game.data.forever.source_checkpoint_p3_ratings import apply_provisional_rating_delta
from tools.wf321_ingest_control_observations import ingest as ingest_control
from dataclasses import replace
os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
with tempfile.TemporaryDirectory() as tmp:
 staged=Path(tmp)/'s.sqlite'
 with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as dest:db.backup(dest)
 ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
 ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
 with ability_source_scope(staged):
  c=prepare_candidate(class_key='druid',level=20,stage=stage)
  for key in ('defense','dodge','hit','crit'):
   for x in ([0,4,8,16,32,64] if key in ('defense','dodge') else [0,4,8,12,16]):
    ir=apply_provisional_rating_delta(c.ir,key,x,level=20) if x else c.ir
    try:
     r=_score(replace(c,ir=ir),20,100)
     print(key,x,round(r['mean_s_per_mob'],7),round(r['combat_s']/100,6),round(r['recovery_s']/100,6),r['events'],flush=True)
    except Exception as e:print(key,x,type(e).__name__,str(e),flush=True)

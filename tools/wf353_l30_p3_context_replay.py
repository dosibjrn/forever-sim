"""Pay for 100mob context from independently found source stages; no legacy seed."""
from pathlib import Path
from time import monotonic,process_time
from hashlib import sha256
import json,sqlite3,tempfile,os
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf353'
def run(max_candidates=18,start_index=0):
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 stages=json.loads((OUT/'WF353_L30_DISCOVERED_STAGES.json').read_text())
 stages=[s for s in stages if s.get('gear_policy_result',{}).get('winner') and s['gear_policy_result']['winner'].get('gear') and s.get('score_s_per_mob') is not None]
 unique={}
 for s in sorted(stages,key=lambda x:(-sum(x['allocation'].values()),float(x['score_s_per_mob']))):
  g=s['gear_policy_result']['winner'];p=g['winner']
  key=json.dumps([s['allocation'],sorted((k,int(v['item_id'])) for k,v in g['gear']['slots'].items()),p],sort_keys=True,default=str)
  unique.setdefault(key,s)
 # Prioritize full-point builds and diverse policy families, not legacy stage.
 stage_order=list(unique.values())
 t=monotonic();cpu=process_time();rows=[];winner=None
 with tempfile.TemporaryDirectory(prefix='wf353_p3_replay_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(src):
   ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
   for idx in range(start_index,min(len(stage_order),max_candidates)):
    stage=stage_order[idx]
    print("START",idx,flush=True)
    result=subprocess_stage_100mob(stage=stage,source_db_path=src,timeout_s=9.)
    row={'index':idx,'spent_points':sum(stage['allocation'].values()),'source_l2_s_per_mob':stage['score_s_per_mob'],**result}
    rows.append(row)
    if result.get('status')=='COMPLETE' and (winner is None or result['mean_s_per_mob']<winner[1]['mean_s_per_mob']):
     winner=(stage,result)
     (OUT/'WF353_L30_CURRENT_P3_STAGE.json').write_text(json.dumps(stage,indent=2,sort_keys=True,default=str)+'\n')
    (OUT/'WF353_L30_P3_CONTEXT_REPLAYS.json').write_text(json.dumps({'rows':rows,'wall_s':monotonic()-t,'cpu_s':process_time()-cpu,'source_sha256':sha256(src.read_bytes()).hexdigest(),'best_s_per_mob':None if winner is None else winner[1]['mean_s_per_mob']},indent=2,sort_keys=True)+'\n')
    print(idx,row['spent_points'],result.get('status'),result.get('mean_s_per_mob'),flush=True)
 return {'tested':len(rows),'complete':sum(x['status']=='COMPLETE' for x in rows),'best':None if winner is None else winner[1]['mean_s_per_mob'],'wall_s':monotonic()-t}
if __name__=='__main__':print(json.dumps(run(),indent=2),flush=True)

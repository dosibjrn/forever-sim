"""Measure nonlinear legal multi-item interactions on real 100-mob CombatRuntime."""
from pathlib import Path
from itertools import combinations
from hashlib import sha256
from time import monotonic,process_time
import json,sqlite3,tempfile,os
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob,substituted_multi_stage,source_context_fingerprint
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/wf353'
def run(limit=12):
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
 single=json.loads((OUT/'WF353_L30_P3_DIRECT_SWAP_EVIDENCE.json').read_text())
 stage=json.loads((OUT/'WF353_L30_BEST_INDEPENDENT_P3_STAGE.json').read_text())
 good=sorted((r for r in single['trials'] if r['status']=='COMPLETE' and
              r['improvement_s_per_mob']>0),key=lambda r:-r['improvement_s_per_mob'])
 by_slot={}
 for r in good:by_slot.setdefault(r['slot'],r)
 chosen=list(by_slot.values())[:5]
 proposals=[]
 for n in range(len(chosen),1,-1):
  for group in combinations(chosen,n):
   swaps={r['slot']:r['item_id'] for r in group}
   proposals.append((sum(r['improvement_s_per_mob'] for r in group),swaps))
 proposals.sort(key=lambda x:(-x[0],-len(x[1])))
 started=monotonic();cpu=process_time();rows=[]
 with tempfile.TemporaryDirectory(prefix='wf353_p3_joint_') as tmp:
  db=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(db) as b:a.backup(b)
  ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  context=source_context_fingerprint(stage=stage,class_key='druid',level=30,
                                     source_db_sha256=sha256(db.read_bytes()).hexdigest())
  if context!=single['context_sha256']:raise ValueError('P3_JOINT_SWAP_CONTEXT_MISMATCH')
  existing=OUT/'WF353_L30_P3_JOINT_ITEM_EVIDENCE.json'
  prev=json.loads(existing.read_text()) if existing.exists() else {}
  if prev and prev['context_sha256']!=context:raise ValueError('P3_STALE_JOINT_CACHE')
  rows=list(prev.get('trials',[]));done={json.dumps(x['swaps'],sort_keys=True) for x in rows}
  best=min([single['baseline_s_per_mob']]+[r['mean_s_per_mob'] for r in rows if r['status']=='COMPLETE'])
  for _,swaps in proposals[:limit]:
   key=json.dumps(swaps,sort_keys=True)
   if key in done:continue
   result=subprocess_stage_100mob(stage=stage,source_db_path=db,swaps=swaps,timeout_s=9.)
   row={'swaps':swaps,'individual_prior_improvement_s_per_mob':sum(
          r['improvement_s_per_mob'] for r in chosen if r['slot'] in swaps),**result}
   rows.append(row)
   if result['status']=='COMPLETE' and result['mean_s_per_mob']<best:
    best=result['mean_s_per_mob']
    new=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=swaps)
    (OUT/'WF353_L30_P3_BEST_JOINT_ITEM_STAGE.json').write_text(json.dumps(new,indent=2,sort_keys=True,default=str)+'\n')
   report={'checkpoint':'druid:L30:unrestricted','context_sha256':context,
     'baseline_100mob_s_per_mob':single['baseline_s_per_mob'],
     'best_100mob_s_per_mob':best,'trials':rows,
     'wall_s':monotonic()-started,'cpu_s':process_time()-cpu,
     'status':'P3_NONLINEAR_ITEM_INTERACTION_PARTIAL','accepted_checkpoints':'1/148'}
   existing.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
   print('JOINT',swaps,result['status'],result.get('mean_s_per_mob'),flush=True)
 return {'trials':len(rows),'complete':sum(r['status']=='COMPLETE' for r in rows),'best':best,
         'baseline':single['baseline_s_per_mob'],'wall_s':monotonic()-started}
if __name__=='__main__':print(json.dumps(run(),indent=2),flush=True)

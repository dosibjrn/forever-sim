"""Independent Druid L30 discovery for P3 build-context calibration; not P4/P5."""
from pathlib import Path
from time import monotonic,process_time
import os,sqlite3,tempfile,json
from hashlib import sha256
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf353';OUT.mkdir(parents=True,exist_ok=True)
def run():
 os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13';t=monotonic();cpu=process_time()
 with tempfile.TemporaryDirectory(prefix='wf353_p3_context_') as tmp:
  src=Path(tmp)/'source.sqlite'
  with sqlite3.connect(f"file:{(ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite').resolve()}?mode=ro",uri=True) as a,sqlite3.connect(src) as b:a.backup(b)
  ingest_observations(src,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
  ingest_control(src,ROOT/'evidence/wf321/druid_l20_control_observations.json')
  with ability_source_scope(src):
   ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=src)
   opts={**JOINT_ARGS,'level':30,'ir_slice':ir,'max_evaluations':520,'max_event_transitions':75000,'initial_search':12,'search_per_gear':10,'max_gear_states':3,'evaluations_per_talent':70,'talent_corridor_reserve':7,'talent_screening_attempts':25,'post_talent_refinement_budget':70,'exclude_unknown_item_effects':True}
   joint=run_source_budgeted_joint_talents(**opts)
   print('joint',joint['attempted'],joint['evaluated'],joint['event_transitions'],'stages',len(joint.get('stages',[])),flush=True)
   from src.v2.source_persistent_joint_finalists import _paid_source_candidate_stages
   stages=_paid_source_candidate_stages(joint)
   (OUT/'WF353_L30_DISCOVERED_STAGES.json').write_text(json.dumps(stages,indent=2,sort_keys=True,default=str)+'\n')
   result={'checkpoint':'druid:L30:unrestricted','source_stage_sha256':sha256(src.read_bytes()).hexdigest(),'joint_attempted':joint['attempted'],'joint_events':joint['event_transitions'],'paid_stages':len(stages),'spent_points':[sum(s['allocation'].values()) for s in stages],'wall_s':monotonic()-t,'cpu_s':process_time()-cpu}
   (OUT/'WF353_L30_DISCOVERY_CONTEXT.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
   return result

if __name__=='__main__':print(json.dumps(run(),indent=2),flush=True)

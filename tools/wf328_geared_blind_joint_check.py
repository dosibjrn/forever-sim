"""Fresh Druid L20 combined source gear/talent/policy search, same stage as WF326.

Historical winner is not read until AFTER the independent search and replay.
"""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_persistent_joint_finalists import select_persistent_finalists
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS
from src.game.data.forever.sqlite_talents import DEFAULT_DB
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    options={**JOINT_ARGS,'max_evaluations':800,'evaluations_per_talent':52,
        'initial_search':10,'search_per_gear':16,'max_gear_states':4,
        'max_event_transitions':115000,'post_talent_refinement_budget':130,
        'talent_corridor_reserve':9,'talent_screening_attempts':95,
        'probe_stats':('agility','strength','stamina','spirit','armor','dodge_rating')}
    t=monotonic();cpu=process_time()
    with tempfile.TemporaryDirectory(prefix='wf328_joint_') as tmp:
        db=Path(tmp)/'source_stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as source, sqlite3.connect(db) as dest:
            source.backup(dest)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=db)
            searched=run_source_budgeted_joint_talents(**options,ir_slice=ir)
            search_wall=monotonic()-t
            search_cpu=process_time()-cpu
            print(json.dumps({'phase':'joint','attempted':searched['attempted'],'evaluated':searched['evaluated'],
               'events':searched['event_transitions'],'talent_allocations':searched['distinct_talent_allocations_paid_L2'],
               'search_wall':search_wall,'search_cpu':search_cpu}),flush=True)
            finalists=select_persistent_finalists(class_key='druid',level=20,joint_result=searched,
                screen_mobs=3,finalist_mobs=100,max_finalists=10,max_screen_candidates=40,
                max_screen_wall_s=5,max_finalist_wall_s=10)
    winner=finalists.get('winner')
    out={'schema':'wf328_identical_stage_independent_joint_druid20_v1','status':finalists['status'],
         'comparison_reference':'WF326 13.46412880141965 s/mob (same source and hundred-mob scorer)',
         'checkpoint':'Druid L20 unrestricted',
         'origin':'self-discovered gear/talent/ordered policy (no old winner injected)',
         'search_attempted':searched['attempted'],'search_evaluated':searched['evaluated'],
         'joint_events':searched['event_transitions'],'distinct_talent_allocations':searched['distinct_talent_allocations_paid_L2'],
         'search_wall_s':search_wall,'search_cpu_s':search_cpu,
         'full_wall_s':monotonic()-t,'full_cpu_s':process_time()-cpu,
         'screen_evaluated':finalists['screen_evaluated'],'finalists_evaluated':finalists['finalists_evaluated'],
         'winner':None if winner is None else {
             'mean_s_per_mob':winner['persistent'].get('mean_s_per_mob'),
             'status':winner['persistent']['status'],
             'talents':winner['allocation'],
             'gear':{s:int(item['item_id']) for s,item in winner['stage']['gear_policy_result']['winner']['gear']['slots'].items()},
             'prefix':winner['stage']['gear_policy_result']['winner']['winner']['prefix'],
             'fallback':winner['stage']['gear_policy_result']['winner']['winner']['fallback']},
         'PASS4':False,'PASS5':False,'PASS6':False,
         'limitations':'Attempt/event bounded joint search; NOT hard 30/300s wall-constrained acceptance.'}
    return out

if __name__=='__main__':
    out=run();path=ROOT/'evidence/wf328/WF328_GEARED_BLIND_100MOB_SAME_SOURCE.json'
    path.parent.mkdir(exist_ok=True,parents=True);path.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print(json.dumps(out,indent=2,sort_keys=True),flush=True)

"""Bounded weighted P3 gear-pilot; NOT P4 joint search."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_persistent_slot_search import search_persistent_gear_slots
from tools.wf321_ingest_control_observations import ingest as ingest_control
ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    report=json.loads((ROOT/'evidence/wf339/WF339_DRUID_L20_WEIGHTED_TOP5_PER_SLOT.json').read_text())
    with tempfile.TemporaryDirectory(prefix='wf339_pilot_') as tmp:
        staged=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as dest: db.backup(dest)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            result=search_persistent_gear_slots(class_key='druid',level=20,seed_stage=stage,
                weighted_p3_report=report,rounds=1,per_slot=1,max_proposals_per_round=18,
                screen_mobs=8,finalist_mobs=100,max_finalists=3,max_cpu_s=35.,max_events=150000)
    out={'schema':'wf339_weighted_slot_pilot_v1','status':result['status'],
      'is_p4':False,'is_p3_pass':False,'p3_weighted_priority_used':True,
      'attempts':result['attempts'],'full_100mob_evaluations':result['full_100mob_evaluations'],
      'initial_s_per_mob':result['initial']['mean_s_per_mob'],
      'best_s_per_mob':result['winner']['mean_s_per_mob'],
      'events':result['events'],'wall_s':result['wall_s'],'cpu_s':result['cpu_s'],
      'rounds':result['rounds']}
    (ROOT/'evidence/wf339/WF339_WEIGHTED_SLOT_PILOT.json').write_text(json.dumps(out,indent=2))
    return out
if __name__=='__main__':print(json.dumps(run(),indent=2))

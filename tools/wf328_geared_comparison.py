"""Druid L20 identical-source 100-mob replay, using recorded source-legal gear/talents/policy."""
from __future__ import annotations
import json, os, sqlite3, tempfile
from pathlib import Path
from time import monotonic, process_time
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.sqlite_talents import DEFAULT_DB

ROOT=Path(__file__).resolve().parents[1]

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    evidence=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
    stage=evidence['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory(prefix='wf328_geared_') as tmp:
        stage_db=Path(tmp)/'source_stage.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as source, sqlite3.connect(stage_db) as dest:
            source.backup(dest)
        ingest_observations(stage_db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(stage_db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(stage_db):
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
            replay=evaluate_persistent_candidate(candidate,level=20,mobs=100,max_wall_s=15,max_total_events=100000)
    reference=evidence['finalist']['winner']['persistent']
    return {'status':replay['status'],'new':replay,'old':{'status':reference['status'],'mean_s_per_mob':reference['mean_s_per_mob'],'events':reference['events']},
        'absolute_difference_s':replay.get('mean_s_per_mob',float('nan'))-reference['mean_s_per_mob'],
        'comparable_identical_stage':True,'independent_new_search':False}

if __name__=='__main__':
    print(json.dumps(run(),indent=2))

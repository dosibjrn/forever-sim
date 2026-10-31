"""WF324: independent source-data same-scenario 100-mob L2 comparison.

Tests the production persistent ActorState executor. Not acceptance for 1/148:
verified source effects and obtainable gear are still incomplete.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate


@pytest.fixture(scope='module')
def staged_db(tmp_path_factory):
    db=tmp_path_factory.mktemp('wf324-horizon')/'data.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(db) as dest:
        original.backup(dest)
    assert ingest_observations(db,Path('evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json'))['count']==9
    ingest_control(db,Path('evidence/wf321/druid_l20_control_observations.json'))
    return db


def test_wf324_100mob_objective_differs_from_paid_single_mob_order(staged_db,monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    base=json.loads(Path('evidence/wf324/WF324_BASELINE_SAME_BUDGET.json').read_text())
    screened=json.loads(Path('evidence/wf324/WF324_SCREENED.json').read_text())
    assert base['attempted']==screened['attempted']==320
    assert base['score_s_per_mob']>screened['score_s_per_mob']
    with ability_source_scope(staged_db):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=staged_db)
        rows=[]
        for result in (base,screened):
            stage={'allocation':result['allocation'],
                'gear_policy_result':{'winner':{'gear':result['gear'],'winner':result['policy']}}}
            candidate=prepare_candidate(class_key='druid',level=20,stage=stage,source_ir=ir)
            check=evaluate_persistent_candidate(candidate,level=20,mobs=100)
            assert check['status']=='COMPLETE'
            assert check['count']==100 and check['continuous_actor_state']
            assert check['combat_s']>0 and check['recovery_s']>0
            assert check['events']>0
            rows.append(check)
    assert rows[1]['mean_s_per_mob']<rows[0]['mean_s_per_mob']
    assert rows[1]['mean_s_per_mob']==pytest.approx(13.9240531311,abs=1e-6)
    assert rows[0]['mean_s_per_mob']==pytest.approx(14.7018277323,abs=1e-6)

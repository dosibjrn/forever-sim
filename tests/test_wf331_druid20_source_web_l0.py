"""Source-bound L0 web-indexed observation safety and checkpoint scoping."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations,load_observations
from src.game.data.forever.source_checkpoint_context_proxy import source_context_evidence
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_db_scope import ability_source_scope

ROOT=Path(__file__).resolve().parents[1]
OBS=ROOT/'evidence/wf331/druid20_source_web_index_observations.json'

@pytest.fixture
def source_stage(tmp_path):
    stage=tmp_path/'stage.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src, sqlite3.connect(stage) as dst:
        src.backup(dst)
    return stage


def test_source_identity_and_l0_provenance(source_stage):
    out=ingest_observations(source_stage,OBS)
    assert out['observations_ingested']==20
    with sqlite3.connect(source_stage) as db:
        db.row_factory=sqlite3.Row
        rows=load_observations(db,'druid')
    assert len(rows)==20
    assert rows[5215]['source_flags']==['precombat_only']
    assert rows[408245]['source_flags']==['not_an_action','grant_or_trigger_unverified']
    assert 439756 not in rows
    assert all(row['capture_kind']!='authenticated_html' for row in rows.values())


def test_web_indexed_context_roles_are_conditional_not_free_damage():
    samples={'Forces an enemy to sleep for up to 20 sec':'conditional_sleep_control',
             'Cures 1 poison effect on the target':'poison_dispel',
             'Returns the spirit of a dead target to the body':'resurrection',
             'Charge a target and interrupt spellcasting':'spell_interrupt',
             'Allows the Druid to prowl, stealthed':'precombat_stealth',
             'Deals Arcane damage and increases damage done by your next Starfire cast by 80%':'next_cast_amplifier',
             'Summon a flurry of stars for 10 sec':'periodic_multi_target_proc'}
    for txt,role in samples.items():
        result=source_context_evidence(txt,target_hp=200)
        assert role in {x['kind'] for x in result['effect_candidates']}
        assert not result['proxy_is_gameplay_execution_or_legality_proof']


def test_web_observation_is_staged_not_source_or_paid_L2(source_stage):
    canonical_sha=hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest()
    with ability_source_scope(source_stage):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=source_stage)
        before=action_frontier(ir,class_key='druid',level=20,db_path=source_stage)
    ingest_observations(source_stage,OBS)
    with ability_source_scope(source_stage):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=source_stage)
        after=action_frontier(ir,class_key='druid',level=20,db_path=source_stage)
    assert before['potentially_legal_positive_ranks']==65
    assert after['potentially_legal_positive_ranks']==52
    assert after['rune_conditional_grants_blocked_without_talent']==9
    assert after['rune_engraving_rows_disabled']==37
    assert after['potential_ranks_assessed_by_numeric_ir_or_text_role'] > before['potential_ranks_assessed_by_numeric_ir_or_text_role']
    assert after['paid_search_admitted_source_rows']==before['paid_search_admitted_source_rows']
    assert after['web_indexed_observations_are_L2_or_legality_proof'] is False
    assert after['PASS1'] is False
    assert hashlib.sha256(DEFAULT_DB.read_bytes()).hexdigest()==canonical_sha


def test_web_source_tampering_fails_atomic(source_stage,tmp_path):
    doc=json.loads(OBS.read_text())
    doc['observations'][0]['source_index_sha256']='0'*64
    path=tmp_path/'bad.json';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='SOURCE_WEB_L0_INDEX_IDENTITY_MISMATCH'):
        ingest_observations(source_stage,path)
    with sqlite3.connect(source_stage) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_source_l0_web_observations'").fetchone() is None


def test_web_observation_duplicate_fails(source_stage,tmp_path):
    doc=json.loads(OBS.read_text());doc['observations'].append(copy.deepcopy(doc['observations'][0]))
    path=tmp_path/'duplicate.json';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='SOURCE_WEB_L0_DUPLICATE_ID'):
        ingest_observations(source_stage,path)


def test_web_url_mismatch_fails(source_stage,tmp_path):
    doc=json.loads(OBS.read_text());doc['observations'][0]['observed_url']='https://www.wowhead.com/forever/spell=999999/hibernate'
    path=tmp_path/'wrong.json';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='SOURCE_WEB_L0_SPELL_URL_MISMATCH'):
        ingest_observations(source_stage,path)


def test_web_stale_source_row_fails(source_stage):
    ingest_observations(source_stage,OBS)
    with sqlite3.connect(source_stage) as db:
        db.execute("UPDATE spell_index SET name='changed' WHERE class_key='druid' AND spell_id=5215")
        db.row_factory=sqlite3.Row
        with pytest.raises(ValueError,match='SOURCE_WEB_L0_STALE_INDEX_OBSERVATION'):
            load_observations(db,'druid')


def test_web_missing_index_row_fails(source_stage):
    ingest_observations(source_stage,OBS)
    with sqlite3.connect(source_stage) as db:
        db.execute("DELETE FROM spell_index WHERE class_key='druid' AND spell_id=5215")
        db.row_factory=sqlite3.Row
        with pytest.raises(ValueError,match='SOURCE_WEB_L0_STALE_INDEX_OBSERVATION'):
            load_observations(db,'druid')

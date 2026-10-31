"""Verified source NPC/quest/item batch and fail-closed generic world events.

A synthetic world origin is deliberately TEST-ONLY; this suite does not
claim a production world origin or a completed class-level checkpoint.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_acquisition import audit_learned_action_legality
from src.game.data.forever.source_world_acquisition import (
    UnverifiedWorldEvent, verify_acquisition_trace,
)
from src.game.level_legality import LevelState, validate_level_state
from tools.ingest_source_acquisition_entities_sqlite import ingest


@pytest.fixture
def sourced_db(tmp_path):
    dest=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,dest)
    with sqlite3.connect(dest) as con:
        entity=con.execute('''SELECT entity_id,zone_ids_json FROM ability_acquisition_entities
            WHERE class_key='mage' AND spell_id=122 AND method='taught_by_npc'
              AND zone_ids_json!='[]' ORDER BY entity_id LIMIT 1''').fetchone()
        assert entity
        npc,zones=entity
        zone=json.loads(zones)[0]
        con.execute('''CREATE TABLE world_origin_evidence (
            origin_id TEXT PRIMARY KEY, class_key TEXT, min_level INTEGER,
            zone_id INTEGER, initial_copper INTEGER,
            source_url TEXT, capture_id TEXT, source_payload TEXT, source_sha256 TEXT
        )''')
        provenance='fixture-origin-only-not-real-world-evidence'
        con.execute('INSERT INTO world_origin_evidence VALUES (?,?,?,?,?,?,?,?,?)',
                    ('TEST_ANCHOR','mage',10,zone,100000,
                     'test://only/synthetic-origin','test-fixture',provenance,
                     hashlib.sha256(provenance.encode()).hexdigest()))
    return dest,npc,zone


def _trainer(npc,spell=122):
    return {'kind':'trainer_purchase','npc_id':npc,'spell_id':spell}


def test_405_actual_html_verified_links_with_exact_type_and_provenance():
    with sqlite3.connect(DEFAULT_DB) as db:
        assert db.execute('SELECT COUNT(*) FROM ability_acquisition_entities').fetchone()[0]==405
        assert db.execute('SELECT COUNT(DISTINCT method || ":" || entity_id) FROM ability_acquisition_entities').fetchone()[0]==212
        counts=dict(db.execute('SELECT method,COUNT(*) FROM ability_acquisition_entities GROUP BY method'))
        assert counts=={'taught_by_npc':398,'reward_from_quest':6,'taught_by_item':1}
        assert db.execute("SELECT COUNT(DISTINCT class_key) FROM ability_acquisition_evidence").fetchone()[0]==9


def test_idempotent_source_batch_and_corrupt_snapshot_is_atomic(tmp_path):
    path=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,path)
    assert ingest(path)==ingest(path)
    with sqlite3.connect(path) as con:
        count=con.execute('SELECT COUNT(*) FROM ability_acquisition_entities').fetchone()[0]
        con.execute('''UPDATE spell_detail_snapshots SET html_sha256='bad'
                       WHERE spell_id=122''')
    with pytest.raises(Exception):
        ingest(path)
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT COUNT(*) FROM ability_acquisition_entities').fetchone()[0]==count


def test_real_spell_detail_and_npc_id_allow_synthetic_local_purchase(sourced_db):
    path,npc,zone=sourced_db
    receipt=verify_acquisition_trace(class_key='mage',level=10,
        anchor_id='TEST_ANCHOR',events=(_trainer(npc),),db_path=path)
    assert receipt['verified_learned_spell_ids']==[122]
    assert receipt['verified_event_count']==1
    assert receipt['remaining_copper']==99600  # canonical spell index cost
    assert receipt['world_route_complete'] is False
    ir=build_game_ir_slice(class_key='mage',level=10)
    result=audit_learned_action_legality(ir,level=10,
        action_ids=['frost_nova:122'],world_anchor_id='TEST_ANCHOR',
        world_events=(_trainer(npc),),db_path=path)
    assert result['complete'] is True
    assert result['verified_world_acquisition_count']==1
    # The complete LevelState validator uses production canonical DB, NOT the
    # synthetic test fixture, so a forged trace cannot certify a real state.
    state=LevelState(class_key='mage',level=10,race_key=ir.actor.metadata.get('race_key'),
        talents={},action_ids=('frost_nova:122',),world_origin_id='TEST_ANCHOR',
        world_acquisition_events=(_trainer(npc),))
    with pytest.raises(ValueError):
        validate_level_state(state,require_world_acquisition=True)


def test_negative_wrong_npc_zone_rank_funds_and_claim(sourced_db):
    path,npc,zone=sourced_db
    for event in (_trainer(-42),_trainer(npc,999999),
                  {'kind':'free_grant','spell_id':122},
                  {'kind':'quest_completed','quest_id':1498}):
        with pytest.raises(UnverifiedWorldEvent):
            verify_acquisition_trace(class_key='mage',level=10,
                anchor_id='TEST_ANCHOR',events=(event,),db_path=path)
    with sqlite3.connect(path) as con:
        con.execute('UPDATE world_origin_evidence SET zone_id=?',(999999,))
    with pytest.raises(UnverifiedWorldEvent,match='NPC_NOT_SOURCED'):
        verify_acquisition_trace(class_key='mage',level=10,
            anchor_id='TEST_ANCHOR',events=(_trainer(npc),),db_path=path)
    with sqlite3.connect(path) as con:
        con.execute('UPDATE world_origin_evidence SET zone_id=?,initial_copper=0',(zone,))
    with pytest.raises(UnverifiedWorldEvent,match='INSUFFICIENT'):
        verify_acquisition_trace(class_key='mage',level=10,
            anchor_id='TEST_ANCHOR',events=(_trainer(npc),),db_path=path)
    with pytest.raises(UnverifiedWorldEvent,match='WORLD_ORIGIN'):
        verify_acquisition_trace(class_key='mage',level=10,
            anchor_id='MADE_UP',events=(_trainer(npc),),db_path=path)


def test_negative_entity_location_or_digest_tamper(sourced_db):
    path,npc,zone=sourced_db
    with sqlite3.connect(path) as con:
        con.execute('''UPDATE ability_acquisition_entities SET zone_ids_json='[999999]'
            WHERE class_key='mage' AND spell_id=122 AND entity_id=?''',(npc,))
    with pytest.raises(UnverifiedWorldEvent,match='ENTITY_SOURCE_FIELDS_TAMPERED'):
        verify_acquisition_trace(class_key='mage',level=10,
            anchor_id='TEST_ANCHOR',events=(_trainer(npc),),db_path=path)


def test_production_anchor_absent_cannot_mint_a_spell():
    with pytest.raises(UnverifiedWorldEvent,match='NO_CANONICAL_WORLD_ORIGIN'):
        verify_acquisition_trace(class_key='mage',level=10,
            anchor_id='FAKE',events=(_trainer(1),))

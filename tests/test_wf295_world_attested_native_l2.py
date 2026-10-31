"""Actual world-source trace -> SAME production L2 controller, never a fake checkpoint.

The positive origin below exists ONLY in an isolated synthetic test fixture;
production catalogue has no independently captured world origins at present.
"""
from __future__ import annotations
from hashlib import sha256
import sqlite3
from pathlib import Path
import pytest

from src.v2.source_budgeted_level_route import search_source_bounded_level_route
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_world_acquisition import verify_acquisition_trace

BASE = dict(class_key='mage',start_level=10,end_level=10,
            max_active_paths=1,max_children_per_path=1,max_l2_per_state=4,
            max_events_per_state=1600,max_total_events=4000,
            max_total_l2_attempts=5)
EVENT=({'kind':'trainer_purchase','spell_id':122,'npc_id':328},)


def _synthetic_world_stage(path):
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(path) as dest:
        src.backup(dest)
    # This is NOT real world origin evidence! Fake source payload tests only
    # whether the existing canonical verifier and controller interoperate.
    text='synthetic unit-test mock source only'
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE world_origin_evidence
            (origin_id TEXT NOT NULL, class_key TEXT NOT NULL, min_level INTEGER NOT NULL,
            zone_id INTEGER NOT NULL, initial_copper INTEGER NOT NULL,
            source_payload TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            source_url TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY (origin_id,class_key))''')
        db.execute('INSERT INTO world_origin_evidence VALUES (?,?,?,?,?,?,?,?,?)',(
            'fixture-origin','mage',10,12,400,text,sha256(text.encode()).hexdigest(),
            'https://www.wowhead.com/forever/npc=328','synthetic-test-not-source-capture'))
        db.commit()


def test_real_catalogue_has_no_world_origin_and_l2_is_not_attempted():
    result=search_source_bounded_level_route(**BASE,world_origin_id='fixture-origin',world_events=EVENT)
    assert result['status']=='BLOCKED_UNVERIFIED_WORLD_ACQUISITION'
    assert result['compute']['l2_attempts']==0
    assert result['accepted_class_level_checkpoints']==0
    assert 'BLOCKED_NO_CANONICAL_WORLD_ORIGIN' in result['failures'][0]['reason']


def test_verified_trace_not_replaced_by_caller_synthetic_learned_ids(tmp_path):
    stage=tmp_path/'stage.sqlite';_synthetic_world_stage(stage)
    with pytest.raises(ValueError,match='WORLD_TRACE_SINGLE_LEVEL_AND_NO_SYNTHETIC'):
        from src.game.data.forever.source_acquisition_events import AcquisitionCharacterState
        search_source_bounded_level_route(**BASE,world_origin_id='fixture-origin',world_events=EVENT,
            world_db_path=stage,initial_acquisition_state=AcquisitionCharacterState('mage',10,12,400,
            learned_spell_ids=frozenset({143})))
    result=search_source_bounded_level_route(**BASE,world_origin_id='fixture-origin',world_events=({'kind':'trainer_purchase','spell_id':122,'npc_id':331},),world_db_path=stage)
    assert result['status']=='BLOCKED_UNVERIFIED_WORLD_ACQUISITION'
    assert result['compute']['l2_attempts']==0
    assert 'BLOCKED_NPC_NOT_SOURCED_IN_PLAYER_ZONE' in result['failures'][0]['reason']


def test_stage_trace_reaches_real_l2_without_promoting_checkpoint(tmp_path):
    stage=tmp_path/'stage.sqlite';_synthetic_world_stage(stage)
    proof=verify_acquisition_trace(class_key='mage',level=10,
        anchor_id='fixture-origin',events=EVENT,db_path=stage)
    assert proof['verified_learned_spell_ids']==[122]
    result=search_source_bounded_level_route(**BASE,world_origin_id='fixture-origin',
        world_events=EVENT,world_db_path=stage)
    assert result['compute']['l2_attempts']>0
    assert result['compute']['event_transitions']>0
    assert result['accepted_class_level_checkpoints']==0
    assert result['full_route_complete'] is False
    if result['selected_route']:
        assert result['selected_route'][0]['world_acquisition_verified']
        assert all('frost_nova:122'==aid for aid in result['selected_route'][0]['source_action_ids'])


def test_world_single_level_only_and_no_free_event_minting():
    with pytest.raises(ValueError,match='WORLD_TRACE_SINGLE_LEVEL'):
        search_source_bounded_level_route(**{**BASE,'end_level':11},
            world_origin_id='any',world_events=EVENT)
    with pytest.raises(ValueError,match='WORLD_EVENTS_REQUIRE'):
        search_source_bounded_level_route(**BASE,world_events=EVENT)

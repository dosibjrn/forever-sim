"""Nine-class source acquisition batch; negative legal-world tests."""
import json
from pathlib import Path
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_acquisition import (
    read_acquisition_evidence,
)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.level_legality import LevelState, validate_level_state
from tools.ingest_source_acquisition_evidence_sqlite import ingest

CLASSES = ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')


def test_all_nine_class_source_rows_and_hashes():
    with sqlite3.connect(DEFAULT_DB) as db:
        indexed = db.execute("SELECT COUNT(*) FROM spell_index WHERE kind='abilities'").fetchone()[0]
        evidence = db.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]
        assert indexed == evidence == 2255
        assert db.execute('SELECT COUNT(DISTINCT class_key) FROM ability_acquisition_evidence').fetchone()[0] == 9
    for key in CLASSES:
        ir = build_game_ir_slice(class_key=key,level=20)
        assert ir is not None
        coverage = next(f for f in ir.source_facts if f.get('fact_kind')=='canonical_indexed_ability_coverage')
        retired_fields = {
            'acquisition_evidence_status',
            'acquisition_methods_observed',
            'world_acquisition_verified',
            'typed_index_acquisition',
        }
        assert all(not retired_fields.intersection(record)
                   for record in coverage['records'])


def test_level_state_does_not_require_separate_acquisition_proof():
    ir=build_game_ir_slice(class_key='druid',level=20)
    s=LevelState(class_key='druid',level=20,race_key=ir.actor.metadata['race_key'],
                 talents={},action_ids=(ir.actions[0].id,))
    # The bounded legacy scenario check is not a trainer/learned-spell gate.
    # Native MythicSim decides actual spell/rank legality when executed.
    assert validate_level_state(s)['status']=='LEGAL_SOURCE_SCENARIO'
    assert not hasattr(s, 'world_acquisition_events')
    assert not hasattr(s, 'world_origin_id')


def test_data_only_stale_index_change_blocks(tmp_path):
    db=tmp_path/'ability.sqlite'
    import shutil
    shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        sid=conn.execute("SELECT spell_id FROM ability_acquisition_evidence WHERE class_key='mage' LIMIT 1").fetchone()[0]
        conn.execute("UPDATE spell_index SET raw_listview_json='{}' WHERE class_key='mage' AND spell_id=?",(sid,))
    row=read_acquisition_evidence(class_key='mage',spell_ids=[sid],db_path=db)[sid]
    assert row['status']=='STALE_INDEX_EVIDENCE'


def test_ingest_replay_deterministic_and_transactional(tmp_path):
    db=tmp_path/'ability.sqlite'
    import shutil
    shutil.copy2(DEFAULT_DB,db)
    first=ingest(db)
    second=ingest(db)
    assert first==second
    assert first['indexed_abilities']==2255
    assert first['world_acquisition_verified']==0
    with sqlite3.connect(db) as conn:
        count=conn.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]
        conn.execute("UPDATE spell_index SET raw_listview_json='not-json' WHERE spell_id=71 AND class_key='warrior'")
    with pytest.raises(json.JSONDecodeError):
        ingest(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ability_acquisition_evidence').fetchone()[0]==count


def test_detail_snapshot_change_revokes_method_evidence(tmp_path):
    import shutil
    db=tmp_path/'ability.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        key=conn.execute("SELECT class_key,spell_id,index_batch_id FROM ability_acquisition_evidence WHERE detail_html_sha256 IS NOT NULL LIMIT 1").fetchone()
        assert key
        before=read_acquisition_evidence(class_key=key[0],spell_ids=[key[1]],db_path=db)
        assert before[key[1]]['status']=='CURRENT_SOURCE_EVIDENCE'
        conn.execute('UPDATE spell_detail_snapshots SET html_sha256=? WHERE batch_id=? AND spell_id=?',
                     ('tampered',key[2],key[1]))
    after=read_acquisition_evidence(class_key=key[0],spell_ids=[key[1]],db_path=db)
    assert after[key[1]]['status']=='STALE_DETAIL_EVIDENCE'

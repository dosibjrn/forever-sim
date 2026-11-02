from __future__ import annotations

from pathlib import Path
import sqlite3

from tools.capture_forever_abilities_sqlite import (
    complete_index, initialize_db, normalize_list_row, reported_count, save_index,
    spell_id_from_url,
)


def test_wowhead_spell_link_and_rank():
    assert spell_id_from_url("https://www.wowhead.com/forever/spell=2687/bloodrage") == 2687
    row = normalize_list_row({"id": 2687, "name":"Bloodrage", "level": 10}, "warrior", "abilities")
    assert row["spell_id"] == 2687 and row["level_hint"] == 10 and row["rank_hint"] is None
    row2 = normalize_list_row({"id": 1234, "name": "Sinister Strike Rank 3", "level": 18}, "rogue", "abilities")
    assert row2["rank_hint"] == 3


def test_counts_fail_closed():
    assert reported_count("175 spells found (175 displayed)") == 175
    assert reported_count("1 - 100 of 175") == 175
    assert complete_index(175, 100, False) is False
    assert complete_index(None, 175, False) is False
    assert complete_index(175, 175, True) is False
    assert complete_index(175, 175, False) is True


def test_sqlite_raw_capture_and_completeness(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "abilities.sqlite")
    initialize_db(db)
    db.execute("INSERT INTO capture_batches VALUES (?,?,?,?,?,?)", ("test", "2026-10-08T12:00:00Z", "wowhead", None, "in_progress", None))
    rows = [{"id": 2687, "name": "Bloodrage", "level": 10},
            {"id": 772, "name": "Rend Rank 1", "level": 4}]
    result = save_index(db,batch_id="test",class_key="warrior",kind="abilities",
                        source_url="https://www.wowhead.com/forever/spells/abilities/warrior",
                        expected=2,rows=rows,blocked_reason=None,content_hash="abcd")
    assert result["complete"] is True
    assert db.execute("SELECT COUNT(*) FROM spell_index").fetchone()[0] == 2
    assert db.execute("SELECT rank_hint FROM spell_index WHERE spell_id=772").fetchone()[0] == 1
    assert db.execute("SELECT complete FROM capture_lists").fetchone()[0] == 1
    db.close()


def test_duplicate_rows_do_not_fake_completeness(tmp_path: Path):
    db = sqlite3.connect(tmp_path / "abilities.sqlite")
    initialize_db(db)
    db.execute("INSERT INTO capture_batches VALUES (?,?,?,?,?,?)", ("test", "2026-10-08T12:00:00Z", "wowhead", None, "in_progress", None))
    dupes = [{"id": 2687, "name": "Bloodrage"}] * 3
    result = save_index(db,batch_id="test",class_key="warrior",kind="abilities",source_url="x",
                        expected=3,rows=dupes,blocked_reason=None,content_hash="abcd")
    assert result["complete"] is False and result["captured"] == 1
    db.close()

"""Source-index maintenance rank selection is shared; semantics stay fail-closed."""
import json
import sqlite3

import pytest

from src.game.data.forever.source_maintenance_ranks import (
    latest_reactive_maintenance_rank,
    latest_stat_maintenance_rank,
)


@pytest.fixture
def source_db(tmp_path):
    db = tmp_path / "source.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE spell_index (class_key TEXT, kind TEXT, name TEXT, "
            "spell_id INTEGER, level_hint INTEGER, raw_listview_json TEXT, source_url TEXT)"
        )
        rows = [
            (782, "Thorns", 14, "Thorns sprout from the friendly target causing 9 Nature "
             "damage to attackers when hit. Lasts 10 min.", "60 Mana"),
            (1075, "Thorns", 24, "Thorns sprout from the friendly target causing 11 Nature "
             "damage to attackers when hit. Lasts 10 min.", "70 Mana"),
            (1126, "Mark of the Wild", 10, "Increases the friendly target's armor by 25 "
             "and all attributes by 3 for 1 hour.", "20 Mana"),
            (5232, "Mark of the Wild", 30, "Increases the friendly target's armor by 100, "
             "all attributes by 5 and all resistances by 2 for 1 hour.", "35 Mana"),
        ]
        for spell_id, name, level, text, cost in rows:
            raw = {
                "id": spell_id, "name": name, "level": level,
                "envChange": {"after": {
                    "name": name, "text": text, "cost": cost,
                    "cast": "Instant", "cooldown": "",
                }},
            }
            conn.execute(
                "INSERT INTO spell_index VALUES (?, 'abilities', ?, ?, ?, ?, ?)",
                ("druid", name, spell_id, level, json.dumps(raw),
                 f"https://example.test/spell/{spell_id}"),
            )
    return db


def test_latest_reactive_rank_and_level_bound(source_db):
    assert latest_reactive_maintenance_rank("DRUID", "Thorns", 9, db_path=source_db) is None
    early = latest_reactive_maintenance_rank("DRUID", "Thorns", 20, db_path=source_db)
    later = latest_reactive_maintenance_rank("druid", "Thorns", 30, db_path=source_db)
    assert (early["spell_id"], early["level"], early["reactive_damage"],
            early["duration_s"], early["mana_cost"]) == (782, 14, 9, 600, 60)
    assert (later["spell_id"], later["reactive_damage"]) == (1075, 11)


def test_latest_stat_rank_and_optional_resistance(source_db):
    assert latest_stat_maintenance_rank("druid", "Mark of the Wild", 9, db_path=source_db) is None
    early = latest_stat_maintenance_rank("DRUID", "Mark of the Wild", 20, db_path=source_db)
    later = latest_stat_maintenance_rank("druid", "Mark of the Wild", 30, db_path=source_db)
    assert (early["spell_id"], early["armor"], early["attributes"],
            early["resistances"], early["duration_s"]) == (1126, 25, 3, 0, 3600)
    assert (later["spell_id"], later["armor"], later["attributes"],
            later["resistances"]) == (5232, 100, 5, 2)
    assert early["acquisition_status"] == "INDEX_TRAINING_HINT_NOT_INDEPENDENTLY_VERIFIED"


@pytest.mark.parametrize(
    "family,reader,prefix",
    [
        ("Thorns", latest_reactive_maintenance_rank, "REACTIVE_AURA"),
        ("Mark of the Wild", latest_stat_maintenance_rank, "STAT_AURA"),
    ],
)
@pytest.mark.parametrize("corruption,expected", [
    ("identity", "{prefix}_SOURCE_IDENTITY_CONFLICT"),
    ("removed", "LATEST_{prefix}_REMOVED"),
    ("missing_after", "{prefix}_NEEDS_UNAMBIGUOUS_AFTER_TOOLTIP"),
    ("unparsed", "UNPARSED_{prefix}_SEMANTICS"),
])
def test_fail_closed_error_codes(source_db, family, reader, prefix, corruption, expected):
    with sqlite3.connect(source_db) as conn:
        row = conn.execute(
            "SELECT rowid,raw_listview_json FROM spell_index "
            "WHERE name=? ORDER BY level_hint DESC LIMIT 1", (family,)
        ).fetchone()
        raw = json.loads(row[1])
        if corruption == "identity":
            raw["id"] += 1
        elif corruption == "removed":
            raw["envChange"]["status"] = "removed"
        elif corruption == "missing_after":
            raw["envChange"]["after"] = None
        else:
            raw["envChange"]["after"]["text"] = "unsupported tooltip"
        conn.execute(
            "UPDATE spell_index SET raw_listview_json=? WHERE rowid=?",
            (json.dumps(raw), row[0]),
        )
    with pytest.raises(ValueError, match=f"^{expected.format(prefix=prefix)}$"):
        reader("druid", family, 30, db_path=source_db)

"""Transitional SQLite source facts do not require the Python GameIR compiler.

This is an import/reader compatibility boundary only. MythicSim Rust remains
the target owner for game facts and legality (#357/#359).
"""

import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_fact_reader_imports_do_not_load_gameir():
    source = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import equipped_weapon_modes, stat_conversions

assert equipped_weapon_modes.DEFAULT_DB is DEFAULT_DB
assert stat_conversions.DEFAULT_DB is DEFAULT_DB
for module in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module

# Existing explicit legacy compiler consumers retain the same source path.
from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DEFAULT_DB
assert LEGACY_DEFAULT_DB is DEFAULT_DB
"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, (
        f"fact-reader import boundary failed: {completed.stdout}\n{completed.stderr}"
    )


def test_fact_reader_explicit_sqlite_results_are_unchanged(tmp_path):
    from src.game.data.forever.equipped_weapon_modes import (
        load_equipped_weapon_mode_facts,
    )
    from src.game.data.forever.stat_conversions import (
        load_mode_resource_capacity_conversions,
        load_mode_stat_conversions,
    )

    db = tmp_path / "facts.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE equipped_weapon_mode_source_facts (
                class_key TEXT, mode_label TEXT, source_stat TEXT,
                damage_source_kind TEXT, operation TEXT, applies_to TEXT,
                authority TEXT, source_url TEXT, source_date TEXT,
                evidence TEXT, capture_id TEXT
            );
            INSERT INTO equipped_weapon_mode_source_facts VALUES (
                'druid', 'cat', 'weapon_dps', 'weapon',
                'replace_flat_dps', 'auto_and_weapon_actions',
                'fixture', 'https://example.invalid/source', '2026-11-03',
                'sourced fixture', 'capture-1'
            );
            CREATE TABLE stat_conversion_source_facts (
                class_key TEXT, target_type TEXT, source_stat TEXT,
                target_id TEXT, mode_label TEXT, coefficient REAL,
                authority TEXT, source_url TEXT, capture_id TEXT
            );
            INSERT INTO stat_conversion_source_facts VALUES
                ('druid', 'stat', 'agility', 'attack_power', 'cat', 1.0,
                 'fixture', 'https://example.invalid/source', 'capture-1'),
                ('druid', 'resource_capacity', 'intellect', 'mana', 'caster',
                 15.0, 'fixture', 'https://example.invalid/source', 'capture-2');
        """)

    weapon = load_equipped_weapon_mode_facts("DRUID", db_path=db)
    assert len(weapon) == 1
    assert (weapon[0].mode_label, weapon[0].operation) == (
        "cat", "replace_flat_dps"
    )
    stat = load_mode_stat_conversions("DRUID", db_path=db)
    capacity = load_mode_resource_capacity_conversions("druid", db_path=db)
    assert len(stat) == len(capacity) == 1
    assert (stat[0].source_stat, stat[0].target_stat, stat[0].coefficient) == (
        "agility", "attack_power", 1.0
    )
    assert (capacity[0].source_stat, capacity[0].target_stat,
            capacity[0].coefficient) == ("intellect", "mana", 15.0)


def test_repair_planner_import_is_source_only():
    """The operator-facing repair planner must not eagerly import GameIR."""
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from tools import plan_forever_ability_repair as planner

assert planner.DEFAULT_DB is DEFAULT_DB
assert callable(planner.plan)
for module in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert module not in sys.modules, module

from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DEFAULT_DB
assert LEGACY_DEFAULT_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    help_result = subprocess.run(
        [sys.executable, "tools/plan_forever_ability_repair.py", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--class-key" in help_result.stdout
    assert "--db" in help_result.stdout


def test_repair_planner_keeps_staged_db_and_fail_closed_contract(tmp_path):
    """The import change must not alter source IDs, commands or rejects."""
    import json
    import pytest
    from tools.plan_forever_ability_repair import plan

    path = tmp_path / "staged.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE capture_batches (
                batch_id TEXT, status TEXT, captured_at TEXT
            );
            CREATE TABLE capture_lists (
                batch_id TEXT, class_key TEXT, kind TEXT, complete INTEGER,
                blocked_reason TEXT, expected_count INTEGER, captured_count INTEGER
            );
            CREATE TABLE spell_index (
                spell_id INTEGER, name TEXT, rank_hint TEXT, level_hint INTEGER,
                source_url TEXT, raw_listview_json TEXT, batch_id TEXT,
                class_key TEXT, kind TEXT
            );
            CREATE TABLE ability_semantic_source_facts (
                spell_id INTEGER, class_key TEXT, semantic_type TEXT,
                required_mode_id TEXT, gcd_s REAL
            );
            INSERT INTO capture_batches VALUES ('source-batch', 'complete', '2026-11-03');
            INSERT INTO capture_lists VALUES (
                'source-batch', 'druid', 'abilities', 1, NULL, 2, 2
            );
        """)
        rows = (
            (101, "Sourced action", 10, None),
            (102, "Verified action", 12, "direct_damage"),
        )
        for spell_id, name, level, semantic in rows:
            payload = json.dumps({"envChange": {"after": {
                "text": "Verified source text", "cost": "10 Mana", "cast": "Instant"
            }}})
            connection.execute(
                "INSERT INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)",
                (spell_id, name, "Rank 1", level,
                 f"https://www.wowhead.com/forever/spell={spell_id}",
                 payload, "source-batch", "druid", "abilities"),
            )
            if semantic:
                connection.execute(
                    "INSERT INTO ability_semantic_source_facts VALUES (?,?,?,?,?)",
                    (spell_id, "druid", semantic, None, 1.5),
                )

    report = plan(class_key="DRUID", level=20, db_path=path)
    assert report["class_key"] == "druid"
    assert report["repair_count"] == 1
    assert report["detail_capture_spell_ids"] == [101]
    assert report["existing_fetcher"]["command_argv"] == [
        "python", "tools/capture_forever_abilities_sqlite.py",
        "--db", str(path), "--batch-id", "source-batch",
        "--details-only", "--spell-ids", "101",
    ]
    assert not report["complete_action_coverage"]

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE capture_lists SET complete=0")
    with pytest.raises(ValueError, match="no unambiguous complete source-index batch"):
        plan(class_key="druid", level=20, db_path=path)


def test_capture_ingesters_import_without_loading_legacy_gameir():
    """The six source-only ingestion CLIs need the SQLite path, not GameIR."""
    code = """
import importlib
import sys

from src.game.data.forever.source_db_scope import DEFAULT_DB

names = (
    'wf247_ingest_outgoing',
    'wf250_ingest_source_capture',
    'wf252_ingest_companions',
    'wf253_ingest_seal',
    'wf254_ingest_paladin_talents',
    'wf257_ingest_flash_recovery',
)
for name in names:
    module = importlib.import_module('tools.' + name)
    assert module.DEFAULT_DB is DEFAULT_DB, name
    assert callable(module.ingest), name

for name in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert name not in sys.modules, name

from src.game.data.forever.sqlite_talents import DEFAULT_DB as legacy_default
assert legacy_default is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_outgoing_capture_ingest_explicit_db_remains_idempotent(tmp_path):
    """A path-only import change must not alter persisted source/proxy facts."""
    from tools.wf247_ingest_outgoing import ingest

    db = tmp_path / "outgoing.sqlite"
    assert ingest(db) == (60, 4)
    assert ingest(db) == (60, 4)
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM outgoing_combat_profile_source_facts"
        ).fetchone()[0] == 60
        assert conn.execute(
            "SELECT COUNT(*) FROM target_armor_debuff_source_facts"
        ).fetchone()[0] == 4
        assert conn.execute(
            "SELECT source_status FROM outgoing_combat_profile_source_facts "
            "WHERE scenario_key='ordinary_melee_classic_proxy' AND level=20"
        ).fetchone()[0] == "classic_proxy_not_forever_server_verified"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_verified_source_capture_staged_ingest_remains_idempotent(tmp_path):
    """The source-only capture CLI still honors explicit staging paths."""
    import json

    from tools.wf250_ingest_source_capture import ingest

    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({
        "captured_at": "2026-11-03",
        "capture_id": "boundary-test",
        "granted_actions": [],
        "spell_ranks": [{
            "class_key": "mage",
            "spell_id": 1234,
            "cast_time_s": 1.5,
            "mana_cost": 20,
            "cooldown_s": 0,
            "tooltip_text": "Source fixture",
            "source_url": "https://example.invalid/spell/1234",
            "source_build": "fixture-build",
            "spell_power_coefficient": 0.5
        }],
        "talents": []
    }), encoding="utf-8")
    db = tmp_path / "capture.sqlite"
    ingest(db=db, capture=capture)
    ingest(db=db, capture=capture)
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT spell_id, spell_power_coefficient "
            "FROM verified_spell_rank_facts"
        ).fetchall() == [(1234, 0.5)]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_historical_capture_stage_clis_avoid_gameir():
    """Source-only operators must not load the transitional Python compiler."""
    code = """
import importlib
import sys

from src.game.data.forever.source_db_scope import DEFAULT_DB

operations = {
    'wf251_ingest_two_classes': 'ingest',
    'wf255_ingest_command': 'ingest',
    'wf256_ingest_seals': 'ingest',
    'wf257_ingest_paladin_corridor': 'ingest',
    'wf381_stage_mage_talent_positions': 'stage',
}
for name, function_name in operations.items():
    module = importlib.import_module('tools.' + name)
    assert module.DEFAULT_DB is DEFAULT_DB, name
    assert callable(getattr(module, function_name)), name

for name in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert name not in sys.modules, name

# Existing compiler clients retain the identical default database identity.
from src.game.data.forever.sqlite_talents import DEFAULT_DB as legacy_default
assert legacy_default is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_historical_mage_stager_keeps_explicit_db_and_source_identity(tmp_path):
    """The import-only change must preserve the staged SQLite output contract."""
    import hashlib
    import json

    import pytest
    from tools.wf381_stage_mage_talent_positions import stage

    base = tmp_path / "canonical.sqlite"
    source = tmp_path / "talent_positions.json"
    target = tmp_path / "staged.sqlite"
    with sqlite3.connect(base) as db:
        db.execute("CREATE TABLE keep_me (value TEXT)")
        db.execute("INSERT INTO keep_me VALUES ('canonical')")
    payload = {
        "schema": "forever_source_talent_positions_v1",
        "source_build": "fixture-build",
        "class_key": "mage",
        "min_level": 30,
        "talents": [{"name": "fixture talent"}],
    }
    source.write_text(json.dumps(payload), encoding="utf-8")
    original = base.read_bytes()
    result = stage(source=source, base=base, target=target)

    assert base.read_bytes() == original
    assert result["base_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["positions"] == 1
    assert result["source_build"] == "fixture-build"
    assert result["sqlite_integrity"] == "ok"
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT value FROM keep_me").fetchone() == ("canonical",)
        row = db.execute(
            "SELECT class_key, source_build, min_level, source_json "
            "FROM checkpoint_talent_source_positions"
        ).fetchone()
        assert row[:3] == ("mage", "fixture-build", 30)
        assert json.loads(row[3]) == payload
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)

    with pytest.raises(ValueError, match="STAGED_TALENT_SOURCE_DB_MUST_NOT_BE_OVERWRITTEN"):
        stage(source=source, base=base, target=base)
    assert base.read_bytes() == original


def test_armor_source_rule_reader_import_does_not_load_gameir():
    """Source-only armor facts must not import the transitional talent compiler."""
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever.armor_conversions import (
    DEFAULT_DB as ARMOR_DB, load_armor_rules, source_enrich_armor,
)
assert ARMOR_DB is DEFAULT_DB
assert callable(load_armor_rules) and callable(source_enrich_armor)
for name in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert name not in sys.modules, name

# Existing legacy users must still resolve the same source database.
from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DB
assert LEGACY_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_armor_source_reader_preserves_explicit_sqlite_and_fail_closed(tmp_path):
    """A source-only import change must retain verified schema and value checks."""
    import pytest
    from src.game.data.forever.armor_conversions import load_armor_rules

    path = tmp_path / "armor.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE armor_conversion_source_facts (
                class_key TEXT, scope TEXT, mode_label TEXT, source_stat TEXT,
                target_stat TEXT, operation TEXT, coefficient REAL,
                authority TEXT, source_url TEXT, source_date TEXT,
                evidence TEXT, capture_id TEXT
            );
        """)
        db.execute(
            "INSERT INTO armor_conversion_source_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ('druid', 'actor', '', 'agility', 'armor', 'add_stat_scaled', 2.0,
             'fixture', 'https://example.invalid/armor', '2026-11-03',
             'explicit source fixture', 'armor-1'),
        )

    rows = load_armor_rules("DRUID", db_path=path)
    assert len(rows) == 1
    assert (rows[0].class_key, rows[0].source_stat, rows[0].coefficient) == (
        "druid", "agility", 2.0
    )
    assert load_armor_rules("mage", db_path=path) == ()

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE armor_conversion_source_facts SET coefficient=-1.0"
        )
    with pytest.raises(ValueError, match="invalid canonical armor source fact"):
        load_armor_rules("druid", db_path=path)

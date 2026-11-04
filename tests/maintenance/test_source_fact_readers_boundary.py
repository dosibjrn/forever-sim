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
    """The remaining source-only ingestion CLIs need SQLite, not GameIR."""
    code = """
import importlib
import sys

from src.game.data.forever.source_db_scope import DEFAULT_DB

names = (
    'wf247_ingest_outgoing',
    'wf252_ingest_companions',
    'wf253_ingest_seal',
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


def test_primary_stat_source_reader_import_is_independent_of_gameir():
    """Reading sourced conversion facts must not construct the legacy game model."""
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever.primary_stat_conversions import (
    DEFAULT_DB as PRIMARY_DB, load_primary_stat_conversions,
    source_enrich_primary_stats, converted_stat_amount,
)
assert PRIMARY_DB is DEFAULT_DB
assert callable(load_primary_stat_conversions)
assert callable(source_enrich_primary_stats)
assert converted_stat_amount(
    {'coefficient': 2.0, 'operation': 'linear'}, 3.0
) == 6.0
for name in (
    'src.game.data.forever.sqlite_talents',
    'src.game.model.ir',
    'src.game.runtime.simulator',
):
    assert name not in sys.modules, name

from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DB
assert LEGACY_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_primary_stat_source_reader_retains_staged_db_and_fail_closed(tmp_path):
    """Import decoupling must not change source identity or coefficient validation."""
    import pytest
    from src.game.data.forever.primary_stat_conversions import (
        load_primary_stat_conversions,
    )

    path = tmp_path / "primary_stats.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE actor_stat_conversion_source_facts (
                class_key TEXT, source_stat TEXT, target_type TEXT,
                target_id TEXT, coefficient REAL, baseline TEXT,
                operation TEXT, threshold REAL, below_coefficient REAL,
                authority TEXT, source_url TEXT, source_date TEXT,
                evidence TEXT, capture_id TEXT
            );
        """)
        db.execute(
            "INSERT INTO actor_stat_conversion_source_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('druid', 'strength', 'stat', 'attack_power', 2.0, 'total',
             'linear', None, None, 'fixture',
             'https://example.invalid/primary-stat', '2026-11-03',
             'explicit source fixture', 'primary-1'),
        )

    rows = load_primary_stat_conversions("DRUID", db_path=path)
    assert len(rows) == 1
    assert (rows[0].source_stat, rows[0].target_id, rows[0].coefficient) == (
        "strength", "attack_power", 2.0
    )
    assert load_primary_stat_conversions("mage", db_path=path) == ()

    with sqlite3.connect(path) as db:
        db.execute("UPDATE actor_stat_conversion_source_facts SET coefficient=-2.0")
    with pytest.raises(ValueError, match="invalid or conflicting"):
        load_primary_stat_conversions("druid", db_path=path)

def test_source_enricher_imports_do_not_load_legacy_talent_compiler():
    """Three live GameIR enrichers need a SQLite path, not the talent compiler."""
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import (
    mode_resource_facts, source_incoming_world, source_companions,
)

for module in (mode_resource_facts, source_incoming_world, source_companions):
    assert module.DEFAULT_DB is DEFAULT_DB, module.__name__

# GameIR remains live in these overlays; only the unnecessary compiler edge
# is removed. Never claim the entire native migration is complete.
assert 'src.game.model.ir' in sys.modules
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DB
assert LEGACY_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_enricher_sqlite_and_fail_closed_behavior(tmp_path):
    """A path-only migration preserves real SQLite reads and source rejects."""
    from types import SimpleNamespace

    import pytest
    from src.game.data.forever.mode_resource_facts import apply_mode_resource_facts
    from src.game.data.forever.source_companions import source_enrich_companions
    from src.game.data.forever.source_incoming_world import source_enrich_incoming_world

    db = tmp_path / "source.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE mode_resource_transition_source_facts (
                class_key TEXT, mode_label TEXT, resource_id TEXT,
                on_enter TEXT, on_exit TEXT, authority TEXT,
                source_url TEXT, capture_id TEXT, source_build TEXT,
                evidence_text TEXT
            );
            CREATE TABLE companion_family_source_facts (
                family_key TEXT, class_key TEXT, min_level INTEGER, max_level INTEGER
            );
        """)

    # A source snapshot with no applicable rows is a no-op, not invented data.
    mode = SimpleNamespace(label="Cat Form", resource_rules=(), provenance=())
    assert apply_mode_resource_facts("druid", (mode,), db_path=db) == (mode,)
    ir = SimpleNamespace(actor=SimpleNamespace(metadata={
        "class_key": "druid", "level": 20,
    }))
    assert source_enrich_companions(ir, db_path=db) is ir

    # A fact referencing an unavailable resource must remain fail-closed.
    with sqlite3.connect(db) as connection:
        connection.execute(
            "INSERT INTO mode_resource_transition_source_facts "
            "(class_key,mode_label,resource_id,on_enter,on_exit) "
            "VALUES (?,?,?,?,?)",
            ("druid", "cat_form", "unavailable", "preserve", "preserve"),
        )
    with pytest.raises(ValueError, match="unavailable resource"):
        apply_mode_resource_facts("druid", (mode,), db_path=db)

    # No health resource => no sourced incoming-attack synthesis or DB read.
    world = SimpleNamespace(incoming_attacks=(), resources=())
    assert source_enrich_incoming_world(world) is world


def test_source_action_overlay_imports_do_not_load_talent_compiler():
    """Live GameIR overlays need a SQLite path, not the legacy talent compiler."""
    code = """
import sys
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import (
    source_area_overlay, source_reactive_control,
    source_stealth_actions, source_timed_auras,
)

for overlay in (
    source_area_overlay, source_reactive_control,
    source_stealth_actions, source_timed_auras,
):
    assert overlay.DEFAULT_DB is DEFAULT_DB, overlay.__name__

# These overlays are still live GameIR consumers. This check only proves
# the independent legacy compiler is no longer loaded just for a path.
assert 'src.game.model.ir' in sys.modules
assert 'src.game.data.forever.sqlite_talents' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules

from src.game.data.forever.sqlite_talents import DEFAULT_DB as LEGACY_DB
assert LEGACY_DB is DEFAULT_DB
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_action_overlays_keep_selected_sqlite_and_fail_closed(tmp_path):
    """A source-path refactor preserves no-op and invalid-fact behavior."""
    from types import SimpleNamespace
    import pytest

    from src.game.data.forever.source_db_scope import ability_source_scope
    from src.game.data.forever.source_area_overlay import source_enrich_area_actions
    from src.game.data.forever.source_reactive_control import source_reactive_control_actions
    from src.game.data.forever.source_stealth_actions import source_stealth_actions
    from src.game.data.forever.source_timed_auras import source_enrich_timed_auras

    db = tmp_path / "selected_source.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE spell_index (
                class_key TEXT, kind TEXT, level_hint INTEGER, spell_id INTEGER,
                name TEXT, raw_listview_json TEXT, source_url TEXT
            );
            CREATE TABLE sourced_timed_aura_actions (
                class_key TEXT, min_level INTEGER, family_key TEXT
            );
            CREATE TABLE sourced_aura_consumers (
                class_key TEXT, min_level INTEGER, family_key TEXT
            );
        """)
    ir = SimpleNamespace(
        actor=SimpleNamespace(metadata={"class_key": "druid", "level": 20}),
        actions=(),
    )

    # These real SQLite readers must not synthesize game effects from absent
    # rows, and the three scope-aware readers must honor the selected DB.
    with ability_source_scope(db):
        assert source_enrich_area_actions(ir) is ir
        assert source_reactive_control_actions(
            ir, class_key="druid", level=20,
        ) is ir
        assert source_stealth_actions(
            ir, class_key="druid", level=20,
        ) is ir
    assert source_enrich_timed_auras(ir, db_path=db) is ir

    # Existing malformed source evidence must still fail closed.
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE verified_spell_area_facts (
                spell_id INTEGER, radius_yards REAL, center TEXT,
                source_url TEXT, source_build TEXT
            );
            INSERT INTO verified_spell_area_facts VALUES (
                100, -2.0, 'actor', 'https://example.invalid/spell', 'fixture'
            );
        """)
    with ability_source_scope(db):
        with pytest.raises(ValueError, match="INVALID_VERIFIED_SOURCE_AREA_FACT"):
            source_enrich_area_actions(ir)



def test_mode_resource_facts_import_and_execution_do_not_load_gameir(tmp_path):
    """Mode transition facts need only generic dataclass structure, not GameIR."""
    db = tmp_path / "mode_resource.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            CREATE TABLE mode_resource_transition_source_facts (
                class_key TEXT, mode_label TEXT, resource_id TEXT,
                on_enter TEXT, on_exit TEXT, authority TEXT,
                source_url TEXT, capture_id TEXT, source_build TEXT,
                evidence_text TEXT
            );
            INSERT INTO mode_resource_transition_source_facts VALUES (
                'druid', 'cat_form', 'mana', 'reset_to_zero', 'preserve',
                'fixture', 'https://example.invalid/mode', 'mode-1',
                '70338', 'explicit sourced transition'
            );
        """)

    code = """
import sys
from dataclasses import dataclass
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.game.data.forever import mode_resource_facts

assert mode_resource_facts.DEFAULT_DB is DEFAULT_DB
assert callable(mode_resource_facts.apply_mode_resource_facts)
assert 'src.game.model.ir' not in sys.modules

@dataclass(frozen=True)
class ResourceRule:
    resource_id: str
    on_enter: str
    on_exit: str

@dataclass(frozen=True)
class Mode:
    label: str
    resource_rules: tuple
    provenance: tuple

mode = Mode(
    label='Cat Form',
    resource_rules=(ResourceRule('mana', 'preserve', 'preserve'),),
    provenance=(),
)
updated, = mode_resource_facts.apply_mode_resource_facts(
    'DRUID', (mode,), db_path=sys.argv[1],
)
assert updated.resource_rules == (ResourceRule('mana', 'reset_to_zero', 'preserve'),)
assert updated.provenance == ({
    'authority': 'fixture',
    'source_url': 'https://example.invalid/mode',
    'capture_id': 'mode-1',
    'source_build': '70338',
    'evidence_text': 'explicit sourced transition',
},)
assert 'src.game.model.ir' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(db)], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"mode resource import boundary failed: {result.stdout}\n{result.stderr}"
    )

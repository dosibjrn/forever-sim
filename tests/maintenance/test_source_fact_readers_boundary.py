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

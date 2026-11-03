"""Source-only enemy melee-AP observation tooling must not import legacy GameIR.

The executable action builder is deliberately retained for live legacy callers
until a verified selected-native replacement exists (#357/#359).
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_enemy_ap_observation_ingest_and_world_source_reader_are_game_ir_free():
    code = r"""
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from src.game.data.forever import source_enemy_melee_ap_debuff as ap
from src.game.data.forever.source_db_scope import DEFAULT_DB

assert ap.DEFAULT_DB is DEFAULT_DB

source_url = 'https://example.test/forever/spell/99'
source = {
    'id': 99,
    'envChange': {'after': {
        'name': 'Demoralizing Roar',
        'text': "The bear roars, decreasing nearby enemies' melee attack power by 48. Lasts 30 sec.",
        'cost': '10 Rage', 'cast': 'Instant', 'cooldown': '',
    }},
}
row = {
    'raw_listview_json': json.dumps(source),
    'spell_id': 99, 'class_key': 'druid', 'name': 'Demoralizing Roar',
    'level_hint': 20, 'source_url': source_url,
}
observation = {
    'spell_id': 99, 'class_key': 'druid', 'name': 'Demoralizing Roar',
    'source_url': source_url, 'geometry_source_url': 'https://example.test/classic/roar',
    'required_mode_id': 'bear', 'gcd_s': 1.5, 'radius_yards': 10.0,
}
assert ap._values(row, observation) == (20, 'bear', 'rage', 10.0, 1.5, 10.0, 48.0, 30.0)
try:
    ap._values(row, {**observation, 'source_url': 'https://invalid.test/spell'})
except ValueError as exc:
    assert str(exc) == 'SOURCED_ENEMY_AP_PROVENANCE_IDENTITY_MISMATCH'
else:
    raise AssertionError('mismatched provenance was accepted')

with TemporaryDirectory() as tmp:
    db_path = Path(tmp) / 'abilities.sqlite'
    obs_path = Path(tmp) / 'observations.json'
    with sqlite3.connect(db_path) as db:
        db.execute('''CREATE TABLE spell_index (
            class_key TEXT, spell_id INTEGER, kind TEXT, name TEXT,
            level_hint INTEGER, raw_listview_json TEXT, source_url TEXT)''')
        db.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?)',
                   ('druid', 99, 'abilities', row['name'], 20,
                    row['raw_listview_json'], source_url))
    obs_path.write_text(json.dumps({
        'schema': 'source_enemy_melee_ap_debuff_observation_v1',
        'observations': [observation]
    }))
    ap.ingest(db_path, obs_path)
    with sqlite3.connect(db_path) as db:
        result = db.execute(
            'SELECT ap_reduction,duration_s,mode_id,cost_resource FROM source_enemy_melee_ap_debuff_facts'
        ).fetchone()
    assert result == (48.0, 30.0, 'bear', 'rage')

@dataclass(frozen=True)
class Attack:
    school: str
    metadata: dict

@dataclass(frozen=True)
class IR:
    incoming_attacks: tuple

original = IR((
    Attack('physical', {'representative_swing_s': 2.0}),
    Attack('nature', {'representative_swing_s': 2.0}),
))
enriched = ap.source_enrich_enemy_melee_ap_incoming(original)
assert original.incoming_attacks[0].metadata == {'representative_swing_s': 2.0}
assert enriched.incoming_attacks[0].metadata['melee_ap_per_dps'] == 14.0
assert 'melee_ap_per_dps' not in enriched.incoming_attacks[1].metadata

for name in ('src.game.model.ir', 'src.game.data.forever.sqlite_talents',
             'src.game.runtime.simulator'):
    assert name not in sys.modules, name
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, text=True,
        capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_enemy_ap_legacy_source_builder_stays_live():
    from src.game.data.forever.registry import build_game_ir_slice

    for class_key, level in (("hunter", 10), ("paladin", 20)):
        ir = build_game_ir_slice(class_key=class_key, level=level)
        assert ir is not None
        assert ir.actor.metadata["class_key"] == class_key
        assert ir.actions

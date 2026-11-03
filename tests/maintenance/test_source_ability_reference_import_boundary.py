"""The source-action reference and strict tooltip parser are not GameIR loaders.

The approved native Rust engine remains the target game-rules owner. The
legacy source_ability_actions compiler is still live until migrated (#357/#359).
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_source_action_reference_and_parser_import_without_gameir():
    source = r"""
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from src.game.data.forever import source_ability_semantics as source
from src.game.data.forever.source_db_scope import DEFAULT_DB

assert source.DEFAULT_DB is DEFAULT_DB
header = ('Finishing move that causes damage over time. Damage increases '
          'per combo point and by your Attack Power:')
text = header + '\n' + '\n'.join(
    f'{n} point: {n * 20} damage over 12 sec.' for n in range(1, 6))
ladder, duration = source.parse_resource_scaled_periodic_ladder(text)
assert ladder == {n: float(n * 20) for n in range(1, 6)}
assert duration == 12.0
try:
    source.parse_resource_scaled_periodic_ladder(text + '\n6 point: 140 damage over 12 sec.')
except ValueError:
    pass
else:
    raise AssertionError('extra unparsed rank was accepted')

with TemporaryDirectory() as tmp:
    db = Path(tmp) / 'source.sqlite'
    with sqlite3.connect(db) as conn:
        conn.executescript('''
            CREATE TABLE spell_index (
                spell_id INTEGER, name TEXT, level_hint INTEGER,
                source_url TEXT, raw_listview_json TEXT,
                class_key TEXT, kind TEXT
            );
            CREATE TABLE ability_semantic_source_facts (
                spell_id INTEGER, class_key TEXT, semantic_type TEXT
            );
        ''')
        conn.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?)',
                     (900, 'Claw', 20, 'https://example.invalid/spell/900',
                      json.dumps({'envChange': {'after': {'cost': '30 Energy'}}}),
                      'druid', 'abilities'))
        conn.execute('INSERT INTO ability_semantic_source_facts VALUES (?,?,?)',
                     (900, 'druid', 'direct_damage'))
    assert source.latest_source_action_ref('druid', 'claw', 19, db_path=db) is None
    ref = source.latest_source_action_ref('DRUID', 'CLAW', 20, db_path=db)
    assert ref.id == 'source_spell:900'
    assert ref.spell_id == 900
    assert ref.cost_resource == 'energy' and ref.cost_amount == 30.0
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=900',
                     (json.dumps({'envChange': {'after': {'cost': '30 Unknown'}}}),))
    try:
        source.latest_source_action_ref('druid', 'claw', 20, db_path=db)
    except ValueError as exc:
        assert 'source action cost unparsed' in str(exc)
    else:
        raise AssertionError('invalid cost was accepted')

for name in ('src.game.model.ir', 'src.game.data.forever.sqlite_talents',
             'src.game.runtime.simulator'):
    assert name not in sys.modules, name

# Legacy consumers still receive the same executable GameIR ResourceCost.
costs = ref.costs
from src.game.model.ir import ResourceCost
assert len(costs) == 1
assert isinstance(costs[0], ResourceCost)
assert costs[0].resource_id == 'energy' and costs[0].amount == 30.0
"""
    completed = subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT,
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_legacy_source_compiler_remains_available_for_multiple_classes():
    from src.game.data.forever.registry import build_game_ir_slice

    for class_key, level in (("hunter", 10), ("paladin", 20)):
        result = build_game_ir_slice(class_key=class_key, level=level)
        assert result is not None
        assert result.actor.metadata["class_key"] == class_key
        assert result.actions

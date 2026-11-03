"""Talent-position source readers must not eagerly load legacy GameIR.

The existing staged rank compiler is still exercised until a native Rust
consumer replaces it, per architecture issues #357/#359.
"""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_position_import_and_missing_snapshot_do_not_load_gameir():
    code = """
import sqlite3
import sys
from src.game.data.forever.source_checkpoint_talent_positions import (
    _rank_l0_provenance, apply_staged_talent_positions,
)
assert _rank_l0_provenance(None, 1) is None
assert _rank_l0_provenance({
    'features': [{'rank_values': [2.0], 'domain': 'damage', 'target': 'spell',
                  'condition': 'always'}],
    'source_url': 'https://example.invalid/source',
    'context_uncertainty': 'partial',
}, 1)['effects'][0]['sourced_value'] == 2.0
conn = sqlite3.connect(':memory:')
assert apply_staged_talent_positions(conn, 'druid', 20, ()) == ((), None)
assert 'src.game.model.ir' not in sys.modules
assert 'src.game.runtime.simulator' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_staged_talent_compiler_keeps_source_ranks_and_fail_closed_sha():
    from hashlib import sha256
    import json
    import sqlite3

    import pytest
    from src.game.data.forever.source_checkpoint_talent_positions import (
        apply_staged_talent_positions,
    )
    from src.game.model.ir import TalentDefinition, TalentRankDefinition

    conn = sqlite3.connect(':memory:')
    conn.execute(
        'CREATE TABLE checkpoint_talent_source_positions '
        '(class_key TEXT, source_build TEXT, min_level INTEGER, '
        'source_sha256 TEXT, source_json TEXT)'
    )
    data = {
        'schema': 'forever_source_talent_positions_v1',
        'class_key': 'druid',
        'source_build': '70338',
        'source_generated': True,
        'source_url': 'https://example.invalid/staged-talents',
        'min_level': 20,
        'points_per_row': 5,
        'talents': [{
            'talent_id': 'naturalist',
            'name': 'Naturalist',
            'tree_key': 'restoration',
            'row': 0,
            'column': 0,
            'max_rank': 2,
            'points_required': 0,
            'source_url': 'https://example.invalid/naturalist',
            'source_talent_id': 11,
            'spell_id': 100,
            'requires': [],
        }],
        'rank_l0': {
            'naturalist': {
                'source_url': 'https://example.invalid/naturalist',
                'context_uncertainty': 'partial observation',
                'features': [{
                    'domain': 'spell', 'target': 'effect', 'condition': 'always',
                    'rank_values': [2.0, 4.0],
                }],
            },
        },
    }
    raw = json.dumps(data, sort_keys=True)
    digest = sha256(raw.encode()).hexdigest()
    conn.execute(
        'INSERT INTO checkpoint_talent_source_positions VALUES (?,?,?,?,?)',
        ('druid', '70338', 20, digest, raw),
    )
    original = TalentDefinition(
        id='naturalist', name='Naturalist', tree_key='restoration', max_rank=2,
    )
    talents, receipt = apply_staged_talent_positions(
        conn, 'druid', 20, (original,),
    )
    assert len(talents) == 1
    assert all(isinstance(r, TalentRankDefinition) for r in talents[0].ranks)
    assert [r.rank for r in talents[0].ranks] == [1, 2]
    assert all(not r.modifiers for r in talents[0].ranks)
    assert [r.provenance['checkpoint_source_l0']['effects'][0]['sourced_value']
            for r in talents[0].ranks] == [2.0, 4.0]
    assert talents[0].metadata['source_position_only'] is True
    assert receipt['positions'] == 1
    assert receipt['rank_effects_staged'] == 2

    conn.execute(
        'UPDATE checkpoint_talent_source_positions SET source_sha256=?',
        ('invalid',),
    )
    with pytest.raises(ValueError, match='STAGED_TALENT_POSITION_SHA_MISMATCH'):
        apply_staged_talent_positions(conn, 'druid', 20, (original,))

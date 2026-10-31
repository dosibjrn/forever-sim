"""WF307 regression: overlapping WF305/306 sources survive the same clean .289 merge."""
import sqlite3
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_partial_l1 import partial_source_action, PartialSourceEvidenceError
from src.game.data.forever.sqlite_talents import DEFAULT_DB


def test_same_source_ir_preserves_paid_thorns_and_l1_periodic_only():
    ir = build_game_ir_slice(class_key='druid', level=20)
    source_thorns = next(a for a in ir.actions if a.id == 'source_spell:782')
    assert source_thorns.effects[0].duration_s == 600
    assert source_thorns.costs[0].amount == 60
    l1, ledger = partial_source_action(ir, class_key='druid', spell_id=8921, fragment_kind='periodic_total')
    assert l1.metadata['never_l2_legal'] is True
    assert l1.effects[0].total_base_damage == 12
    assert l1.effects[0].tick_interval_s == l1.effects[0].duration_s
    assert ledger['partial_not_l2'] is True


def test_spell_dependency_observations_retained_not_promoted_to_gameplay():
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT source_spell_id,referenced_spell_id,observation_status '
                          'FROM source_spell_dependency_observations WHERE class_key=?',('druid',)).fetchall()
    assert len(rows) == 4
    assert all(row[2] != 'verified_html' for row in rows)

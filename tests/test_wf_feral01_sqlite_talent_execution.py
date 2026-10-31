from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import load_sqlite_talents, DEFAULT_DB
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations, search_talent_allocations
from src.v2.source_mode_search import evaluate_discovered_mode_search


def test_sqlite_inventory_has_every_indexed_family_and_all_three_trees():
    ir = build_source_slice(20)
    coverage = ir.provenance['talent_sqlite_coverage']
    assert coverage['captured'] == coverage['expected'] == 52
    assert len(ir.talents) == 52
    assert len({t.id for t in ir.talents}) == 52
    assert {t.tree_key for t in ir.talents} == {'balance', 'feral', 'restoration'}
    assert coverage['complete'] is False
    assert len({row['talent_id'] for row in coverage['blockers']}) == 52
    assert ir.provenance['talent_authority'] == 'canonical_sqlite_forever_abilities'


def test_source_index_drives_family_count_no_hardcoded_list(tmp_path):
    clone = tmp_path / 'abilities.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    c = sqlite3.connect(clone)
    # Removing a captured row is an ingestion failure, not silent 51/52 coverage.
    c.execute("DELETE FROM spell_index WHERE class_key='druid' AND kind='talents' AND spell_id=16934")
    c.commit(); c.close()
    with pytest.raises(ValueError, match='capture count mismatch'):
        load_sqlite_talents('druid', action_families={'claw'}, db_path=clone)


def test_feral_first_rank_changes_real_level20_actions_without_hardcoded_talent_list():
    ir = build_source_slice(20)
    talent = next(t for t in ir.talents if t.id == 'ferocity')
    assert talent.tree_key == 'feral'
    assert talent.metadata['sqlite_spell_id'] == 16934
    assert talent.metadata['rank_cap_verified'] is True
    assert talent.metadata['tree_position_verified'] is False
    assert {'maul', 'primal_bite', 'rake'} <= set(talent.metadata['unavailable_action_targets'])
    before = {a.family_key: a.costs[0].amount for a in ir.actions if a.family_key in ('claw', 'swipe')}
    modified, application = apply_talent_selection(ir, {'ferocity': 1}, level=20)
    after = {a.family_key: a.costs[0].amount for a in modified.actions if a.family_key in ('claw', 'swipe')}
    assert before == {'swipe': 20.0, 'claw': 45.0}
    assert after == {'swipe': 19.0, 'claw': 44.0}
    assert {x['action_id'] for x in application.applied_modifiers} == {'swipe:16', 'claw:20'}
    assert any(x['talent_id'] == 'ferocity' for x in ir.provenance['talent_sqlite_coverage']['blockers'])
    allocations, truncated = enumerate_legal_talent_allocations(_historical_234_talent_slice(ir), level=20)
    assert not truncated and len(allocations) == 417
    assert {'ferocity': 1} in allocations


def test_unknown_talent_effect_is_not_a_zero_cost_noop():
    ir = build_source_slice(20)
    unknown = next(t for t in ir.talents if not t.ranks or not any(r.modifiers for r in t.ranks))
    with pytest.raises(ValueError, match='(no canonical rank record|unsupported talent effect)'):
        validate_talent_selection(ir, {unknown.id: 1}, level=20)
    result = search_talent_allocations(ir, level=20, evaluate=lambda s: (1.0, {}))
    assert unknown.id in result.blocked_talent_ids
    assert result.complete_source_talent_coverage is False


def test_feral_modifier_reaches_production_policy_scorer_without_fake_speedup():
    ir = build_source_slice(20)
    modified, _ = apply_talent_selection(ir, {'ferocity': 1}, level=20)
    baseline = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=ir,
                                                max_policies_per_path=24)
    improved = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=modified,
                                                max_policies_per_path=24)
    b = sorted(row['seconds_per_mob'] for row in [baseline['winner'], *baseline['alternatives']])
    m = sorted(row['seconds_per_mob'] for row in [improved['winner'], *improved['alternatives']])
    assert len(b) == len(m)
    # The old expectation that -1 Energy *must* cross a kill-time threshold
    # predates the .237 Cat entry reset. With zero initial Energy this small
    # cost reduction need not alter any discrete action count. The action-cost
    # mutation is independently asserted above; do not manufacture a DPS gain.
    assert all(new <= old + 1e-9 for old, new in zip(b, m))
    assert improved['winner']['seconds_per_mob'] == pytest.approx(baseline['winner']['seconds_per_mob'])


def _historical_234_talent_slice(ir):
    from dataclasses import replace
    old={'improved_wrath','ferocity','savage_fury','thick_hide','heart_of_the_wild'}
    return replace(ir,talents=tuple(t for t in ir.talents if t.id in old))

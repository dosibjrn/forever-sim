"""TDD: opt-in legacy talent points flow through legality and candidate generation."""
from dataclasses import replace

import pytest

from src.game.model.ir import TalentDefinition, TalentRankDefinition, TalentModifier
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import available_talent_points, validate_talent_selection, apply_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations
from src.game.talent_frontier import source_legal_talent_neighbors


def artificial_catalog():
    # Test-only executable ranks, no fabricated game facts in production.
    base = build_game_ir_slice(class_key='mage', level=30)
    assert base is not None
    def talent(n):
        return TalentDefinition(id=n, name=n, tree_key='fixture', max_rank=5,
            ranks=tuple(TalentRankDefinition(rank=i, modifiers=(TalentModifier(
                kind='actor_stat_flat', target_type='actor_stat',
                target_id='spirit', value=i),)) for i in range(1, 6)),
            metadata={'row': 0})
    return replace(base, talents=tuple(talent(f'fixture_{i}') for i in range(6)))


def test_bonus_is_explicit_opt_in_and_invalid_values_are_rejected():
    assert available_talent_points(30) == 21
    assert available_talent_points(30, bonus_talent_points=5) == 26
    with pytest.raises(ValueError):
        available_talent_points(30, bonus_talent_points=-1)
    with pytest.raises(ValueError):
        available_talent_points(30, bonus_talent_points=True)


def test_same_26_point_allocation_valid_only_with_explicit_bonus():
    ir = artificial_catalog()
    allocation = {f'fixture_{i}':5 for i in range(5)} | {'fixture_5':1}
    with pytest.raises(ValueError, match='budget'):
        validate_talent_selection(ir, allocation, level=30)
    validate_talent_selection(ir, allocation, level=30, bonus_talent_points=5)
    _, report = apply_talent_selection(ir, allocation, level=30, bonus_talent_points=5)
    assert report.available_points == 26
    assert report.spent_points == 26
    with pytest.raises(ValueError, match='budget'):
        validate_talent_selection(ir, {**allocation, 'fixture_5':2}, level=30, bonus_talent_points=5)


def test_bonus_is_real_optimizer_candidate_axis_not_just_validator():
    ir = artificial_catalog()
    # 2 test-only rank-15 families: 256 proposals, so no 5,000-cap
    # false negative when the bonus opens >21-point allocations.
    def long_talent(n):
        return TalentDefinition(id=n, name=n, tree_key='fixture', max_rank=15,
            ranks=tuple(TalentRankDefinition(rank=i, modifiers=(TalentModifier(
                kind='actor_stat_flat', target_type='actor_stat',
                target_id='spirit', value=i),)) for i in range(1,16)),
            metadata={'row':0})
    small = replace(ir, talents=(long_talent('a'), long_talent('b')))
    normal, cutoff0 = enumerate_legal_talent_allocations(small, level=30, max_candidates=5000)
    legacy, cutoff5 = enumerate_legal_talent_allocations(small, level=30, max_candidates=5000,
                                                    bonus_talent_points=5)
    assert not cutoff0 and not cutoff5
    assert all(sum(c.values()) <= 21 for c in normal)
    assert any(sum(c.values()) > 21 for c in legacy)
    incumbent = {f'fixture_{i}':5 for i in range(4)} | {'fixture_4':1}
    normal_neighbors=source_legal_talent_neighbors(ir, incumbent, level=30)
    legacy_neighbors=source_legal_talent_neighbors(ir, incumbent, level=30, bonus_talent_points=5)
    assert not any(sum(dict(n.allocation).values())>21 for n in normal_neighbors['neighbors'])
    assert any(sum(dict(n.allocation).values())>21 for n in legacy_neighbors['neighbors'])

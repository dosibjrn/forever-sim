"""Source-objective exclusions retain their real source and legal-search regressions."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.source_objective_relevance import solo_threat_exclusion
from src.game.talent_execution_coverage import (
    compile_talent_runtime, compile_talent_candidate)
from src.game.talent_frontier import source_legal_talent_neighbors, allocation_key
from src.game.talents import available_talent_points, talented_bonus_for_level
from src.game.data.forever.source_checkpoint_p2 import _witness


@pytest.fixture(scope="module")
def canonical():
    ir = build_game_ir_slice(class_key="druid", level=60)
    compiled, coverage = compile_talent_runtime(ir)
    talent = next(t for t in compiled.talents if t.id == "subtlety")
    assert [r.rank for r in talent.ranks] == [1, 2, 3]
    return compiled, coverage, talent


def test_all_three_actual_source_ranks_are_checked_not_fake_behavior(canonical):
    compiled, coverage, talent = canonical
    for rank, percent in zip(talent.ranks, (10., 20., 30.)):
        assert not rank.modifiers
        checked = solo_threat_exclusion(compiled, rank)
        assert checked is not None
        assert checked["status"] == "DOES_NOT_AFFECT_SIM"
        assert checked["source_rank_percent"] == percent
        assert checked["source_capture_id"]
    assert not any(r["talent_id"] == "subtlety"
                   for r in coverage["missing"])
    assert sum(r["talent_id"] == "subtlety"
               for r in coverage["objective_excluded"]) == 3


def test_exclusion_rejects_other_actors_and_unsupported_source(canonical):
    compiled, _, talent = canonical
    rank = talent.ranks[0]
    assert solo_threat_exclusion(compiled, replace(
        rank, provenance={**rank.provenance,
                          "raw_tooltip": "Reduces damage taken by 10%."})) is None
    assert solo_threat_exclusion(compiled, replace(
        rank, provenance={**rank.provenance, "source": {"url": "https://example.org"}})) is None
    companion = replace(compiled.actor, id="allied_pet")
    assert solo_threat_exclusion(
        replace(compiled, companions=(companion,)), rank) is None
    assert solo_threat_exclusion(
        replace(compiled, timed_summons=(object(),)), rank) is None


def test_objective_neutral_rank_remains_reachable_in_actual_legal_frontier(canonical):
    compiled, _, talent = canonical
    bonus = talented_bonus_for_level(60)
    points = available_talent_points(60, bonus_talent_points=bonus)
    step = int(compiled.provenance["talent_tree_rules"]["points_per_row"])
    witness = _witness(talent, 1, compiled.talents, points, step)
    assert witness is not None and witness["subtlety"] == 1
    prior = dict(witness)
    prior.pop("subtlety")
    frontier = source_legal_talent_neighbors(
        compiled, prior, level=60, bonus_talent_points=bonus)
    assert allocation_key(witness) in {n.allocation for n in frontier["neighbors"]}
    _, receipt = compile_talent_candidate(
        compiled, selection=witness, level=60, bonus_talent_points=bonus)
    assert receipt["status"] == "EXECUTABLE_CANDIDATE_DIAGNOSTIC"

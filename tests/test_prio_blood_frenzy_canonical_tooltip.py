"""Exact sourced compound critical-resource tooltip -> existing generic proc engine.

Parser behavior is a source projection, not a complete P2 runtime acceptance.
"""
from types import SimpleNamespace

import pytest

from src.game.data.forever.sqlite_talents import _parse_rank_tooltip
from src.game.data.forever.checkpoint_p2_execution_gate import _source_partial_semantics


SOURCE = {
    "url": "https://theforeverera.com/en/talents/druid/blood-frenzy/",
    "source_build": "1.60.1.70338",
    "capture_id": "test_source_rank",
}
MODES = {"bear_form": "bear", "cat_form": "cat"}


def text(chance):
    return (
        f"Gives you a {chance}% chance to gain an additional 5 Rage "
        "any time you get a critical strike while in Bear Form or Dire Bear Form. "
        "In addition, your non-periodic critical strikes from Cat Form abilities "
        f"that generate Combo Points have a {chance}% chance to add an additional Combo Point."
    )


@pytest.mark.parametrize("chance", [50, 100])
def test_sourced_two_branch_rank_compiles_both_runtime_resource_rules(chance):
    modifiers, missing, reason = _parse_rank_tooltip(
        text(chance), action_families={"claw"},
        mode_labels=MODES, source=SOURCE)
    assert len(modifiers) == 2
    assert {m.kind for m in modifiers} == {"critical_resource_gain"}
    bear, cat = modifiers
    assert (bear.target_id, bear.provenance["required_mode_id"]) == ("rage", "bear")
    assert (cat.target_id, cat.provenance["required_mode_id"]) == ("combo_points", "cat")
    assert (bear.value, cat.value) == pytest.approx((chance / 100, chance / 100))
    assert (bear.provenance["bonus_resource_amount"],
            cat.provenance["bonus_resource_amount"]) == (5.0, 1.0)
    assert bear.provenance["requires_resource_generator"] is False
    assert cat.provenance["requires_resource_generator"] is True
    assert missing == ("dire_bear_form",)
    assert reason == "source_critical_resource_partial_mode_scope"
    assert "SOURCE_CRITICAL_RESOURCE_MODE_SCOPE_NOT_EXECUTED" in (
        _source_partial_semantics(SimpleNamespace(modifiers=modifiers)))


def test_full_source_mode_availability_does_not_leave_mode_gap():
    modifiers, missing, reason = _parse_rank_tooltip(
        text(50), action_families={"claw"},
        mode_labels={**MODES, "dire_bear_form": "dire_bear"}, source=SOURCE)
    assert len(modifiers) == 3
    assert [m.provenance["required_mode_id"] for m in modifiers] == [
        "bear", "dire_bear", "cat"]
    assert not missing and reason is None
    assert not _source_partial_semantics(SimpleNamespace(modifiers=modifiers))


def test_partial_source_clause_fails_closed_without_invented_resource():
    broken = text(50).replace("Combo Points", "Combo Pearls")
    bad, _, reason = _parse_rank_tooltip(
        broken, action_families={"claw"}, mode_labels=MODES, source=SOURCE)
    assert not bad and reason == "invalid_source_critical_resource_compound"


def test_missing_required_bear_or_cat_mode_fails_closed():
    for modes in ({"cat_form": "cat"}, {"bear_form": "bear"}):
        modifiers, _, reason = _parse_rank_tooltip(
            text(50), action_families={"claw"}, mode_labels=modes, source=SOURCE)
        assert not modifiers and reason == "invalid_source_critical_resource_compound"

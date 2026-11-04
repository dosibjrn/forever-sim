"""Owner-approved P3 defensive-zero applicability, separate from paid gate runs.

These cheap validator regressions check status/coverage; they do not pretend
that a controlled item vector is a real source-legal live P3 acceptance.
"""
from types import SimpleNamespace

import pytest

from src.game import checkpoint_p3_smoke as p3


DEFENSIVE = ("armor", "stamina", "dodge", "parry",
             "health_regeneration_per_5s")


def _policy(mode=None):
    requirements = (() if mode is None else
                    ({"kind": "mode_is", "value": mode},))
    action = SimpleNamespace(id="selected_action", requirements=requirements,
                             effects=())
    ir = SimpleNamespace(id="test_source_ir", actor=None, modes=(),
                         actions=(action,), auto_attacks=())
    policy = SimpleNamespace(id="selected_policy",
                             rules=(SimpleNamespace(action_id=action.id),))
    return ir, policy


@pytest.fixture
def minimal_catalogue(monkeypatch):
    item = SimpleNamespace(item_id=7, item_level=60, required_level=60,
                           name="controlled ordinary gear", source_url="source")
    stats = {**{axis: 5.0 for axis in DEFENSIVE}, "spell_power": 10.0}
    monkeypatch.setattr(p3, "available_items",
                        lambda *args, **kwargs: (item,))
    monkeypatch.setattr(p3, "source_item_slots",
                        lambda row: ("chest",))
    monkeypatch.setattr(p3, "_ordinary_stats", lambda row: stats)
    monkeypatch.setattr(
        p3, "item_score",
        lambda row, weights: sum(float(weights.get(k, 0.0)) * value
                                 for k, value in stats.items()),
    )
    return {**{axis: 0.0 for axis in DEFENSIVE}, "spell_power": 1.0}


def _run(weights, class_key="druid", mode=None):
    ir, policy = _policy(mode)
    return p3.fast_p3_smoke_for_policy(
        source_ir=ir, policy=policy, class_key=class_key, level=60,
        weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
    )


def test_balance_defensive_zeros_are_counted_not_blocked(minimal_catalogue):
    result = _run(minimal_catalogue)
    assert result["p3_pass"] is True
    assert result["defensive_positive_required"] is False
    assert result["tested_stat_assertions"] == 6
    assert result["verified_stat_assertions"] == 6
    assert result["blockers"] == []


@pytest.mark.parametrize("class_key, mode", [
    ("warrior", None),
    ("druid", "bear"),
])
def test_warrior_or_selected_bear_policy_requires_positive_defense(
        minimal_catalogue, class_key, mode):
    result = _run(minimal_catalogue, class_key=class_key, mode=mode)
    assert result["defensive_positive_required"] is True
    assert result["p3_pass"] is False
    for axis in DEFENSIVE:
        assert "NONPOSITIVE_RELEVANT_WEIGHT:" + axis in result["blockers"]


def test_negative_defensive_weight_still_fails_for_caster(minimal_catalogue):
    weights = {**minimal_catalogue, "stamina": -0.5}
    result = _run(weights)
    assert result["p3_pass"] is False
    assert "NEGATIVE_WEIGHT:stamina" in result["blockers"]


def test_offensive_zero_still_fails_for_caster(minimal_catalogue):
    result = _run({**minimal_catalogue, "spell_power": 0.0})
    assert "NONPOSITIVE_RELEVANT_WEIGHT:spell_power" in result["blockers"]


def test_missing_defensive_weight_is_not_forgiven(minimal_catalogue):
    weights = dict(minimal_catalogue)
    del weights["armor"]
    result = _run(weights)
    assert "MISSING_WEIGHT:armor" in result["blockers"]


@pytest.fixture
def native_weapon_scorer(monkeypatch):
    """Exercise the native-item scorer mapping, without auditing Rust mechanics."""
    from src.game import native_p3_item_options

    item = SimpleNamespace(item_id=101, item_level=20, required_level=20,
                           name="Native-equipped weapon", source_url="native")
    stats = {"weapon_dps": 6.0, "mean_weapon_hit_damage": 4.0}
    monkeypatch.setattr(
        native_p3_item_options, "native_p3_item_records",
        lambda *args, **kwargs: (
            (item,), {}, {"status": "ok", "unverified_candidate_count": 0,
                          "excluded_non_client_item_count": 0,
                          "source": "selected-native"}
        ),
    )
    monkeypatch.setattr(p3, "source_item_slots",
                        lambda row: ("main_hand",))
    monkeypatch.setattr(p3, "_ordinary_stats", lambda row: stats)
    monkeypatch.setattr(
        p3, "item_score",
        lambda row, weights: sum(
            float(weights.get(axis, 0.0)) * amount
            for axis, amount in stats.items()
        ),
    )


@pytest.mark.parametrize("weight", [0.0, -0.4])
def test_native_measured_weapon_tradeoffs_are_valid_p3_scores(
        native_weapon_scorer, weight):
    report = p3.fast_p3_smoke(
        class_key="priest", level=20,
        weights={"weapon_dps": weight, "mean_weapon_hit_damage": weight},
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
        weapon_damage_dependent=True,
        equipped_weapon_dps_relevant=True,
        native_options_binary="selected-native",
    )
    assert report["blockers"] == []
    assert report["p3_pass"] is True
    assert report["tested_stat_assertions"] == 2
    assert report["verified_stat_assertions"] == 2
    assert report["slots"]["main_hand"]["items"][0]["score"] == weight * 10.0


@pytest.mark.parametrize(("weights", "missing"), [
    ({"weapon_dps": -0.4}, "MISSING_WEIGHT:mean_weapon_hit_damage"),
    ({"mean_weapon_hit_damage": -0.4}, "MISSING_APPLICABLE_DPS_WEIGHT"),
])
def test_native_weapon_sensitivity_still_needs_measured_axes(
        native_weapon_scorer, weights, missing):
    report = p3.fast_p3_smoke(
        class_key="priest", level=20,
        weights=weights,
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
        weapon_damage_dependent=True,
        equipped_weapon_dps_relevant=True,
        native_options_binary="selected-native",
    )
    assert report["p3_pass"] is False
    assert missing in report["blockers"]

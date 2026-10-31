import pytest

from src.shared.leveling.timing import BASE_BETWEEN_PULL_TRAVEL_S, between_pull_travel_s
from src.v2.class_model import Evaluation


def test_shared_travel_baseline_and_speed_modifier():
    assert between_pull_travel_s() == pytest.approx(BASE_BETWEEN_PULL_TRAVEL_S)
    assert between_pull_travel_s(speed_multiplier=1.10) == pytest.approx(BASE_BETWEEN_PULL_TRAVEL_S / 1.10)


def test_evaluation_publishes_one_consistent_timing_contract():
    ev = Evaluation.from_raw({"total_s": 1000.0, "kill_s": 600.0, "recovery_s": 180.0, "travel_s": 220.0})
    out = ev.published_fields()
    assert out["seconds_per_mob"] == pytest.approx(10.0)
    assert out["kill_seconds_per_mob"] == pytest.approx(6.0)
    assert out["recovery_seconds_per_mob"] == pytest.approx(1.8)
    assert out["travel_seconds_per_mob"] == pytest.approx(2.2)
    assert out["timing_complete"] is True
    assert out["timing_consistent"] is True
    assert out["timing_residual_seconds_per_mob"] == pytest.approx(0.0)


def test_evaluation_surfaces_stale_mixed_authority_timing():
    ev = Evaluation.from_published_row({
        "score_s_per_100": 900.0,
        "kill_seconds_per_mob": 6.0,
        "recovery_seconds_per_mob": 2.0,
        "travel_seconds_per_mob": 2.2,
    })
    assert ev.timing_complete is True
    assert ev.timing_consistent is False
    assert ev.timing_residual_s_per_100 == pytest.approx(-120.0)


def test_forever_experimental_classes_share_non_overlapping_travel_bucket():
    from src.rulesets.forever.classes.hunter import engine as hunter
    from src.rulesets.forever.classes.druid import engine as druid
    from src.rulesets.forever.classes.paladin import engine as paladin

    samples = [
        hunter.experimental_level_score(20, hunter.Talents(), "marksmanship"),
        druid.experimental_level_score(20, druid.Talents(), "balance"),
        paladin.experimental_level_score(20, paladin.Talents(), "retribution"),
    ]
    for score in samples:
        assert score["travel_s"] > 0
        assert score["total_s"] == pytest.approx(score["kill_s"] + score["recovery_s"] + score["travel_s"])

def test_forever_mage_event_chain_uses_same_timing_decomposition():
    from src.rulesets.forever.classes.mage import engine as mage
    policy = mage.Policy('Frostbolt spam', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    score = mage.simulate_chain(20, mage.Talents(), policy, mage.SimConfig(), n=4, seed=7)
    assert score['travel_s'] == pytest.approx(4 * BASE_BETWEEN_PULL_TRAVEL_S)
    assert score['total_s'] == pytest.approx(score['kill_s'] + score['recovery_s'] + score['travel_s'])

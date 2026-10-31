import pytest

from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.classes.druid.talents import Talents


def test_berserk_facts_match_current_forever_tooltip():
    assert wh.BERSERK_COOLDOWN_S == pytest.approx(180.0)
    assert wh.BERSERK_DURATION_S == pytest.approx(15.0)
    assert wh.BERSERK_CP_BUILDER_CRIT_BONUS == pytest.approx(1.0)
    assert wh.BERSERK_PRIMAL_BITE_MAX_TARGETS == 3


def test_cat_berserk_increases_builder_crit_and_throughput():
    base = mechanics._cat_single(60, Talents(blood_frenzy=2))
    zerk = mechanics._cat_single(60, Talents(blood_frenzy=2, berserk=1))

    assert zerk["berserk_available"] is True
    assert zerk["berserk_uptime_ev"] == pytest.approx(15.0 / 180.0)
    assert zerk["builder_crit_chance_ev"] > base["builder_crit_chance_ev"]
    assert zerk["combo_points_per_builder_ev"] > base["combo_points_per_builder_ev"]
    assert zerk["dps"] > base["dps"]
    assert "Berserk on CD" in zerk["rotation"]


def test_bear_berserk_removes_primal_bite_cooldown_during_window_and_adds_pack_hits():
    talents = dict(mangle=1, leader_of_the_pack=1)
    base = mechanics._bear_pack(60, Talents(**talents), 3)
    zerk = mechanics._bear_pack(60, Talents(**talents, berserk=1), 3)

    assert zerk["berserk_available"] is True
    assert zerk["berserk_uptime_ev"] == pytest.approx(15.0 / 180.0)
    assert zerk["berserk_primal_bite_rate_per_s"] > 0.0
    assert zerk["berserk_primal_bite_extra_targets"] == 2
    assert zerk["primal_bite_rate_per_s"] > base["primal_bite_rate_per_s"]
    assert zerk["dps"] > base["dps"]
    assert "Berserk on CD" in zerk["rotation"]


def test_bear_berserk_does_not_create_extra_targets_on_single_target():
    row = mechanics._bear_pack(60, Talents(mangle=1, leader_of_the_pack=1, berserk=1), 1)
    assert row["berserk_primal_bite_extra_targets"] == 0

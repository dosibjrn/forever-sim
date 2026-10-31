from __future__ import annotations

import pytest

from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid.talents import Talents


def test_druid_defense_bonus_reduces_single_target_incoming_damage():
    level = 20
    talents = Talents()
    gear = mechanics._bear_gear(level)
    base_damage, _, _ = mechanics._incoming_damage(level, 10.0, gear, bear=True, talents=talents)
    more = dict(gear)
    more["defense"] = float(more.get("defense", 0.0)) + 10.0
    more_damage, _, _ = mechanics._incoming_damage(level, 10.0, more, bear=True, talents=talents)

    # Druid +Defense has miss+dodge channels, but no parry channel in form.
    assert mechanics._druid_defense_avoidance(more) - mechanics._druid_defense_avoidance(gear) == pytest.approx(0.008)
    assert more_damage < base_damage


def test_bear_pack_exposes_defense_avoidance_and_it_changes_survival():
    level = 20
    talents = Talents()
    token = mechanics._GEAR_PROBE.set({"defense": 20.0})
    try:
        row = mechanics._bear_pack(level, talents, 3)
    finally:
        mechanics._GEAR_PROBE.reset(token)

    assert row["defense_skill_bonus"] >= 20.0
    assert row["defense_avoidance_bonus"] > 0.0
    assert row["total_avoidance"] >= row["defense_avoidance_bonus"]
    assert row["avg_incoming_dps"] > 0.0


def test_druid_defense_link_mutation_is_detected(monkeypatch):
    level = 20
    talents = Talents()
    gear = mechanics._bear_gear(level)
    more = dict(gear)
    more["defense"] = float(more.get("defense", 0.0)) + 20.0

    base = mechanics._incoming_damage(level, 10.0, gear, bear=True, talents=talents)[0]
    improved = mechanics._incoming_damage(level, 10.0, more, bear=True, talents=talents)[0]
    assert improved < base

    monkeypatch.setattr(mechanics, "_druid_defense_avoidance", lambda _gear: 0.0)
    broken_base = mechanics._incoming_damage(level, 10.0, gear, bear=True, talents=talents)[0]
    broken_more = mechanics._incoming_damage(level, 10.0, more, bear=True, talents=talents)[0]
    assert broken_more == pytest.approx(broken_base)


def test_druid_defense_stat_weight_reason_no_longer_claims_avoidance_unmodeled():
    out = mechanics.marginal_stat_weights(20, Talents(), profile="bear")
    row = out["stats"]["defense"]
    assert row["status"] == "measured"
    assert "generic miss+dodge avoidance" in row["reason"]
    assert "not yet modeled" not in row["reason"]

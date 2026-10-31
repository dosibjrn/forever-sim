from src.rulesets.forever.classes.druid import mechanics as m
from src.rulesets.forever.classes.druid.talents import Talents


def test_rejuvenation_carry_ticks_into_next_pull():
    heal, detail = m._rejuvenation_carry_heal(20, {"healing": 0.0}, 8.0)
    assert detail is not None
    assert detail["rank_level"] == 16
    assert detail["carry_ticks"] == 3
    assert heal == 87.0


def test_rejuvenation_healing_stat_increases_carry_value():
    base, _ = m._rejuvenation_carry_heal(40, {"healing": 0.0}, 8.0)
    boosted, _ = m._rejuvenation_carry_heal(40, {"healing": 100.0}, 8.0)
    assert boosted > base


def test_bear_frenzied_regeneration_reduces_recovery_deficit():
    t = Talents()
    gear = {"stamina": 25.0, "armor": 500.0, "bonus_armor": 0.0, "defense": 0.0,
            "spirit": 0.0, "mp5": 0.0, "healing": 0.0}
    no_fr = m._feral_pack_recovery(40, t, gear, 8.0, pull_size=1, avg_alive=1.0, first_kill_s=8.0, rage_rate=0.0)
    with_fr = m._feral_pack_recovery(40, t, gear, 8.0, pull_size=1, avg_alive=1.0, first_kill_s=8.0, rage_rate=8.0)
    assert with_fr["frenzied_regeneration_heal_ev"] > 0.0
    assert with_fr["hp_missing"] < no_fr["hp_missing"]


def test_bear_peak_pressure_participates_in_lethality(monkeypatch):
    t = Talents()
    gear = {"stamina": 0.0, "armor": 0.0, "bonus_armor": 0.0, "defense": 0.0,
            "spirit": 0.0, "mp5": 0.0, "healing": 0.0}
    monkeypatch.setattr(m, "_player_hp", lambda *a, **k: 100.0)
    monkeypatch.setattr(m, "normal_world_raw_dps", lambda level: 10.0)
    # Average exposure total stays <100, but the full-pack opener exceeds it.
    row = m._feral_pack_recovery(40, t, gear, 4.0, pull_size=3, avg_alive=1.0, first_kill_s=4.0, rage_rate=0.0)
    assert row["feasible"] is False
    assert row["lethal_pressure"] >= row["player_hp"]


def test_rejuvenation_carry_policy_can_beat_direct_recovery():
    gear = {"spirit": 0.0, "mp5": 0.0, "healing": 0.0}
    rows = m._feral_caster_recovery_candidates(40, Talents(), gear, 8.0, 400.0, 100.0)
    best = min(rows, key=lambda row: row["recovery_s"])
    assert best["recovery_method"] == "caster_rejuvenation_carry_reform"
    assert best["rejuvenation_carry_ticks"] == 3

import pytest

from src.rulesets.forever.classes import druid
from src.rulesets.forever.classes.druid import mechanics as dm
from src.rulesets.forever.classes.druid import wowhead_facts as wh


def test_wrath_forever_rank_modifier_progression():
    assert wh.WRATH_SP_COEFF_LADDER[:3] == ((1, 0.429), (6, 0.486), (14, 0.571))
    assert all(coeff == pytest.approx(0.571) for _lv, coeff in wh.WRATH_SP_COEFF_LADDER[2:])
    assert wh.WRATH_RANKS[:3] == (
        (1, 10, 1.5, 15, 18, 0.429),
        (6, 20, 1.7, 25, 28, 0.486),
        (14, 40, 2.0, 32, 37, 0.571),
    )


def test_starfire_and_moonfire_forever_modifier_ladders():
    assert all(coeff == pytest.approx(1.0) for _lv, coeff in wh.STARFIRE_SP_COEFF_LADDER)
    assert wh.MOONFIRE_SP_COEFF_LADDER[:4] == (
        (4, 0.060, 0.052),
        (10, 0.094, 0.081),
        (16, 0.128, 0.111),
        (22, 0.150, 0.130),
    )
    assert wh.MOONFIRE_RANKS[-1][:6] == (58, 375, 195, 228, 384, 12.0)
    assert wh.MOONFIRE_RANKS[-1][-2:] == pytest.approx((0.15, 0.13))


def test_insect_swarm_full_duration_spell_power_modifier():
    assert wh.INSECT_SWARM_TICK_SP_COEFF == pytest.approx(0.158)
    assert wh.INSECT_SWARM_FULL_DURATION_SP_COEFF == pytest.approx(0.948)


def test_balance_runtime_actually_credits_periodic_spell_power(monkeypatch):
    # Hold every gear stat fixed except SP so dot_damage_per_mob must react to
    # Moonfire/Insect periodic modifiers as well as Moonfire direct damage.
    def gear(sp):
        return {
            "name": "test", "spell_power": float(sp), "intellect": 0.0,
            "strength": 0.0, "agility": 0.0, "stamina": 0.0, "spirit": 0.0,
            "armor": 0.0, "defense_rating": 0.0, "items": [],
            "provenance": "test",
        }
    t=druid.Talents(insect_swarm=1)
    monkeypatch.setattr(dm, "_balance_gear", lambda level: gear(0))
    zero=druid.experimental_level_score(50,t,"balance")
    monkeypatch.setattr(dm, "_balance_gear", lambda level: gear(100))
    hundred=druid.experimental_level_score(50,t,"balance")
    assert hundred["dot_damage_per_mob"] > zero["dot_damage_per_mob"] + 50.0


def test_natures_splendor_adds_periodic_uptime_instead_of_diluting_dot(monkeypatch):
    def gear(level):
        return {
            "name": "test", "spell_power": 100.0, "intellect": 0.0,
            "strength": 0.0, "agility": 0.0, "stamina": 0.0, "spirit": 0.0,
            "armor": 0.0, "defense_rating": 0.0, "items": [],
            "provenance": "test",
        }
    monkeypatch.setattr(dm, "_balance_gear", gear)
    base=druid.experimental_level_score(50,druid.Talents(insect_swarm=1),"balance")
    long=druid.experimental_level_score(50,druid.Talents(insect_swarm=1,natures_splendor=1),"balance")
    assert long["dot_damage_per_mob"] >= base["dot_damage_per_mob"]

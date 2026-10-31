import pytest

from src.rulesets.forever.classes.druid.mechanics import (
    _bear_pack, _thick_hide_base_armor, marginal_stat_weights,
)
from src.rulesets.forever.classes.druid.talents import Talents


def _base(**kw):
    data=dict(
        ferocity=5, heart_of_the_wild=5, feral_instinct=3, savage_fury=2,
        sharpened_claws=2, predatory_strikes=3, leader_of_the_pack=1,
        thick_hide=0,
    )
    data.update(kw)
    return Talents(**data)


def test_thick_hide_rank3_adds_three_base_armor_per_level_before_form_multiplier():
    t=_base(thick_hide=3)
    assert _thick_hide_base_armor(60,t,{"defense":0}) == pytest.approx(180.0)
    row=_bear_pack(60,t,1)
    zero=_bear_pack(60,_base(thick_hide=0),1)
    # Production Bear gear may carry excess +Defense, which Forever Thick Hide
    # also converts to pre-form base Armor. Assert against the same canonical
    # gear vector rather than the old defense-free fixture assumption.
    expected=_thick_hide_base_armor(60,t,row["gear_stats"])
    assert row["thick_hide_base_armor"] == pytest.approx(expected)
    assert row["armor"] - zero["armor"] == pytest.approx(expected * 5.0)


def test_thick_hide_rank_table_uses_tooltip_excess_defense_coefficients():
    gear={"defense":10}
    expected=(0.0, 20.0+6.7, 40.0+13.3, 60.0+20.0)
    for rank,want in enumerate(expected):
        assert _thick_hide_base_armor(20,_base(thick_hide=rank),gear) == pytest.approx(want)


def test_thick_hide_reduces_bear_incoming_damage():
    zero=_bear_pack(60,_base(thick_hide=0),3)
    three=_bear_pack(60,_base(thick_hide=3),3)
    assert three["incoming_damage"] < zero["incoming_damage"]
    assert three["armor_reduction"] > zero["armor_reduction"]


def test_defense_probe_has_value_with_thick_hide():
    weights=marginal_stat_weights(60,_base(thick_hide=3),profile="bear")
    assert "defense" in weights["stats"]
    assert weights["stats"]["defense"]["status"] == "measured"

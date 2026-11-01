import pytest

from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.classes.druid.mechanics import _bear_pack, _lacerate_cycle
from src.rulesets.forever.classes.druid.talents import Talents


def _feral(**kw):
    data=dict(
        ferocity=5, heart_of_the_wild=5, feral_instinct=3, savage_fury=2,
        sharpened_claws=2, shredding_attacks=0, mangle=1,
        predatory_strikes=3, blood_frenzy=2, leader_of_the_pack=1,
        natural_reaction=5,
    )
    data.update(kw)
    return Talents(**data)


def test_lacerate_rank_ladder_matches_forever_beta():
    assert wh.LACERATE_RANKS == (
        (42, 15, 50, 15.0, 5, 0.10),
        (50, 15, 60, 15.0, 5, 0.10),
        (58, 15, 75, 15.0, 5, 0.10),
    )


def test_shredding_attacks_reduces_lacerate_rage_by_one_per_rank():
    for rank, expected in [(0, 15.0), (1, 14.0), (2, 13.0), (3, 12.0)]:
        row=_lacerate_cycle(
            60,_feral(shredding_attacks=rank),rage_budget_per_s=20.0,
            gcd_budget_per_s=2/3,target_lifetime_s=30.0,
            bear_normal_hit=100.0,crit=0.10,
        )
        assert row["rage_cost"] == pytest.approx(expected)


def test_lacerate_ramp_is_finite_target_and_caps_at_five_stacks():
    short=_lacerate_cycle(
        60,_feral(shredding_attacks=3),rage_budget_per_s=20.0,
        gcd_budget_per_s=2/3,target_lifetime_s=3.0,
        bear_normal_hit=100.0,crit=0.10,
    )
    long=_lacerate_cycle(
        60,_feral(shredding_attacks=3),rage_budget_per_s=20.0,
        gcd_budget_per_s=2/3,target_lifetime_s=30.0,
        bear_normal_hit=100.0,crit=0.10,
    )
    assert short["applications_per_target"] < 5.0
    assert long["applications_per_target"] == pytest.approx(5.0)
    assert long["avg_stacks"] < 5.0
    assert long["dps"] > short["dps"]


def test_bear_production_uses_lacerate_from_level_42_and_exposes_priority():
    pre=_bear_pack(41,_feral(shredding_attacks=3),1)
    post=_bear_pack(42,_feral(shredding_attacks=3),1)
    assert pre["lacerate_rank_level"] is None
    assert pre["lacerate_dps"] == 0.0
    assert post["lacerate_rank_level"] == 42
    assert post["lacerate_rage_cost"] == pytest.approx(12.0)
    assert post["lacerate_cast_rate_per_s"] > 0.0
    assert "Lacerate ramp/maintain on focus" in post["rotation"]

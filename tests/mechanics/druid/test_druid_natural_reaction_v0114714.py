import pytest

from src.rulesets.forever.classes.druid.mechanics import _bear_pack, _natural_reaction, _world_melee_attack_attempts_per_second
from src.rulesets.forever.classes.druid.talents import Talents


def _base(**kw):
    # Legal-ish late-Feral fixture with stable Bear throughput; Natural Reaction
    # is the only field varied by the tests below.
    data=dict(
        ferocity=5, heart_of_the_wild=5, feral_instinct=3, savage_fury=2,
        sharpened_claws=2, predatory_strikes=3, leader_of_the_pack=1,
        natural_reaction=0,
    )
    data.update(kw)
    return Talents(**data)


def test_natural_reaction_rank_table_matches_forever_tooltip():
    for rank in range(6):
        dodge, proc, rage = _natural_reaction(_base(natural_reaction=rank))
        assert dodge == pytest.approx(.01 * rank)
        assert proc == pytest.approx(.20 * rank)
        assert rage == pytest.approx(5.0)


def test_rank5_dodge_reduces_bear_incoming_damage():
    zero=_bear_pack(60,_base(natural_reaction=0),3)
    five=_bear_pack(60,_base(natural_reaction=5),3)
    assert five["natural_reaction_dodge_chance"] == pytest.approx(.05)
    # Same armor/exposure model: verified 5% dodge must lower expected damage.
    assert five["incoming_damage"] < zero["incoming_damage"]


def test_rank5_adds_expected_rage_from_dodges():
    row=_bear_pack(60,_base(natural_reaction=5),3)
    assert row["natural_reaction_rage_proc_chance"] == pytest.approx(1.0)
    assert row["natural_reaction_rage_per_proc"] == pytest.approx(5.0)
    expected=(
        max(1.0,row["avg_alive_mobs"])
        * _world_melee_attack_attempts_per_second()
        * .05 * 1.0 * 5.0
    )
    assert row["natural_reaction_rage_rate"] == pytest.approx(expected)
    assert row["rage_rate_proxy"] > row["base_rage_rate_proxy"] + row["incoming_damage_rage_rate_proxy"]

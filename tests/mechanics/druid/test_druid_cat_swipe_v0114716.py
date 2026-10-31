from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.classes.druid.mechanics import _cat, _cat_single
from src.rulesets.forever.classes.druid.talents import Talents


def _feral():
    return Talents(
        ferocity=5, heart_of_the_wild=5, feral_swiftness=2,
        savage_fury=2, sharpened_claws=2, predatory_strikes=3,
        blood_frenzy=2, leader_of_the_pack=1,
    )


def test_improved_swipe_is_not_claimed_available_from_sod_rune_page():
    assert wh.IMPROVED_SWIPE_AVAILABLE is False
    assert "wowforevertalent.com/abilities/druid" in wh.FOREVER_DRUID_SPELLBOOK_SOURCE


def test_cat_production_does_not_use_unverified_swipe_cat():
    t = _feral()
    single = _cat_single(40, t)
    best = _cat(40, t)
    assert best["total_s"] == single["total_s"]
    assert best["pull_size"] == 1
    assert best["improved_swipe_used"] is False

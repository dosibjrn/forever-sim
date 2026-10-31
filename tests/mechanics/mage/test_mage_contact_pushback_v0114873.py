from __future__ import annotations

from src import game_context
from src.engine_registry import reset_engine_cache


def _forever_expected_engine():
    game_context.configure("forever", "mage")
    reset_engine_cache()
    from src.v2 import expected_engine as expected
    from src.rulesets.forever.classes.mage import engine as mage
    return expected, mage


def test_expected_contact_prices_melee_that_begins_during_hard_cast():
    expected, mage = _forever_expected_engine()
    cfg = mage.SimConfig()
    mob = mage.Mob(level=20, hp=500.0, run_speed=cfg.mob_speed, swing=2.0, melee_reach=cfg.melee_reach)
    state = expected.ExpectedState(
        t=0.0, hp=500.0, mana=1000.0, max_mana=1000.0,
        distance=8.0, engaged=True,
    )
    # The mob is not in melee at cast start but reaches the mage during a
    # 2.1-second hard cast.  This was the v0.11.48.72 blind spot.
    contact_s, swings = expected._expected_contact_and_swings_during_interval(state, 2.1, mob)
    assert contact_s > 0.0
    assert swings >= 1.0


def test_l20_control_screen_no_longer_reports_zero_contact_and_pushback():
    expected, mage = _forever_expected_engine()
    talents = mage.Talents(
        imp_frostbolt=5, elemental_precision=1, permafrost=1,
        frostbite=3, ice_lance=1,
    )
    policy = mage.Policy(
        "contact regression", "frostbolt", use_fireblast=True,
        use_nova=True, nova_rank1=True, nova_move_yards=5,
        use_blink=True, blink_min_hp_frac=0.35,
        use_proc_ice_lance=True,
    )
    score = expected.score_policy(20, talents, policy, mage.SimConfig(), cycle_pulls=6)
    assert score["melee_contact_s"] > 0.0
    assert score["pushback_s"] > 0.0

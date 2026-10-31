from __future__ import annotations

import random
from dataclasses import replace

from src.rulesets.forever.classes.mage import engine as mage


def _l20_ice_lance_build():
    return mage.Talents(
        imp_frostbolt=5,
        elemental_precision=1,
        permafrost=1,
        frostbite=3,
        ice_lance=1,
    )


def test_l20_best_wand_matches_real_named_gear_authority():
    wand = mage.best_wand(20)
    gear = mage.real_gear_snapshot(20)["slots"]["wand"]
    assert wand.name == gear["name"] == "Sizzle Stick"
    assert wand.item_id == int(gear["item_id"]) == 8071
    assert wand.school == "fire"
    assert wand.school_origin == "wowhead_current_item_fact"
    assert abs(wand.dmin - 27.0) < 1e-9
    assert abs(wand.dmax - 52.0) < 1e-9
    assert abs(wand.speed - 1.70) < 1e-9
    assert abs(wand.dps - float(gear["wand_dps"])) < 0.02


def test_frost_final_search_exposes_hp_aware_wand_cutoffs_1_2_3():
    ps = mage.candidate_policies_for_build(20, _l20_ice_lance_build(), focused=True, school="frost")
    cutoffs = {int(p.wand_finisher_max_hits) for p in ps if p.use_proc_ice_lance}
    assert {0, 1, 2, 3}.issubset(cutoffs)
    assert any("HP→Wand≤2" in mage.policy_desc(p, 20) for p in ps if p.wand_finisher_max_hits == 2)


def test_wand_finisher_is_bounded_once_per_mob():
    t = _l20_ice_lance_build()
    cfg = mage.SimConfig()
    stats = mage.player_stats_for_config(20, t, cfg)
    mob = mage.Mob(level=20, hp=500.0, run_speed=cfg.mob_speed, swing=2.0, melee_reach=cfg.melee_reach)
    s = mage.State(t=0.0, hp=1000.0, mana=stats.max_mana, max_mana=stats.max_mana, distance=30.0)
    metrics = mage.FightMetrics()
    mage.perform_wand_finisher(s, 2, 20, t, stats, cfg, mob, random.Random(7), metrics)
    assert s.wand_finisher_committed is True
    assert metrics.casts.get("wand_finisher", 0) <= 2
    assert metrics.wand_shots <= 2
    p = mage.Policy("bounded", "frostbolt", wand_finisher_max_hits=2)
    assert mage.choose_action(s, 20, t, stats, cfg, mob, p, mob.hp)[0] != "wand_finisher"


def test_l20_event_policy_sweep_evaluates_hp_aware_wand_windows_without_freezing_winner():
    """Cutoff is a searched policy dimension, not a hard-coded answer.

    Use one otherwise-identical policy and vary only the observable-HP wand
    window.  Catalogue refreshes and corrected ranged-hit mechanics may change
    which cutoff wins; the invariant is that all bounded alternatives are
    actually evaluated and can affect the score.
    """
    t = _l20_ice_lance_build()
    cfg = mage.SimConfig()
    base = next(
        p for p in mage.candidate_policies_for_build(20, t, focused=True, school="frost")
        if p.use_proc_ice_lance and p.use_fireblast and p.use_nova
        and p.nova_move_yards == 5 and abs(p.blink_min_hp_frac - 0.35) < 1e-12
        and int(p.wand_finisher_max_hits) == 0
    )
    by_cutoff = {}
    for cutoff in (0, 1, 2, 3):
        p = replace(base, name=f"wand cutoff {cutoff}", wand_finisher_max_hits=cutoff)
        r = mage.simulate_chain(20, t, p, cfg, n=16, seed=7)
        by_cutoff[cutoff] = 3600.0 / (float(r["total_s"]) / 16.0)
        assert float(r.get("wand_shots", 0.0)) <= cutoff * 16 + 1e-9
    assert set(by_cutoff) == {0, 1, 2, 3}
    assert len({round(v, 6) for v in by_cutoff.values()}) > 1
    assert max(by_cutoff, key=by_cutoff.get) in {0, 1, 2, 3}

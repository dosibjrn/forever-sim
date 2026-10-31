"""Slow release gate for the real stochastic PnP mapper/reducer.

This file lives in ``tests/release/`` and is excluded from ordinary pytest
collection using ``norecursedirs = release``. Release smoke is invoked
explicitly with ``scripts/commands/run-release-smoke.*``.
"""

import os
import pickle

from src import classic_mage_leveling_optimizer_v10 as eng
from src import optimizer_core as opt
from src import pnp_cache
from src import policy_codec


def _run_small_frost_search(tmp_path, callback):
    return opt.run_search(
        start_level=11,
        end_level=13,
        snapshot_width=8,
        snapshot_mobs=1,
        beam=6,
        score_mobs=1,
        dest_cheap_mobs=1,
        dest_refine_mobs=1,
        dest_k=4,
        max_respecs=2,
        seed=47,
        workers=1,
        checkpoint=tmp_path / "mc_precision_ladder.pkl",
        resume=True,
        exploration_frac=0.20,
        callback=callback,
        seed_dir=None,
        cross_seed_dirs=[],
        use_best_water=True,
        respec_prior_schedules=[],
        incumbent_hours_provider=None,
        fastlane_max_per_preview=0,
    )


def test_real_frost_mc_precision_ladder_and_resume(tmp_path, monkeypatch):
    """Exercise real MC simulation through 1->100m and checkpoint resume.

    Unlike the fast unit suite, this does not mock the fight simulator or PnP
    evaluator.  It is intentionally a slower release-only smoke test.
    """
    pnp_cache.close_connection()
    monkeypatch.setattr(pnp_cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pnp_cache, "DB_PATH", tmp_path / "cache" / "pnp.sqlite3")
    pnp_cache._DB_READY.clear()
    monkeypatch.setenv(eng.PRIMARY_SCHOOL_ENV, "frost")

    seen = []
    layers = _run_small_frost_search(
        tmp_path,
        lambda data: seen.append(
            (
                data.get("phase"),
                data.get("snapshot_level"),
                data.get("outer_level"),
                data.get("preview_precision_mobs"),
            )
        ),
    )

    assert sorted({p for *_rest, p in seen if p}) == list(pnp_cache.PRECISION_LADDER)
    top = opt.all_top_states(layers, top_k=6)
    assert top
    for state in top:
        for event in state.events:
            if event.score_s <= 0 or event.policy == "unscored":
                continue
            policy = policy_codec.parse_descriptor(event.policy, event.level)
            assert eng.policy_primary_school(policy) == "frost"

    checkpoint = tmp_path / "mc_precision_ladder.pkl"
    with checkpoint.open("rb") as fh:
        saved = pickle.load(fh)
    assert saved["phase"] == "outer"
    assert saved["outer_level"] == 13
    assert set(saved["snapshot_pools"]) == {11, 12, 13}

    first_keys = [opt.state_rank_key(s) for s in top]
    resumed_callbacks = []
    resumed = _run_small_frost_search(tmp_path, lambda data: resumed_callbacks.append(data))
    assert resumed_callbacks == [], "resume should reuse completed 100m map + outer DP checkpoint"
    assert [opt.state_rank_key(s) for s in opt.all_top_states(resumed, top_k=6)] == first_keys

    pnp_cache.close_connection()


def test_real_level40_mc_barrier_policy_option(tmp_path, monkeypatch):
    """Barrier talent must expose both ON/OFF to the real cached MC optimizer.

    The assertion deliberately does not require Barrier ON to win the baseline
    generic-mob objective; the correctness contract is that taking the talent
    grants an optional policy action rather than forcing its mana/GCD cost.
    """
    pnp_cache.close_connection()
    monkeypatch.setattr(pnp_cache, "CACHE_DIR", tmp_path / "barrier_cache")
    monkeypatch.setattr(pnp_cache, "DB_PATH", tmp_path / "barrier_cache" / "pnp.sqlite3")
    pnp_cache._DB_READY.clear()
    monkeypatch.setenv(eng.PRIMARY_SCHOOL_ENV, "frost")

    base=eng.Talents(
        imp_frostbolt=5, elemental_precision=3, ice_shards=5, frostbite=3,
        imp_frost_nova=2, permafrost=3, piercing_ice=3, arctic_reach=2,
        frost_channeling=3, ice_block=1,
    )
    talents=eng.add_point(base,'ice_barrier')
    policies=pnp_cache._candidate_policies(40,talents,coarse=True)
    assert any(p.use_ice_barrier for p in policies)
    assert any(not p.use_ice_barrier for p in policies)

    cfg=eng.SimConfig(use_best_water=True,seed=9001)
    winner,result=pnp_cache.optimize_policy_cached(40,talents,cfg,n=4,seed=9001,coarse=True)
    assert eng.policy_primary_school(winner) == 'frost'
    assert result['total_s'] > 0
    assert pnp_cache.DB_PATH.exists()
    pnp_cache.close_connection()

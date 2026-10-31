from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import continuity
from src.v2.analytic_frontier import default_views
from src.v2.path_dp import LevelNode


def test_continuity_preserves_locally_bad_cross_tree_setup_until_future_unlock(monkeypatch):
    cfg = eng.SimConfig(use_best_water=True)
    lo, hi = 40, 46  # six future points: enough for 5 Arcane setup + first AC point

    # Start from a real legal Fire-heavy progression. Independent pools contain
    # only the locally attractive Fire continuation; the cross-tree setup must
    # therefore be created by continuity rather than handed to it.
    fire_rows = continuity._family_greedy_spines(lo, hi, cfg)['fire']
    base = fire_rows[lo]
    pools = {
        lvl: [LevelNode(lvl, fire_rows[lvl], 0.0, None, 'fixture')]
        for lvl in range(lo, hi + 1)
    }

    base_fire = {n: int(getattr(base, n)) for n, r in eng.TALENT_RULES.items() if r[0] == 'fire'}

    def synthetic_proxy(level, t, _cfg):
        # The current-level optimizer hates Arcane setup points. Only once
        # Arcane Concentration becomes reachable/selected does the branch pay.
        if t.arcane_concentration:
            return -1000.0
        arc = eng.tree_points(t, 'arcane')
        return 100.0 + arc if arc else 0.0

    def fake_score_worker(args):
        level, builds, _cfg, _view = args
        return level, [
            LevelNode(level, t, synthetic_proxy(level, t, _cfg) * 100.0, None, 'fixture-rich')
            for t in builds
        ]

    monkeypatch.setattr(continuity, 'proxy_score', synthetic_proxy)
    monkeypatch.setattr(continuity, '_score_missing_worker', fake_score_worker)

    out = continuity.close_pools_forward(
        pools, cfg, default_views()[1],
        parent_k=1, start_level=lo, end_level=hi, max_workers=1,
        leader_seeds=1, trail_cap=12,
    )

    # Exact Fire prerequisite allocation may differ because continuity also has
    # its own legal Fire spine. What matters is preserving a genuinely Fire-heavy
    # cross-tree setup, not falling back to the unrelated pure-Arcane spine.
    assert any(
        eng.tree_points(n.talents, 'fire') >= 30
        and n.talents.arcane_concentration >= 1
        for n in out[hi]
    ), 'future Arcane payoff branch was pruned before Arcane Concentration unlocked'

import pytest

from src import classic_mage_leveling_optimizer_v10 as eng
from src.mc_path_race import FrozenLevel, FrozenPath, race_paths


def _cand(name, base):
    pol = eng.Policy(name, 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    # Two levels make the test exercise path aggregation, not a single-level alias.
    return FrozenPath(name, (
        FrozenLevel(20, eng.Talents(imp_frostbolt=5), pol),
        FrozenLevel(21, eng.Talents(imp_frostbolt=5, elemental_precision=1), pol),
    ), metadata={'base': base})


def _fake_sim(level, talents, policy, cfg, *, target_n, seed, continuation):
    base = {'fast': 10.0, 'slow': 12.0, 'tie_a': 10.0, 'tie_b': 10.0}[policy.name]
    # Enough uncertainty to require at least one round in the tie case, while
    # clear 20% separation resolves immediately.
    se = 0.2 / (target_n ** 0.5)
    return {'mean_s_per_mob': base, 'stderr_s_per_mob': se}, {'n': target_n}


def test_full_path_race_eliminates_clear_loser_and_resolves():
    res = race_paths(
        [_cand('fast', 10), _cand('slow', 12)], eng.SimConfig(),
        start_mobs=20, max_mobs=80, growth=2, alpha=.05,
        simulate_incremental=_fake_sim,
    )
    assert res.resolved is True
    assert res.winner_index == 0
    assert res.survivor_indices == (0,)
    assert any(r.candidate_index == 1 and r.eliminated for r in res.rows)
    # Whole-path score is aggregated over both levels, not one representative level.
    assert res.rows[0].mean_seconds > 20.0


def test_full_path_race_can_end_explicitly_unresolved():
    res = race_paths(
        [_cand('tie_a', 10), _cand('tie_b', 10)], eng.SimConfig(),
        start_mobs=10, max_mobs=40, growth=2, alpha=.05,
        simulate_incremental=_fake_sim,
    )
    assert res.resolved is False
    assert res.survivor_indices == (0, 1)
    assert res.rounds == 3  # 10 -> 20 -> 40
    assert all(not r.eliminated for r in res.rows)


def test_full_path_race_rejects_mismatched_level_sets():
    a = _cand('fast', 10)
    b = FrozenPath('slow', a.levels[:1])
    with pytest.raises(ValueError, match='identical level sets'):
        race_paths([a, b], eng.SimConfig(), simulate_incremental=_fake_sim)

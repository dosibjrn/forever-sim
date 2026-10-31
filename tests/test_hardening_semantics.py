import math
import pytest

from src import classic_mage_leveling_optimizer_v10 as eng
from src import optimizer_core as opt
from src import state_manager as sm
from src.v2 import mc_bridge
from src.v2 import objective as obj


def _simple_path():
    t11 = eng.add_point(eng.add_point(eng.Talents(), 'imp_frostbolt'), 'imp_frostbolt')
    t12 = eng.add_point(t11, 'imp_frostbolt')
    pol = eng.Policy('FBo pure', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    return {
        'hours': 1.0,
        'respecs_used': 0,
        'respec_levels': [],
        'final_allocation': eng.final_allocation(t12),
        'steps': [
            {'level': 11, 'kind': 'start', 'talent_added': None,
             'allocation': eng.final_allocation(t11), 'policy': eng.policy_desc(pol,11),
             'score_s_per_100': 2400.0},
            {'level': 12, 'kind': 'point', 'talent_added': 'imp_frostbolt',
             'allocation': eng.final_allocation(t12), 'policy': eng.policy_desc(pol,12),
             'score_s_per_100': 2300.0},
        ],
    }


def test_objective_uses_same_lplus1_lplus2_workload_as_simulator():
    # Classic higher-level mob XP uses the mob-level base XP and +5% per level.
    # Character level 20: L21 => 158 XP, L22 => 171 XP after integer rounding.
    assert obj.mob_xp(20, 21) == 158
    assert obj.mob_xp(20, 22) == 171
    assert obj.workload_xp_per_mob(20) == pytest.approx((158 + 171) / 2)
    expected = obj.xp_to_next(20) / ((158 + 171) / 2) / 100.0
    assert obj.level_weight_per_100(20) == pytest.approx(expected)
    # Legacy MC and Fast must expose one authoritative objective.
    assert opt.level_weight_per_100(20) == pytest.approx(obj.level_weight_per_100(20))
    assert opt.OBJECTIVE_VERSION == obj.OBJECTIVE_VERSION


def test_allocation_parser_rejects_unknown_duplicate_and_out_of_range_fields():
    with pytest.raises(ValueError):
        opt.parse_allocation('definitely_not_a_talent=1')
    with pytest.raises(ValueError):
        opt.parse_allocation('imp_frostbolt=1, imp_frostbolt=2')
    max_rank = eng.TALENT_RULES['imp_frostbolt'][1]
    with pytest.raises(ValueError):
        opt.parse_allocation(f'imp_frostbolt={max_rank + 1}')


def test_outer_replay_point_detail_must_match_allocation_delta():
    rows = mc_bridge._path_to_replay(_simple_path())
    # The allocation adds imp_frostbolt, but the persisted label claims another
    # perfectly valid talent. Silent repair would validate a different path.
    rows[-1] = dict(rows[-1], detail='frost_warding')
    with pytest.raises(ValueError):
        opt.outer_state_from_replay(rows)


def test_replay_state_does_not_swallow_illegal_point_event():
    st = opt.OuterState(
        talents=eng.Talents(), cumulative_s=0.0, respecs_used=0,
        events=[opt.Event(10, 'point', 'definitely_not_a_talent', 'unscored', 0.0)]
    )
    with pytest.raises(Exception):
        opt.replay_state(st)


def test_bridge_rejects_valid_but_wrong_talent_added_label():
    p = _simple_path()
    p['steps'][1] = dict(p['steps'][1], talent_added='frost_warding')
    with pytest.raises(ValueError):
        mc_bridge._path_to_replay(p)


def test_fast_bridge_and_mc_use_same_canonical_path_id():
    c = mc_bridge._bridge_candidate('smooth', '0', _simple_path(), 'buy_water')
    expected = sm.candidate_path_id_from_replay(c['replay'])
    assert c['path_id'] == expected


def test_mc_cache_identity_uses_effective_policy_not_presentation_name():
    from src import pnp_cache
    cfg = eng.SimConfig(seed=123)
    t = eng.Talents(imp_frostbolt=5)
    a = eng.Policy('pretty name A', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    b = eng.Policy('pretty name B', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    assert pnp_cache.scenario_key(19, t, a, cfg, 99) == pnp_cache.scenario_key(19, t, b, cfg, 99)


def test_mc_cache_identity_ignores_pre20_blink_but_not_live_blink():
    from src import pnp_cache
    cfg = eng.SimConfig(seed=123)
    t = eng.Talents(imp_frostbolt=5)
    off = eng.Policy('off', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    on = eng.Policy('on', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=True)
    assert pnp_cache.scenario_key(19, t, off, cfg, 99) == pnp_cache.scenario_key(19, t, on, cfg, 99)
    assert pnp_cache.scenario_key(20, t, off, cfg, 99) != pnp_cache.scenario_key(20, t, on, cfg, 99)


def test_unknown_policy_descriptor_fails_loudly():
    with pytest.raises(ValueError):
        opt.policy_from_desc('DefinitelyNotASpell | FBl≤22%', 40)


@pytest.mark.parametrize('level', [19, 20, 40, 59])
def test_policy_descriptor_roundtrip_preserves_effective_descriptor(level):
    # Descriptor is the persisted Fast/MC contract. Every emitted search policy
    # must roundtrip to the same effective descriptor at that level.
    for p in eng.candidate_policies(level):
        d = eng.policy_desc(p, level)
        q = opt.policy_from_desc(d, level)
        assert eng.policy_desc(q, level) == d


def test_outer_replay_reconstructs_legacy_level11_prefix_snapshot():
    rows = mc_bridge._path_to_replay(_simple_path())
    legacy = rows[1:]  # historical files could omit the unscored lvl10 row
    st = opt.outer_state_from_replay(legacy, cumulative_hours_hint=1.0)
    assert [ev.level for ev in st.events[:2]] == [10, 11]
    assert st.events[0].policy == 'unscored'
    assert st.events[0].score_s == 0.0
    assert st.events[1].policy == legacy[0]['rotation']
    assert st.talents == opt.parse_allocation(legacy[-1]['allocation'])


def test_outer_replay_still_rejects_midpath_multi_point_jump():
    rows = mc_bridge._path_to_replay(_simple_path())
    jumped = eng.add_point(opt.parse_allocation(rows[-1]['allocation']), 'frost_warding')
    jumped = eng.add_point(jumped, 'frost_warding')
    rows[-1] = dict(rows[-1], allocation=eng.final_allocation(jumped), detail='frost_warding')
    with pytest.raises(ValueError, match='exactly one point'):
        opt.outer_state_from_replay(rows)


def test_outer_preview_progress_reports_expensive_stage(monkeypatch):
    """Outer DP exposes the exact stage so a long level is diagnosable."""
    from src import optimizer_core as opt
    from src import classic_mage_leveling_optimizer_v10 as eng

    policy = eng.Policy('test', primary='frostbolt')

    def fake_score_many(level, talents, cfg, n, seed, cache, executor=None, coarse=True):
        return [(policy, {'total_s': float(n), 'stderr_s_per_mob': 0.0}) for _ in talents]

    monkeypatch.setattr(opt, 'score_many', fake_score_many)
    events = []
    pools = {
        11: [opt.SnapshotState(eng.Talents(imp_frostbolt=2), 100.0, policy, 0.0)]
    }
    opt.optimize_free_respec(
        11, 11, pools, eng.SimConfig(), max_respecs=0, beam_width=3,
        score_mobs=4, dest_cheap_mobs=2, dest_refine_mobs=8, dest_k=12,
        pool_precision_mobs=32, progress_callback=events.append,
    )

    stages = [row['stage'] for row in events]
    assert stages[0] == 'begin'
    assert 'point-score' in stages
    assert 'destination-shortlist' in stages
    assert 'selection-refine' in stages
    assert stages[-1] == 'done'
    refine = next(row for row in events if row['stage'] == 'selection-refine')
    assert refine['level'] == 11
    assert refine['mobs'] == 32
    assert refine['candidates'] > 0

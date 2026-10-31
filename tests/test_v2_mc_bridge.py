from src import classic_mage_leveling_optimizer_v10 as eng
from src import optimizer_core as opt
from src.v2 import mc_bridge


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


def test_fast_path_replay_reconstructs_level10_prefix():
    replay = mc_bridge._path_to_replay(_simple_path())
    assert [r['level'] for r in replay] == [10,11,12]
    assert replay[0]['normalized_min_per_100'] == 0.0
    assert replay[1]['normalized_min_per_100'] > 0.0
    assert replay[2]['detail'] == 'imp_frostbolt'


def test_fast_path_roundtrips_into_mc_outer_state():
    path = _simple_path()
    replay = mc_bridge._path_to_replay(path)
    st = opt.outer_state_from_replay(replay, cumulative_hours_hint=path['hours'])
    assert st.respecs_used == 0
    assert st.events[0].level == 10
    assert st.events[-1].level == 12
    assert st.talents == opt.parse_allocation(path['final_allocation'])
    assert min(e.level for e in st.events if e.score_s > 0) == 11


def test_fast_bridge_candidate_is_explicitly_unvalidated():
    c = mc_bridge._bridge_candidate('hard','0',_simple_path(),'buy_water')
    assert c['validated_hours'] is None
    assert c['guidance_only_until_mc_replay'] is True
    assert c['water_mode'] == 'buy_water'


def test_respec_probe_levels_are_bounded_even_with_every_level_as_prior():
    priors = [[lvl] for lvl in range(11, 60)]
    got = opt.derive_respec_probe_levels({}, 11, 59, priors, max_probe_levels=12)
    assert len(got) <= 12
    assert min(got) >= 11 and max(got) <= 59


def test_old_outer_checkpoint_is_downgraded_to_snapshots_not_resumed():
    marker = {11: ['expensive-pool-marker']}
    stale = {
        'phase': 'outer', 'snapshot_mode': 'independent_pnp_v3',
        'snapshot_pools': marker, 'outer_layers': {'huge': ['bad-frontier']},
        'search_meta': {},
    }
    migrated, changed = opt.migrate_outer_search_checkpoint(stale, True)
    assert changed is True
    assert migrated['phase'] == 'snapshots'
    assert migrated['snapshot_pools'] is marker
    assert 'outer_layers' not in migrated


def test_current_outer_checkpoint_remains_resumable():
    current = {
        'phase': 'outer', 'snapshot_pools': {11: []},
        'search_meta': {'outer_search_semantics_version': opt.OUTER_SEARCH_SEMANTICS_VERSION},
    }
    got, changed = opt.migrate_outer_search_checkpoint(current, True)
    assert changed is False
    assert got is current


def test_publish_then_inject_roundtrip_uses_temp_bridge_and_preserves_identity(tmp_path, monkeypatch):
    root=tmp_path/'bridge'
    monkeypatch.setattr(mc_bridge, 'BRIDGE_ROOT', root)
    monkeypatch.setattr(mc_bridge, 'SEED_DIR', root/'seeds')
    monkeypatch.setattr(mc_bridge, 'TOP_CANDIDATES', root/'top_candidates.json')
    monkeypatch.setattr(mc_bridge, 'RESPEC_SCHEDULES', root/'respec_schedules.json')
    monkeypatch.setattr(mc_bridge, 'MANIFEST', root/'manifest.json')
    captured=[]
    monkeypatch.setattr(mc_bridge.sm, 'ensure_dirs', lambda: None)
    monkeypatch.setattr(mc_bridge.sm, 'merge_display_candidates',
                        lambda cards, max_k=10, water_mode='buy_water': captured.extend(cards) or cards)

    mc_bridge.reset(water_mode='buy_water', views='smooth')
    assert mc_bridge.publish_paths('smooth', {'0': _simple_path()}, water_mode='buy_water') == 1
    assert mc_bridge.TOP_CANDIDATES.exists()
    assert mc_bridge.RESPEC_SCHEDULES.exists()
    assert (mc_bridge.SEED_DIR/'lvl_11.json').exists()
    assert (mc_bridge.SEED_DIR/'lvl_12.json').exists()

    raw=mc_bridge._read_json(mc_bridge.TOP_CANDIDATES, [])
    assert len(raw) == 1 and raw[0]['validated_hours'] is None
    result=mc_bridge.inject_into_mc()
    assert result['errors'] == []
    assert result['offered']['buy_water'] == 1
    assert len(captured) == 1
    assert captured[0]['path_id'] == raw[0]['path_id']
    assert captured[0]['fast_analytic_hours'] == raw[0]['search_hours']

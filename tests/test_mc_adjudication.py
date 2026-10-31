import pytest

from src import classic_mage_leveling_optimizer_v10 as eng
from src import state_manager as sm
from src import optimizer_core as opt
from src.mc_adjudication import prepare_candidate_union, adjudicate_candidates


def _replay(tree='frost'):
    talent = 'imp_frostbolt' if tree == 'frost' else 'imp_fireball'
    rot = 'FBo' if tree == 'frost' else 'FBa'
    rows = []
    t = eng.Talents()
    for lvl in (10, 11, 12):
        t = eng.add_point(t, talent)
        rows.append({
            'level': lvl, 'action': 'point', 'detail': talent,
            'allocation': eng.final_allocation(t),
            'rotation': 'unscored' if lvl == 10 else rot,
            'normalized_min_per_100': 0.0 if lvl == 10 else 40.0,
        })
    return rows


def _candidate(tree='frost', source='native', suffix='a'):
    replay = _replay(tree)
    return {
        'id': f'{source}_{suffix}',
        'path_id': sm.candidate_path_id_from_replay(replay),
        'source': source,
        'full_arc': True,
        'replayable': True,
        'replay': replay,
    }


def test_prepare_union_dedupes_same_semantic_path_and_unions_provenance():
    a = _candidate('frost', 'fast_smooth', 'a')
    b = _candidate('frost', 'native_mc', 'b')
    prepared = prepare_candidate_union([a, b], expected_levels=(11, 12))
    assert len(prepared) == 1
    assert set(prepared[0].sources) == {'fast_smooth', 'native_mc'}
    assert prepared[0].path_id == a['path_id']


def test_prepare_union_rejects_malformed_eligible_candidate():
    bad = _candidate('frost')
    bad['replay'][-1] = dict(bad['replay'][-1], rotation='DefinitelyNotASpell')
    with pytest.raises(ValueError):
        prepare_candidate_union([bad], expected_levels=(11, 12))


def _fake_sim(level, talents, policy, cfg, *, target_n, seed, continuation):
    mean = 10.0 if policy.primary == 'frostbolt' else 13.0
    return {'mean_s_per_mob': mean, 'stderr_s_per_mob': 0.02}, {'n': target_n}


def test_adjudication_races_fast_and_native_paths_as_one_union():
    fast = _candidate('frost', 'fast_smooth')
    native = _candidate('fire', 'native_mc')
    out = adjudicate_candidates(
        [fast, native], eng.SimConfig(), expected_levels=(11, 12),
        start_mobs=10, max_mobs=20, simulate_incremental=_fake_sim,
    )
    assert out.race.resolved
    assert out.winner is not None
    assert out.winner.path_id == fast['path_id']
    assert len(out.prepared) == 2


def test_unresolved_race_annotations_do_not_create_authoritative_validation():
    from src.mc_adjudication import candidate_updates_from_adjudication

    a = _candidate('frost', 'fast_smooth')
    b = _candidate('frost', 'native_mc', suffix='other')
    # Make a distinct semantic path with identical synthetic performance.
    b['replay'][-1] = dict(b['replay'][-1], rotation='FBo | FBl≤18%')
    b['path_id'] = sm.candidate_path_id_from_replay(b['replay'])

    def tie_sim(level, talents, policy, cfg, *, target_n, seed, continuation):
        return {'mean_s_per_mob': 10.0, 'stderr_s_per_mob': 1.0}, {'n': target_n}

    out = adjudicate_candidates(
        [a, b], eng.SimConfig(), expected_levels=(11, 12),
        start_mobs=10, max_mobs=20, simulate_incremental=tie_sim,
    )
    assert not out.race.resolved
    updates = candidate_updates_from_adjudication(out, sim_code_hash='hash')
    assert len(updates) == 2
    assert all(u.get('validated_hours') is None for u in updates)
    assert all(u['path_race_resolved'] is False for u in updates)
    assert all(u.get('path_race_ci_lower_hours') is not None for u in updates)


def test_resolved_race_only_winner_becomes_authoritative_validation():
    from src.mc_adjudication import candidate_updates_from_adjudication

    fast = _candidate('frost', 'fast_smooth')
    native = _candidate('fire', 'native_mc')
    out = adjudicate_candidates(
        [fast, native], eng.SimConfig(), expected_levels=(11, 12),
        start_mobs=10, max_mobs=20, simulate_incremental=_fake_sim,
    )
    updates = candidate_updates_from_adjudication(out, sim_code_hash='hash')
    winners = [u for u in updates if u.get('validated_hours') is not None]
    assert len(winners) == 1
    assert winners[0]['path_id'] == fast['path_id']
    assert winners[0]['validation_mode'] == 'adaptive_path_race'
    assert winners[0]['sim_code_hash'] == 'hash'
    losers = [u for u in updates if u['path_id'] != fast['path_id']]
    assert losers and all(u.get('validated_hours') is None for u in losers)


def test_provisionalize_fixed_validation_preserves_measurement_but_removes_authority():
    from src.mc_adjudication import provisionalize_fixed_validation
    card = {
        'validated_hours': 41.25, 'validation_mobs': 100,
        'validation_mode': 'fixed_policy_replay_xp_weighted_pnp',
        'sim_code_hash': 'hash', 'source': 'startup_replay',
    }
    out = provisionalize_fixed_validation(card)
    assert out['validated_hours'] is None
    assert out['fixed_replay_hours'] == 41.25
    assert out['fixed_replay_mobs'] == 100
    assert out['fixed_replay_sim_code_hash'] == 'hash'
    assert out['validation_mode'] == 'fixed_policy_replay_provisional'


def test_pnp_cached_simulator_uses_canonical_level_seed_and_target(monkeypatch):
    from src import mc_adjudication as adj
    calls = []
    monkeypatch.setattr(adj.pnp_cache, 'canonical_seed', lambda level: 123000 + level)
    def fake_eval(level, talents, policy, cfg, target_n, seed):
        calls.append((level, target_n, seed))
        return {'mean_s_per_mob': 10.0, 'stderr_s_per_mob': 0.1}
    monkeypatch.setattr(adj.pnp_cache, 'evaluate_policy', fake_eval)
    p = eng.Policy('x', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    metrics, state = adj.pnp_cached_simulator(20, eng.Talents(), p, eng.SimConfig(), target_n=400, seed=999, continuation={'ignored': True})
    assert calls == [(20, 400, 123020)]
    assert metrics['mean_s_per_mob'] == 10.0
    assert state == {'n': 400}


def _patch_state(monkeypatch, tmp_path):
    from src import state_manager as state
    root = tmp_path / 'state'
    monkeypatch.setattr(state, 'STATE', root)
    monkeypatch.setattr(state, 'RUNTIME', root / 'runtime')
    monkeypatch.setattr(state, 'LOGS', root / 'logs')
    monkeypatch.setattr(state, 'IMPORTS', root / 'imports')
    monkeypatch.setattr(state, 'TRACKS', root / 'tracks')
    monkeypatch.setattr(state, 'BEST', root / 'best')
    monkeypatch.setattr(state, 'CANDIDATES', root / 'best' / 'candidates')
    monkeypatch.setattr(state, 'CHECKPOINTS', root / 'checkpoints')
    monkeypatch.setattr(state, 'HISTORY', root / 'history')
    monkeypatch.setattr(state, 'SEEDS', root / 'seeds')
    monkeypatch.setattr(state, 'USER_CONFIG', root / 'config.json')
    state.ensure_dirs()
    return state


def test_state_adjudication_writes_race_evidence_and_promotes_only_resolved_winner(tmp_path, monkeypatch):
    from src import mc_adjudication as adj
    state = _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(state.pnp_cache, 'current_sim_hash', lambda: 'hash')
    tp = state.track_paths('buy_water')
    rows = []
    for c in (_candidate('frost', 'fast_smooth'), _candidate('fire', 'native_mc')):
        c = dict(c, objective_version=opt.OBJECTIVE_VERSION, search_hours=50.0)
        rows.append(c)
    (tp.best / 'top_candidates.json').write_text(__import__('json').dumps(rows), encoding='utf-8')
    state.migrate_adaptive_validation_authority('buy_water')

    result = adj.adjudicate_state_candidates(
        'buy_water', eng.SimConfig(), expected_levels=(11, 12),
        start_mobs=10, max_mobs=20, max_candidates=4,
        simulate_incremental=_fake_sim,
    )
    assert result is not None and result.race.resolved
    assert result.promoted is True
    stored = __import__('json').loads((tp.best / 'top_candidates.json').read_text(encoding='utf-8'))
    winner = next(x for x in stored if x.get('path_id') == result.winner.path_id)
    assert winner['validation_mode'] == 'adaptive_path_race'
    assert winner['validated_hours'] is not None
    assert winner['path_race_resolved'] is True
    best = state.current_best_meta('buy_water')
    assert best['candidate_id'] == winner['id']
    assert best['validation_mode'] == 'adaptive_path_race'
    losers = [x for x in stored if x.get('path_id') != winner['path_id']]
    assert losers and all(x.get('validated_hours') is None for x in losers)


def test_prepare_union_accepts_legacy_level11_start_by_reconstructing_unscored_prefix():
    legacy = _candidate('frost', 'historical')
    legacy['replay'] = legacy['replay'][1:]  # omit lvl10 unscored point row
    legacy['path_id'] = sm.candidate_path_id_from_replay(legacy['replay'])
    prepared = prepare_candidate_union([legacy], expected_levels=(11, 12))
    assert len(prepared) == 1
    assert [x.level for x in prepared[0].frozen.levels] == [11, 12]


def test_state_adjudication_skips_one_corrupt_persisted_candidate(tmp_path, monkeypatch, capsys):
    from src import mc_adjudication as adj
    state = _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(state.pnp_cache, 'current_sim_hash', lambda: 'hash')
    tp = state.track_paths('buy_water')

    frost = dict(_candidate('frost', 'native_mc', 'goodf'),
                 objective_version=opt.OBJECTIVE_VERSION, search_hours=50.0)
    fire = dict(_candidate('fire', 'native_mc', 'goodx'),
                objective_version=opt.OBJECTIVE_VERSION, search_hours=51.0)
    bad = dict(_candidate('frost', 'historical', 'bad'),
               objective_version=opt.OBJECTIVE_VERSION, search_hours=49.0)
    bad['replay'] = [dict(x) for x in bad['replay']]
    bad['replay'][-1]['rotation'] = 'DefinitelyNotASpell'
    bad['path_id'] = sm.candidate_path_id_from_replay(bad['replay'])
    (tp.best / 'top_candidates.json').write_text(
        __import__('json').dumps([bad, frost, fire]), encoding='utf-8')

    result = adj.adjudicate_state_candidates(
        'buy_water', eng.SimConfig(), expected_levels=(11, 12),
        start_mobs=10, max_mobs=20, max_candidates=4,
        simulate_incremental=_fake_sim,
    )
    assert result is not None
    assert len(result.prepared) == 2
    assert all(p.path_id != bad['path_id'] for p in result.prepared)
    out = capsys.readouterr().out
    assert '[path race skip]' in out and bad['id'] in out

def test_replay_primary_school_filter_uses_rotation_not_talent_tree():
    frost = _replay('frost')
    fire = _replay('fire')
    assert opt.replay_matches_primary_school(frost, 'frost')
    assert not opt.replay_matches_primary_school(fire, 'frost')
    assert opt.replay_matches_primary_school(fire, 'all')


def test_state_adjudication_frost_mode_excludes_persisted_fire_paths(tmp_path, monkeypatch):
    from src import mc_adjudication as adj
    state = _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(state.pnp_cache, 'current_sim_hash', lambda: 'hash')
    tp = state.track_paths('buy_water')
    rows = [
        dict(_candidate('frost', 'fast_smooth'), objective_version=opt.OBJECTIVE_VERSION, search_hours=50.0),
        dict(_candidate('fire', 'native_mc'), objective_version=opt.OBJECTIVE_VERSION, search_hours=49.0),
    ]
    (tp.best / 'top_candidates.json').write_text(__import__('json').dumps(rows), encoding='utf-8')
    result = adj.adjudicate_state_candidates(
        'buy_water', eng.SimConfig(), expected_levels=(11,12), school='frost',
        start_mobs=10, max_mobs=20, max_candidates=4, simulate_incremental=_fake_sim,
    )
    assert result is not None
    assert len(result.prepared) == 1
    assert eng.policy_primary_school(result.prepared[0].frozen.levels[0].policy) == 'frost'

def test_school_scoped_best_does_not_replace_all_school_best(tmp_path, monkeypatch):
    state = _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(state.pnp_cache, 'current_sim_hash', lambda: 'hash')
    frost = dict(_candidate('frost', 'native_mc', 'frostbest'),
                 objective_version=opt.OBJECTIVE_VERSION,
                 validated_hours=60.0, validation_mobs=100,
                 validation_mode='adaptive_path_race', sim_code_hash='hash')
    fire = dict(_candidate('fire', 'native_mc', 'globalbest'),
                objective_version=opt.OBJECTIVE_VERSION,
                validated_hours=50.0, validation_mobs=100,
                validation_mode='adaptive_path_race', sim_code_hash='hash')
    assert state.set_authoritative_race_winner(fire, None, 'buy_water', school='all')
    assert state.set_authoritative_race_winner(frost, None, 'buy_water', school='frost')
    assert state.current_best_meta('buy_water','all')['candidate_id'] == fire['id']
    assert state.current_best_meta('buy_water','frost')['candidate_id'] == frost['id']

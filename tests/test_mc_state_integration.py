import json
from types import SimpleNamespace

from src import optimizer_core as opt
from src import state_manager as sm


def test_merge_same_path_preserves_fast_provenance_on_mc_validation(tmp_path, monkeypatch):
    best = tmp_path / 'best'
    best.mkdir(parents=True)
    path_id = 'path_deadbeef'
    prior = {
        'id': 'fast_' + path_id,
        'path_id': path_id,
        'source': 'fast_bridge_smooth',
        'sources': ['fast_bridge_smooth'],
        'objective_version': opt.OBJECTIVE_VERSION,
        'full_arc': True,
        'replayable': True,
        'search_hours': 100.0,
        'validated_hours': None,
        'fast_analytic_hours': 100.0,
        'fast_bridge_id': 'fast_' + path_id,
        'replay': [],
    }
    (best / 'top_candidates.json').write_text(json.dumps([prior]), encoding='utf-8')

    incoming = {
        'id': 'mc_replay_different_presentation_id',
        'path_id': path_id,
        'source': 'startup_replay',
        'objective_version': opt.OBJECTIVE_VERSION,
        'full_arc': True,
        'replayable': True,
        'search_hours': 99.0,
        'validated_hours': 103.5,
        'validation_mobs': 400,
        'sim_code_hash': 'simhash',
        'replay': [],
    }

    monkeypatch.setattr(sm, 'track_paths', lambda mode='buy_water': SimpleNamespace(best=best))
    monkeypatch.setattr(sm.pnp_cache, 'record_path_candidates', lambda *a, **k: None)
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'simhash')
    captured = {}
    monkeypatch.setattr(sm, 'write_candidate_files', lambda rows, water_mode='buy_water': captured.setdefault('rows', rows))

    out = sm.merge_display_candidates([incoming], max_k=8, water_mode='buy_water')
    row = next(c for c in out if c.get('path_id') == path_id)

    assert row['validated_hours'] == 103.5
    assert row['fast_analytic_hours'] == 100.0
    assert row['fast_bridge_id'] == 'fast_' + path_id
    assert set(row['sources']) >= {'fast_bridge_smooth', 'startup_replay'}
    assert row['fast_vs_mc_delta_hours'] == 3.5


def _patch_state_root(monkeypatch, tmp_path):
    state = tmp_path / 'state'
    monkeypatch.setattr(sm, 'STATE', state)
    monkeypatch.setattr(sm, 'RUNTIME', state / 'runtime')
    monkeypatch.setattr(sm, 'LOGS', state / 'logs')
    monkeypatch.setattr(sm, 'IMPORTS', state / 'imports')
    monkeypatch.setattr(sm, 'TRACKS', state / 'tracks')
    monkeypatch.setattr(sm, 'BEST', state / 'best')
    monkeypatch.setattr(sm, 'CANDIDATES', state / 'best' / 'candidates')
    monkeypatch.setattr(sm, 'CHECKPOINTS', state / 'checkpoints')
    monkeypatch.setattr(sm, 'HISTORY', state / 'history')
    monkeypatch.setattr(sm, 'SEEDS', state / 'seeds')
    monkeypatch.setattr(sm, 'USER_CONFIG', state / 'config.json')
    sm.ensure_dirs()
    return state


def test_objective_migration_archives_path_rankings_but_preserves_seed_banks(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    tp = sm.track_paths('buy_water')
    seed = tp.seeds / 'lvl_20.json'
    seed.write_text(json.dumps({'level': 20, 'candidates': [{'allocation': 'imp_frostbolt=5'}]}), encoding='utf-8')
    (tp.best / 'best_meta.json').write_text(json.dumps({
        'best_validated_hours': 42.0,
        'candidate_id': 'old',
        'objective_version': 'legacy_equal100',
    }), encoding='utf-8')
    (tp.best / 'top_candidates.json').write_text(json.dumps([{
        'id': 'old', 'validated_hours': 42.0, 'objective_version': 'legacy_equal100'
    }]), encoding='utf-8')

    sm.migrate_objective_state('buy_water')

    meta = json.loads((tp.best / 'best_meta.json').read_text(encoding='utf-8'))
    assert meta['objective_version'] == opt.OBJECTIVE_VERSION
    assert meta['best_validated_hours'] is None
    assert json.loads((tp.best / 'top_candidates.json').read_text(encoding='utf-8')) == []
    assert (tp.history / 'legacy_equal100_objective' / 'best_meta.json').exists()
    assert (tp.history / 'legacy_equal100_objective' / 'top_candidates.json').exists()
    assert seed.exists(), 'local per-level seed banks must survive objective migration'


def test_current_best_meta_quarantines_stale_sim_hash(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    tp = sm.track_paths('buy_water')
    (tp.best / 'best_meta.json').write_text(json.dumps({
        'best_validated_hours': 50.0,
        'candidate_id': 'oldhash',
        'objective_version': opt.OBJECTIVE_VERSION,
        'sim_code_hash': 'old-hash',
    }), encoding='utf-8')
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'new-hash')

    meta = sm.current_best_meta('buy_water')
    assert meta['best_validated_hours'] is None
    assert meta['stale_previous_hours'] == 50.0
    assert meta['stale_previous_hash'] == 'old-hash'
    assert meta['sim_code_hash'] == 'new-hash'


def test_promote_requires_current_objective_and_current_sim_hash(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'cur')
    base = {
        'id': 'cand', 'source': 'race', 'validated_hours': 40.0,
        'validation_mobs': 400, 'objective_version': opt.OBJECTIVE_VERSION,
        'sim_code_hash': 'cur',
    }
    assert sm.promote_if_better(dict(base, objective_version='old'), water_mode='buy_water') is False
    assert sm.promote_if_better(dict(base, sim_code_hash='old'), water_mode='buy_water') is False
    assert sm.promote_if_better(base, water_mode='buy_water') is True
    assert sm.current_best_meta('buy_water')['best_validated_hours'] == 40.0


def test_adaptive_authority_migration_demotes_fixed_n_best_but_keeps_measurement(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    tp = sm.track_paths('buy_water')
    old = {
        'id': 'fixed', 'path_id': 'p1', 'source': 'startup_replay',
        'objective_version': opt.OBJECTIVE_VERSION,
        'validated_hours': 40.0, 'validation_mobs': 100,
        'validation_mode': 'fixed_policy_replay_xp_weighted_pnp',
        'sim_code_hash': 'cur', 'full_arc': True, 'replayable': True, 'replay': [],
    }
    (tp.best / 'top_candidates.json').write_text(json.dumps([old]), encoding='utf-8')
    (tp.best / 'best_meta.json').write_text(json.dumps({
        'best_validated_hours': 40.0, 'candidate_id': 'fixed',
        'objective_version': opt.OBJECTIVE_VERSION, 'sim_code_hash': 'cur',
        'validation_mode': 'fixed_policy_replay_xp_weighted_pnp',
    }), encoding='utf-8')
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'cur')

    sm.migrate_adaptive_validation_authority('buy_water')

    meta = json.loads((tp.best / 'best_meta.json').read_text(encoding='utf-8'))
    assert meta['best_validated_hours'] is None
    assert meta['validation_authority_version'] == sm.VALIDATION_AUTHORITY_VERSION
    rows = json.loads((tp.best / 'top_candidates.json').read_text(encoding='utf-8'))
    assert rows[0]['validated_hours'] is None
    assert rows[0]['fixed_replay_hours'] == 40.0
    assert rows[0]['fixed_replay_mobs'] == 100
    assert (tp.history / 'legacy_fixed_validation_authority' / 'best_meta.json').exists()


def test_adaptive_authority_promotion_rejects_provisional_fixed_replay(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'cur')
    sm.migrate_adaptive_validation_authority('buy_water')
    base = {
        'id': 'cand', 'source': 'test', 'validated_hours': 40.0,
        'validation_mobs': 400, 'objective_version': opt.OBJECTIVE_VERSION,
        'sim_code_hash': 'cur',
    }
    assert sm.promote_if_better(
        dict(base, validation_mode='fixed_policy_replay_xp_weighted_pnp'),
        water_mode='buy_water', require_adaptive=True,
    ) is False
    assert sm.promote_if_better(
        dict(base, validation_mode='adaptive_path_race'),
        water_mode='buy_water', require_adaptive=True,
    ) is True


def test_resolved_adaptive_race_winner_replaces_old_authority_even_if_reestimated_slower(tmp_path, monkeypatch):
    _patch_state_root(monkeypatch, tmp_path)
    tp = sm.track_paths('buy_water')
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'cur')
    (tp.best / 'best_meta.json').write_text(json.dumps({
        'best_validated_hours': 39.0, 'candidate_id': 'old', 'source': 'adaptive_path_race',
        'validation_mobs': 100, 'validation_mode': 'adaptive_path_race',
        'validation_authority_version': sm.VALIDATION_AUTHORITY_VERSION,
        'objective_version': opt.OBJECTIVE_VERSION, 'sim_code_hash': 'cur',
    }), encoding='utf-8')
    winner = {
        'id': 'reestimated', 'source': 'adaptive_path_race', 'validated_hours': 40.0,
        'validation_mobs': 800, 'validation_mode': 'adaptive_path_race',
        'objective_version': opt.OBJECTIVE_VERSION, 'sim_code_hash': 'cur',
    }
    assert sm.set_authoritative_race_winner(winner, water_mode='buy_water') is True
    meta = sm.current_best_meta('buy_water')
    assert meta['candidate_id'] == 'reestimated'
    assert meta['best_validated_hours'] == 40.0
    assert meta['validation_mobs'] == 800


def test_startup_replay_dedupes_same_replay_with_stale_persisted_path_ids(tmp_path, monkeypatch):
    """Replay content is authoritative; historical path_id values must not duplicate work."""
    _patch_state_root(monkeypatch, tmp_path)
    tp = sm.track_paths('buy_water')
    replay = [
        {
            'level': 11,
            'action': 'point',
            'detail': 'imp_frostbolt',
            'allocation': 'imp_frostbolt=2',
            'rotation': 'FBo',
            'normalized_min_per_100': 40.0,
        },
    ]
    base = {
        'objective_version': opt.OBJECTIVE_VERSION,
        'full_arc': True,
        'replayable': True,
        'validated_hours': None,
        'search_hours': 100.0,
        'replay': replay,
    }
    rows = [
        dict(base, id='same-display-a', path_id='stale-a'),
        dict(base, id='same-display-b', path_id='stale-b', search_hours=101.0),
    ]
    (tp.best / 'top_candidates.json').write_text(json.dumps(rows), encoding='utf-8')
    monkeypatch.setattr(sm.pnp_cache, 'current_sim_hash', lambda: 'current-hash')

    out = sm.startup_replay_candidates('buy_water', global_top=5)

    assert len(out) == 1
    assert out[0]['path_id'] == sm.candidate_path_id_from_replay(replay)

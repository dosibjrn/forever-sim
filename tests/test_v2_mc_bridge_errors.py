import json
from types import SimpleNamespace

import pytest

from src import classic_mage_leveling_optimizer_v10 as eng
from src import state_manager as sm
from src.v2 import mc_bridge


def _bridge_paths(monkeypatch, tmp_path):
    root = tmp_path / 'bridge'
    monkeypatch.setattr(mc_bridge, 'BRIDGE_ROOT', root)
    monkeypatch.setattr(mc_bridge, 'SEED_DIR', root / 'seeds')
    monkeypatch.setattr(mc_bridge, 'TOP_CANDIDATES', root / 'top_candidates.json')
    monkeypatch.setattr(mc_bridge, 'RESPEC_SCHEDULES', root / 'respec_schedules.json')
    monkeypatch.setattr(mc_bridge, 'MANIFEST', root / 'manifest.json')
    root.mkdir(parents=True, exist_ok=True)
    return root


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
             'allocation': eng.final_allocation(t11), 'policy': eng.policy_desc(pol, 11),
             'score_s_per_100': 2400.0},
            {'level': 12, 'kind': 'point', 'talent_added': 'imp_frostbolt',
             'allocation': eng.final_allocation(t12), 'policy': eng.policy_desc(pol, 12),
             'score_s_per_100': 2300.0},
        ],
    }


def test_read_json_malformed_returns_default(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('{ definitely not json', encoding='utf-8')
    assert mc_bridge._read_json(p, {'fallback': True}) == {'fallback': True}
    assert mc_bridge._read_json(tmp_path / 'missing.json', []) == []


def test_publish_level_candidates_dedupes_keeps_best_caps_and_skips_bad_node(tmp_path, monkeypatch):
    _bridge_paths(monkeypatch, tmp_path)
    t = eng.Talents(imp_frostbolt=2)
    policy = eng.Policy('frost', 'frostbolt')
    worse = SimpleNamespace(talents=t, score_s_per_100=2500.0, policy=policy)
    better = SimpleNamespace(talents=t, score_s_per_100=2400.0, policy=policy)
    other = SimpleNamespace(talents=eng.Talents(imp_frostbolt=1, elemental_precision=1),
                            score_s_per_100=2450.0, policy=policy)
    bad = SimpleNamespace(talents=None, score_s_per_100='nope', policy=policy)

    mc_bridge.publish_level_candidates(11, [worse, better, other, bad], view='smooth',
                                       water_mode='buy_water', cap=1)
    payload = json.loads((mc_bridge.SEED_DIR / 'lvl_11.json').read_text(encoding='utf-8'))
    assert len(payload['candidates']) == 1
    row = payload['candidates'][0]
    assert row['analytic_score_s_per_100'] == 2400.0
    assert row['allocation'] == eng.final_allocation(t)
    assert payload['meta']['guidance_only'] is True


def test_prefix_point_names_rejects_unreachable_illegal_target():
    with pytest.raises(ValueError, match='cannot construct legal prefix'):
        mc_bridge._prefix_point_names(eng.Talents(winters_chill=1))


def test_path_to_replay_rejects_empty_and_talent_added_mismatch():
    with pytest.raises(ValueError, match='no steps'):
        mc_bridge._path_to_replay({'steps': []})

    path = _simple_path()
    path['steps'][1] = dict(path['steps'][1], talent_added='elemental_precision')
    with pytest.raises(ValueError, match='talent_added mismatch'):
        mc_bridge._path_to_replay(path)


def test_publish_paths_recovers_from_nonlist_state_and_skips_invalid_paths(tmp_path, monkeypatch):
    _bridge_paths(monkeypatch, tmp_path)
    mc_bridge.TOP_CANDIDATES.write_text(json.dumps({'corrupt_shape': True}), encoding='utf-8')
    mc_bridge.MANIFEST.write_text(json.dumps([]), encoding='utf-8')

    good = _simple_path()
    broken = _simple_path()
    broken['steps'][1] = dict(broken['steps'][1], allocation=good['steps'][0]['allocation'])
    count = mc_bridge.publish_paths('smooth', {
        '0': good,
        '1': {'error': 'failed', 'hours': 2.0},
        '2': {'steps': [], 'hours': None},
        '3': broken,
    }, water_mode='buy_water')

    assert count == 1
    rows = json.loads(mc_bridge.TOP_CANDIDATES.read_text(encoding='utf-8'))
    assert len(rows) == 1 and rows[0]['guidance_only_until_mc_replay'] is True
    manifest = json.loads(mc_bridge.MANIFEST.read_text(encoding='utf-8'))
    assert manifest['status'] == 'ready' and manifest['path_candidates'] == 1


def test_inject_into_mc_fault_isolates_bad_replay_and_offers_good_one(tmp_path, monkeypatch):
    _bridge_paths(monkeypatch, tmp_path)
    good = mc_bridge._bridge_candidate('smooth', '0', _simple_path(), 'buy_water')
    bad = dict(good, id='bad-replay', path_id='bad-replay', replay=[{
        'level': 11, 'action': 'point', 'detail': 'imp_frostbolt',
        'allocation': 'imp_frostbolt=5', 'rotation': 'FBo',
        'normalized_min_per_100': 40.0,
    }])
    mc_bridge.TOP_CANDIDATES.write_text(json.dumps([bad, good]), encoding='utf-8')

    captured = []
    monkeypatch.setattr(mc_bridge.sm, 'ensure_dirs', lambda: None)
    monkeypatch.setattr(mc_bridge.sm, 'merge_display_candidates',
                        lambda cards, max_k=10, water_mode='buy_water': captured.extend(cards) or cards)

    result = mc_bridge.inject_into_mc()
    assert result['offered'] == {'buy_water': 1}
    assert len(result['errors']) == 1 and result['errors'][0].startswith('bad-replay:')
    assert len(captured) == 1
    assert captured[0]['fast_bridge_id'] == good['id']
    assert captured[0]['validated_hours'] is None


def test_publish_paths_ignores_named_auxiliary_routes(tmp_path, monkeypatch, capsys):
    _bridge_paths(monkeypatch, tmp_path)
    good = _simple_path()
    auxiliary = _simple_path()
    auxiliary["respecs_used"] = 1
    count = mc_bridge.publish_paths("smooth", {
        "0": good,
        "per_level_best": auxiliary,
    }, water_mode="buy_water")

    assert count == 1
    assert "per_level_best" not in capsys.readouterr().out
    rows = json.loads(mc_bridge.TOP_CANDIDATES.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["budget"] == 0

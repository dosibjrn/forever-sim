from types import SimpleNamespace

from src import game_context
from src.engine_registry import reset_engine_cache
from src.v2 import experimental_classes as ec
from src.v2.icon_provenance import item_icon


def test_wolfsbane_has_exact_item_identity_and_listener_source_url():
    meta = item_icon('Wolfsbane')
    assert meta['entity_kind'] == 'item'
    assert meta['entity_id'] == 267369
    assert meta['provenance_url'].endswith('/forever/item=267369/wolfsbane')

    try:
        game_context.configure('forever', 'paladin')
        reset_engine_cache()
        from src.rulesets.forever.classes.paladin import gear
        setup = next(g for g in gear.archetypes(20) if g.name == '2h_normal')
        row = gear.gear_snapshot(setup)['slots']['weapon']
        assert row['name'] == 'Wolfsbane'
        assert row['source_url'].endswith('/forever/item=267369/wolfsbane')
    finally:
        game_context.configure('classic', 'mage')
        reset_engine_cache()


def test_experimental_normal_run_publishes_route_stat_matrices(monkeypatch, tmp_path):
    calls = []
    from src.v2 import spec_matrix

    def fake_generate_all(class_name, targets, *, project_root='.'):
        calls.append((class_name, list(targets)))
        return tmp_path / 'spec_matrix.json', {'matrices': {'20:unconstrained': {}}}

    monkeypatch.setattr(spec_matrix, 'generate_all', fake_generate_all)
    old_name = getattr(ec.eng, 'CLASS_NAME', None)
    try:
        game_context.configure('forever', 'paladin')
        reset_engine_cache()
        path, count, error = ec._publish_spec_matrices(10, 20, SimpleNamespace(stat_weights=True))
        assert error is None
        assert path.endswith('spec_matrix.json')
        assert count == 1
        assert calls == [('paladin', [20])]

        calls.clear()
        path, count, error = ec._publish_spec_matrices(10, 20, SimpleNamespace(stat_weights=False))
        assert (path, count, error) == (None, 0, None)
        assert calls == []
    finally:
        game_context.configure('classic', 'mage')
        reset_engine_cache()

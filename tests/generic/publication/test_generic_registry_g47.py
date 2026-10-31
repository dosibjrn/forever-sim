from pathlib import Path
from src.game.data.forever import registry
from src.v2.decision_dashboard import GENERIC_CLASSES, _generic_ui_metadata
from src.version import SOFTWARE_VERSION


def test_g47_catalog_and_ui_discovery():
    assert tuple(GENERIC_CLASSES) == registry.registered_class_keys()
    assert set(_generic_ui_metadata()) == set(registry.registered_class_keys())
    for cls, metadata in _generic_ui_metadata().items():
        assert metadata['display_name'] and metadata['source_registry'] == 'forever_game_ir'


def test_g47_registering_new_provider_requires_no_dashboard_or_ui_branch(monkeypatch):
    monkeypatch.setitem(registry._PROVIDERS, 'test_beast', lambda level: None)
    assert 'test_beast' in registry.generic_class_metadata()
    # Dashboard reads runtime registry, not a hard-coded class tuple.
    assert 'test_beast' in _generic_ui_metadata()
    source = Path('src/listener.py').read_text()
    assert "if(data?.active_backend==='generic')return Object.keys(data?.class_metadata||{})" in source
    assert 'test_beast' not in source


def test_g47_version():
    assert tuple(map(int, SOFTWARE_VERSION.split('.'))) >= (0, 11, 48, 171)

"""Native class selection is a plugin boundary, not a Warlock-only optimizer."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.v2 import native_class_adapters as registry


def test_all_nine_classes_have_the_same_normalized_optimizer_choice():
    assert registry.FOREVER_CLASSES == frozenset({
        "druid", "hunter", "mage", "paladin", "priest",
        "rogue", "shaman", "warlock", "warrior",
    })
    for name in registry.FOREVER_CLASSES:
        assert registry.normalize_class_name(name.upper()) == name
    with pytest.raises(ValueError, match="unknown Forever class"):
        registry.normalize_class_name("necromancer")


def test_warlock_is_one_registered_class_plugin_not_the_shared_default():
    adapter = registry.resolve_native_class_adapter("WARLOCK")
    assert adapter.class_name == "warlock"
    assert adapter.default_source == Path(
        "fixtures/warlock-l20-native-paid-30s.request.json")
    assert callable(adapter.evaluator_factory)


def test_mage_plugin_is_discovered_without_modifying_shared_optimizer(monkeypatch):
    class FakeMageNativeEvaluator:
        pass

    observed = []
    def fake_import(name):
        observed.append(name)
        return SimpleNamespace(
            PersistentNativeEvaluator=FakeMageNativeEvaluator,
            DEFAULT_NATIVE_SOURCE="fixtures/mage.test.json",
        )

    monkeypatch.setattr(registry, "import_module", fake_import)
    adapter = registry.resolve_native_class_adapter("MAGE")
    assert observed == ["tools.wf_mage_native_persistent_optimizer"]
    assert adapter.class_name == "mage"
    assert adapter.evaluator_factory is FakeMageNativeEvaluator
    assert adapter.default_source == Path("fixtures/mage.test.json")


def test_missing_real_native_class_adapter_fails_without_pretending_support(monkeypatch):
    def missing_module(name):
        raise ModuleNotFoundError("Missing " + name, name=name)

    monkeypatch.setattr(registry, "import_module", missing_module)
    with pytest.raises(registry.NativeAdapterUnavailable,
                       match="source-native adapter for 'druid' is not implemented"):
        registry.resolve_native_class_adapter("druid")


def test_missing_dependency_of_adapter_is_not_masked_as_unimplemented(monkeypatch):
    def broken_import(name):
        raise ModuleNotFoundError("Missing private dependency", name="the_private_dependency")

    monkeypatch.setattr(registry, "import_module", broken_import)
    with pytest.raises(ModuleNotFoundError, match="Missing private dependency"):
        registry.resolve_native_class_adapter("shaman")

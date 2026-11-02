"""P7 source-native and live 2D producers must use the same explicit RNG mode.

These are environment/dispatch tests, not real pinned Rust gate acceptance.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _producer():
    path = Path(__file__).resolve().parents[1] / (
        "integrations/mythicsim-rust/live_world_probe.py")
    spec = importlib.util.spec_from_file_location("p7_rng_source_producer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ("balanced", "stochastic"))
def test_native_source_control_explicit_rng_mode(monkeypatch, tmp_path, mode):
    producer = _producer()
    request = tmp_path / "source.json"
    request.write_text(json.dumps({"simOptions": {
        "iterations": 10000, "randomSeed": "1179706472"}}))
    binary = tmp_path / "forever-engine"
    binary.write_text("injected test only")
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(kwargs["env"])
        source = json.loads(Path(argv[argv.index("--request") + 1]).read_text())
        assert source["simOptions"]["iterations"] == 3
        assert source["simOptions"]["randomSeed"] == "1179706472"
        Path(argv[argv.index("--outfile") + 1]).write_text(json.dumps({
            "identity": {"engine": "forever-engine"},
            "result": {"iterationsDone": 3,
                       "raidMetrics": {"dps": {"avg": 730.0}},
                       "firstIterationDuration": 120.0}}))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(producer.subprocess, "run", fake_run)
    result = producer.native_source_control(binary, request, 3, rng_mode=mode)
    assert result["native_dps"] == 730.0
    assert len(seen) == 1
    assert seen[0]["WOWSIM_RNG_MODE"] == mode
    assert "FOREVER_GSIM_WORLD_BRIDGE" not in seen[0]


@pytest.mark.parametrize("mode", ("balanced", "stochastic"))
def test_live_world_process_explicit_rng_mode(monkeypatch, tmp_path, mode):
    producer = _producer()
    request = tmp_path / "source.json"
    request.write_text(json.dumps({
        "simOptions": {"iterations": 10000, "randomSeed": "1179706472"},
        "raid": {"parties": [{"players": [{"distanceFromTarget": 15}]}]},
        "encounter": {"targets": [{"level": 63}]},
    }))
    binary = tmp_path / "forever-engine"
    binary.write_text("injected test only")
    seen = []

    def fake_prepare(argv, **kwargs):
        Path(argv[argv.index("--outfile") + 1]).write_text(
            json.dumps({"request_sha256": "prepared-id"}))
        return SimpleNamespace(returncode=0)

    def fake_popen(argv, **kwargs):
        seen.append(kwargs["env"])
        raise RuntimeError("EXPECTED_NATIVE_WORLD_ENV_CAPTURE")

    monkeypatch.setattr(producer.subprocess, "run", fake_prepare)
    monkeypatch.setattr(producer.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError, match="EXPECTED_NATIVE_WORLD_ENV_CAPTURE"):
        producer.run(binary, request, distance=15., iterations=3, rng_mode=mode)
    assert len(seen) == 1
    assert seen[0]["WOWSIM_RNG_MODE"] == mode
    assert seen[0]["FOREVER_GSIM_WORLD_BRIDGE"] == "1"


def test_invalid_rng_mode_fails_before_source_execution(tmp_path):
    producer = _producer()
    with pytest.raises(ValueError, match="RNG_MODE_INVALID"):
        producer.run(tmp_path / "no-binary", tmp_path / "no-request",
                     distance=15., rng_mode="unknown")
    with pytest.raises(ValueError, match="RNG_MODE_INVALID"):
        producer.native_source_control(
            tmp_path / "no-binary", tmp_path / "no-request", 3,
            rng_mode="unknown")


def test_selected_rust_build_reuses_historical_full_rng_patch_chain():
    """Do not regress to pre-WF659 dispatch or omit the recovered >100% fix.

    Pure wiring guard: actual Rust and 2D behavior is tested by the existing
    manual native-world workflow, not simulated in Python.
    """
    patcher = (Path(__file__).resolve().parents[1] /
               "integrations/mythicsim-rust/patch_world_ingress.py").read_text()
    original = "wf652_apply_balanced.py"
    typed = "wf659_typed_rng.py"
    migrated = "wf660_boolean_migration.py"
    extremes = "rng_extreme_probability_fix.py"
    audit = "wf659_rng_boolean_audit.py"
    for name in (original, typed, migrated, extremes, audit):
        assert name in patcher, f"Selected Rust production patch missing: {name}"
    assert patcher.index(original) < patcher.index(typed)
    assert patcher.index(typed) < patcher.index(migrated)
    assert patcher.index(migrated) < patcher.index(extremes)
    assert patcher.index(extremes) < patcher.index(audit)
    assert "wf_l60_rng_extreme_tests" in patcher

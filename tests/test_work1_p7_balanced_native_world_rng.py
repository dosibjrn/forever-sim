"""P7 source-native and live 2D producers must use the same explicit RNG mode.

These are explicit CLI-mode dispatch tests, not real P7 gate acceptance.
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
        seen.append((argv, kwargs["env"]))
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
    assert seen[0][0][seen[0][0].index("--rng-mode") + 1] == mode
    assert "WOWSIM_RNG_MODE" not in seen[0][1]
    assert "FOREVER_GSIM_WORLD_BRIDGE" not in seen[0][1]


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
        seen.append((argv, kwargs["env"]))
        raise RuntimeError("EXPECTED_NATIVE_WORLD_ENV_CAPTURE")

    monkeypatch.setattr(producer.subprocess, "run", fake_prepare)
    monkeypatch.setattr(producer.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError, match="EXPECTED_NATIVE_WORLD_ENV_CAPTURE"):
        producer.run(binary, request, distance=15., iterations=3, rng_mode=mode)
    assert len(seen) == 1
    assert seen[0][0][seen[0][0].index("--rng-mode") + 1] == mode
    assert "WOWSIM_RNG_MODE" not in seen[0][1]
    assert seen[0][1]["FOREVER_GSIM_WORLD_BRIDGE"] == "1"


def test_native_and_live_world_use_identical_iteration_limited_request(
        monkeypatch, tmp_path):
    """The native control and live bridge must run the same first N RNG stream."""
    producer = _producer()
    request = tmp_path / "source.json"
    original = {
        "simOptions": {"iterations": 10000, "randomSeed": "1179706472"},
        "raid": {"parties": [{"players": [{"distanceFromTarget": 15}]}]},
        "encounter": {"targets": [{"level": 63}]},
    }
    request.write_text(json.dumps(original))
    binary = tmp_path / "forever-engine"
    binary.write_text("injected test only")
    seen = []

    def fake_run(argv, **kwargs):
        source_path = Path(argv[argv.index("--request") + 1])
        source = json.loads(source_path.read_text())
        seen.append((argv[1], source))
        output = Path(argv[argv.index("--outfile") + 1])
        if argv[1] == "prepare":
            output.write_text(json.dumps({"request_sha256": "prepared-id"}))
        else:
            output.write_text(json.dumps({
                "identity": {"engine": "forever-engine"},
                "result": {"iterationsDone": 3,
                           "raidMetrics": {"dps": {"avg": 730.0}},
                           "firstIterationDuration": 120.0},
            }))
        return SimpleNamespace(returncode=0, stderr="")

    def fake_popen(argv, **kwargs):
        source_path = Path(argv[argv.index("--request") + 1])
        seen.append(("world-sim", json.loads(source_path.read_text())))
        raise RuntimeError("EXPECTED_NATIVE_WORLD_ENV_CAPTURE")

    monkeypatch.setattr(producer.subprocess, "run", fake_run)
    monkeypatch.setattr(producer.subprocess, "Popen", fake_popen)
    native = producer.native_source_control(
        binary, request, 3, rng_mode="stochastic")
    assert native["iterations"] == 3
    with pytest.raises(RuntimeError, match="EXPECTED_NATIVE_WORLD_ENV_CAPTURE"):
        producer.run(binary, request, distance=15., iterations=3,
                     rng_mode="stochastic")

    assert [kind for kind, _ in seen] == ["sim", "prepare", "world-sim"]
    assert seen[0][1] == seen[1][1] == seen[2][1]
    assert all(source["simOptions"]["iterations"] == 3 for _, source in seen)
    assert all(source["simOptions"]["randomSeed"] == "1179706472"
               for _, source in seen)
    assert request.read_text() == json.dumps(original)


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
    # The explicit required mode is a separate audited port, applied after
    # the historical RNG repair chain in the fork publisher and production CI.
    publisher = (Path(__file__).resolve().parents[1] /
                 "scripts/bootstrap_mythicsim_rust_fork.sh").read_text()
    selected = (Path(__file__).resolve().parents[1] /
                ".github/workflows/rust-upstream-fork.yml").read_text()
    typed_mode = "port_native_typed_rng.py"
    assert typed_mode in publisher
    assert typed_mode in selected
    assert publisher.index(typed_mode) < publisher.index("cargo test --locked --lib persistent_next_target")

def test_reference_cli_uses_explicit_stochastic_mode(monkeypatch, tmp_path, capsys):
    """The standalone reference diagnostic must preserve its former stochastic default."""
    import sys

    producer = _producer()
    request = tmp_path / "saved-request.json"
    request.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid", "balanceDruid": {},
            "distanceFromTarget": 15.0,
        }]}]},
        "encounter": {"targets": [{"level": 63}]},
    }))
    binary = tmp_path / "forever-engine"
    calls = []

    def native(binary, request, iterations, *, rng_mode):
        calls.append(("native", rng_mode, iterations))
        return {"iterations": iterations, "native_dps": 730.0,
                "first_duration_s": 120.0}

    def live(binary, request, *, distance, iterations, rng_mode):
        calls.append(("world", rng_mode, iterations))
        return {"iterations_done": iterations, "native_dps": 730.0,
                "world_mean_dps": 730.0, "sampled_duration_s": 120.0,
                "source_request_raw_sha256": "test-request",
                "native_damage_events": iterations,
                "native_world_ticks": iterations}

    monkeypatch.setattr(producer, "native_source_control", native)
    monkeypatch.setattr(producer, "run", live)
    monkeypatch.setattr(sys, "argv", [
        "live_world_probe.py", "--binary", str(binary),
        "--request", str(request), "--reference-iterations", "2",
    ])
    producer.main()
    assert calls == [("native", "stochastic", 2), ("world", "stochastic", 2)]
    assert "checkpoint_certified" in capsys.readouterr().out

def test_upstream_candidate_verification_passes_explicit_rng_mode():
    """No source-verification helper may rely on the removed implicit mode default."""
    import ast

    path = (Path(__file__).resolve().parents[1] /
            "integrations/mythicsim-rust/verify_upstream_candidate.py")
    tree = ast.parse(path.read_text())
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "probe"
    ]
    assert calls
    assert all(any(keyword.arg == "rng_mode" for keyword in node.keywords)
               for node in calls)

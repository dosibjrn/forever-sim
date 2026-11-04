"""Feral P7.1 source selection/native dispatch regression, NOT a real gate PASS."""
import hashlib
from pathlib import Path

import pytest

from tools import wf_gate_p7_1_live as gate

ROOT = Path(__file__).resolve().parents[1]
SAVED = Path("docs/evidence/druid-l60-feral/p7.1/saved_811_request.json")


def _copy_authentic_source(root: Path) -> Path:
    request = root / SAVED
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_bytes((ROOT / SAVED).read_bytes())
    return request


def test_feral_reference_is_original_pinned_811_request(tmp_path, monkeypatch):
    request = _copy_authentic_source(tmp_path)
    assert hashlib.sha256(request.read_bytes()).hexdigest() == gate.SAVED_FERAL_RAW_SHA
    assert gate.FERAL_REFERENCE_DPS == pytest.approx(811.0237260012982)
    monkeypatch.delenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", raising=False)
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(tmp_path / "missing-engine"))
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    # The source and original scenario were selected successfully; no real
    # executable is present and no synthetic source score can grant a PASS.
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]
    assert gate.run_live(tmp_path, "druid", 60, spec="unrestricted")["status"] == "BLOCKED"


def test_feral_source_mutation_fails_before_native(tmp_path):
    request = _copy_authentic_source(tmp_path)
    request.write_bytes(request.read_bytes() + b" ")
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_1_SAVED_REQUEST_CHANGED"]


@pytest.mark.parametrize(
    ("dps_factor", "expected_status", "expected_reason"),
    [(1.0, "PASS", []),
     (0.98, "FAIL", ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"])],
)
def test_feral_native_stochastic_forwarding_and_99_percent_floor(
        tmp_path, monkeypatch, dps_factor, expected_status, expected_reason):
    """Stub only the native transport, not Warcraft mechanics or M1 evidence."""
    request = _copy_authentic_source(tmp_path)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("transport-only test path")
    selected = "1f170913f0af47f0de455c2b91581d777e713d3a"
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.delenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", raising=False)
    monkeypatch.setattr(gate, "_selected_rust_submodule", lambda *args: selected)
    provider = tmp_path / "integrations/mythicsim-rust/live_world_probe.py"
    provider.parent.mkdir(parents=True)
    score = gate.FERAL_REFERENCE_DPS * dps_factor
    provider.write_text(
        "def native_source_control(binary, request, iterations, *, rng_mode):\n"
        "    assert rng_mode == 'stochastic'\n"
        "    assert request.name == 'saved_811_request.json'\n"
        "    assert iterations == 1000\n"
        f"    return {{'native_dps': {score!r}, 'iterations': iterations}}\n"
        "def run(*args, **kwargs):\n"
        "    raise AssertionError('P7.1 must remain native-only')\n"
    )
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    assert result["status"] == expected_status  # Mocked transport; no gate credit.
    assert result["reasons"] == expected_reason
    assert result["native_dps"] == pytest.approx(score)
    assert result["saved_reference_dps"] == pytest.approx(gate.FERAL_REFERENCE_DPS)
    assert result["source_request_raw_sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    assert result["source_report_url"] == gate.FERAL_REPORT_URL
    assert result["reference_profile"] == result["checkpoint_spec"] == "feral"
    assert result["native_source_revision"] == selected
    assert result["iterations"] == result["sampled_source_fights"] == 1000


def test_feral_bounded_sample_is_never_full_acceptance(tmp_path, monkeypatch):
    _copy_authentic_source(tmp_path)
    monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", "3")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(tmp_path / "missing-engine"))
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_p71_cli_exposes_actual_native_dps_and_frozen_comparator(monkeypatch, capsys):
    """CLI receipt forwarding only; no synthetic gate PASS or M1 write."""
    import json
    from tools import wf_gate as cli

    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"],
        "native_dps": 792.3,
        "saved_reference_dps": gate.FERAL_REFERENCE_DPS,
        "required_dps": gate.FERAL_REFERENCE_DPS * 0.99,
        "reference_profile": "feral",
        "selected_validation": "1000_native_stochastic_fights",
        "iterations": 1000,
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "feral", "--gate", "P7.1"]) == 1
    receipt = json.loads(capsys.readouterr().out)["results"][0]
    assert receipt["status"] == "FAIL"
    assert receipt["native_dps"] == 792.3
    assert receipt["saved_reference_dps"] == gate.FERAL_REFERENCE_DPS
    assert receipt["required_dps"] == pytest.approx(gate.FERAL_REFERENCE_DPS * 0.99)
    assert receipt["reference_profile"] == "feral"
    assert receipt["selected_validation"] == "1000_native_stochastic_fights"


def test_native_execution_failure_keeps_actionable_error(monkeypatch, capsys):
    import json
    from tools import wf_gate as cli
    error = "RuntimeError:NATIVE_SOURCE_CONTROL_FAILED exit=1 request_sha256=abc output=source rejected"
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_1_NATIVE_STOCHASTIC_EXECUTION_FAILED"],
        "native_execution_error": error,
        "native_source_revision": "tested-native-pin",
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "feral", "--gate", "P7.1"]) == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["native_execution_error"] == error
    assert row["native_source_revision"] == "tested-native-pin"


def test_native_adapter_preserves_structured_rust_refusal(monkeypatch, tmp_path):
    """Test Forever transport only; do not second-guess Rust talent legality."""
    import importlib.util
    import json
    from types import SimpleNamespace

    path = ROOT / "integrations/mythicsim-rust/live_world_probe.py"
    spec = importlib.util.spec_from_file_location("work2_native_refusal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    request = _copy_authentic_source(tmp_path)
    reason = 'druid talents "050022-55000032021032212051-053": Predatory Discipline has 1 rank, the string gives 3'
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=5, stdout=json.dumps({"prepared": False,
                                           "refusal": {"code": "talents", "reason": reason}}),
        stderr=""))
    with pytest.raises(module.NativeSourceRefusal) as failure:
        module.native_source_control(tmp_path / "forever-engine", request,
                                     1000, rng_mode="stochastic")
    assert failure.value.code == "talents"
    assert failure.value.reason == reason
    assert failure.value.exit_code == 5
    assert len(failure.value.request_sha256) == 64


def test_feral_rejected_native_source_is_not_a_stochastic_dps_failure(tmp_path, monkeypatch):
    _copy_authentic_source(tmp_path)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("transport-only test path")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setattr(gate, "_selected_rust_submodule", lambda *args: "native-pin")
    provider = tmp_path / "integrations/mythicsim-rust/live_world_probe.py"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        "class NativeSourceRefusal(RuntimeError):\n"
        "    def __init__(self):\n"
        "        self.code = 'talents'\n"
        "        self.reason = 'Predatory Discipline has 1 rank, the string gives 3'\n"
        "def native_source_control(*args, **kwargs):\n"
        "    raise NativeSourceRefusal()\n"
    )
    result = gate.run_live(tmp_path, "druid", 60, spec="feral")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_1_NATIVE_SOURCE_REFUSED"]
    assert result["native_refusal_code"] == "talents"
    assert "Predatory Discipline" in result["native_refusal_reason"]
    assert "native_dps" not in result


def test_cli_keeps_native_refusal_code_and_full_reason(monkeypatch, capsys):
    import json
    from tools import wf_gate as cli

    reason = 'druid talents "050022-55000032021032212051-053": ' + 'Predatory Discipline rank refusal; ' * 20
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "BLOCKED",
        "reasons": ["P7_1_NATIVE_SOURCE_REFUSED"],
        "native_refusal_code": "talents",
        "native_refusal_reason": reason,
    })
    assert cli.main(["--class", "druid", "--level", "60",
                     "--spec", "feral", "--gate", "P7.1"]) != 0
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["status"] == "BLOCKED"
    assert row["native_refusal_code"] == "talents"
    assert row["native_refusal_reason"] == reason

"""Fast fail-closed tests for the direct P7.1 production entry.

No fake Rust binary, mock 2D combat, or substitute P7.1 PASS. The final
1000-stochastic-fight native/world acceptance is deliberately on-demand.
"""
import hashlib
import json

from tools import wf_gate_p7_1_live as gate


def _fixture(root):
    request = root / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    witness.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({
        "raid": {"parties": [{"players": [{"class": "ClassDruid",
                                         "balanceDruid": {},
                                         "distanceFromTarget": 15}]}]},
        "encounter": {"targets": [{"level": 63}]},
        "simOptions": {"iterations": 10000},
    }))
    witness.write_text(json.dumps({"engine_revision": gate.PINNED_RUST,
                                   "iterations": 10000,
                                   "reference_dps": 728.1936126415858}))
    return request


def test_selected_fork_requires_parent_gitlink_not_historical_engine(
        tmp_path, monkeypatch):
    """The saved WF633 engine is provenance, while the executable is the gitlink."""
    import subprocess
    selected = "1f170913f0af47f0de455c2b91581d777e713d3a"
    actual = [selected]
    mode = ["valid"]

    def fake_git(args, **kwargs):
        if "ls-tree" in args:
            row = ("160000 commit " + selected
                   + "\tintegrations/mythicsim-rust/engine\n")
            if mode[0] == "not_gitlink":
                row = "100644 blob " + selected + "\tintegrations/mythicsim-rust/engine\n"
            return subprocess.CompletedProcess(args, 0, row, "")
        assert "rev-parse" in args
        return subprocess.CompletedProcess(args, 0, actual[0] + "\n", "")

    monkeypatch.setattr(gate.subprocess, "run", fake_git)
    assert gate._selected_rust_submodule(tmp_path, tmp_path / "upstream") == selected
    assert selected != gate.PINNED_RUST
    actual[0] = gate.PINNED_RUST
    assert gate._selected_rust_submodule(tmp_path, tmp_path / "upstream") is None
    actual[0] = selected
    mode[0] = "not_gitlink"
    assert gate._selected_rust_submodule(tmp_path, tmp_path / "upstream") is None


def test_shared_p74_preflight_accepts_exact_fork_without_overwriting_saved_witness(
        tmp_path, monkeypatch):
    from tools import wf_gate_p7_2_live as discovery
    request = _fixture(tmp_path)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("unit test path only")
    bridge = tmp_path / "upstream/src/core/fight/world_bridge.rs"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("// unit test bridge marker")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setattr(discovery, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    selected = "1f170913f0af47f0de455c2b91581d777e713d3a"
    monkeypatch.setattr(discovery, "_selected_rust_submodule",
                        lambda *args: selected)
    prepared = discovery._pinned_source_runtime(
        tmp_path, "druid", 60, "balance", "P7.4")
    assert isinstance(prepared, tuple)
    _, meta, selected_binary = prepared
    assert selected_binary == binary
    assert meta["engine_revision"] == gate.PINNED_RUST
    assert meta["selected_engine_revision"] == selected


def test_unrelated_checkpoint_cannot_use_balance_reference(tmp_path):
    report = gate.run_live(tmp_path, "hunter", 20, spec="beast-mastery")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_changed_source_request_blocks_before_binary(tmp_path):
    _fixture(tmp_path)
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_SAVED_REQUEST_CHANGED"]


def test_no_native_binary_never_awards_pass(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_source_original_iteration_count_is_provenance_not_10000_requirement(
        tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    payload = json.loads(request.read_text())
    payload["simOptions"]["iterations"] = 7  # historical sample count is metadata only
    request.write_text(json.dumps(payload))
    witness = tmp_path / "docs/evidence/wf633/WF633_VALIDATION.json"
    meta = json.loads(witness.read_text())
    meta["iterations"] = 10000  # historical witness count is not a gate limit
    witness.write_text(json.dumps(meta))
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    # We reach the real pinned-native preflight: no spurious 10k check, and
    # a missing production binary cannot award a PASS.
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_invalid_bounded_probe_cannot_start_native(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    for value in ("0", "1001", "10001", "not-an-integer"):
        monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", value)
        report = gate.run_live(tmp_path, "druid", 60, spec="balance")
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == ["P7_1_INVALID_LIVE_PROBE_ITERATIONS"]


def test_bounded_probe_still_requires_real_pinned_native(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", "3")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_cli_separates_sample_breadth_from_live_dps_proximity(monkeypatch, capsys):
    # Presentation regression only; exact-source Actions prove real Rust/gsim.
    from tools import wf_gate as cli
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_1_BOUNDED_DIAGNOSTIC_NOT_FULL_SAVED_REFERENCE"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "source_request_raw_sha256": "reproducible-source-request-hash",
        "native_source_revision": gate.PINNED_RUST,
        "source_report_url": "https://api.mythicsim.com/report",
        "world_damage_events": 430, "world_boundaries": 792,
        "world_dps": 692.1030471575785,
        "saved_reference_dps": 728.1936126415858,
        "behavior_probes_executed": 3,
        "sampled_source_fights": 3, "saved_source_iterations": 10000,
    })
    assert cli.main(["--class", "druid", "--level", "60", "--spec", "balance",
                     "--gate", "P7.1"]) == 1
    report = json.loads(capsys.readouterr().out)
    row = report["results"][0]
    assert report["status"] == row["status"] == "FAIL"
    for key in ("verified", "applicable", "pass_count", "reachability_count",
                "partial_coverage_percent", "pareto_effort_estimate_percent"):
        assert key not in row
    assert row["sampled_source_fights"] == 3
    assert row["saved_source_iterations"] == 10000
    # 3 sampled fights are not the required 1,000 stochastic final.
    # Production correctly withholds an acceptance-comparable DPS ratio.
    for key in ("dps_objective_required", "dps_objective_proximity_percent",
                "dps_objective_gate_pass"):
        assert key not in row


def test_source_fight_sample_cannot_earn_m1_partial():
    from tools.wf_gate_coverage import measured_live_coverage
    sample = {"status": "FAIL", "pass_count": 3,
              "reachability_count": 10000,
              "behavior_probes_executed": 3}
    assert measured_live_coverage(sample) is None


def test_equal_mean_dps_cannot_hide_wrong_source_encounter_duration():
    # Negative control for the real P7.1 native-vs-ACK-world comparison.
    # These small metric dicts test the assertion, NOT a substitute engine.
    native = {"iterations": 3, "native_dps": 692.1030471575785,
              "first_duration_s": 133.0027}
    live = {"iterations_done": 3, "native_dps": 692.1030471575785,
            "world_mean_dps": 692.1030471575785,
            "sampled_duration_s": 133.0027,
            "native_damage_events": 430, "native_world_ticks": 792,
            "per_iteration": [{"iteration_index": i, "duration_s": 133.0027,
                               "world_dps": 692.1030471575785,
                               "world_applied_damage": 692.1030471575785 * 133.0027} for i in range(3)]}
    assert gate._source_native_world_parity(native, live, 3) is None
    live["sampled_duration_s"] = 132.0027
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED")
    live["sampled_duration_s"] = 133.0027
    live["per_iteration"][0] = {
        **live["per_iteration"][0], "duration_s": 132.0027}
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED")
    live["per_iteration"][0] = {
        **live["per_iteration"][0], "duration_s": 133.0027}
    live["native_world_ticks"] = 0
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_EXECUTION_INCOMPLETE")


def test_dps_floor_failure_is_not_mislabeled_as_native_world_parity():
    from tools.wf_gate_coverage import p7_final_stochastic_mean_passes
    assert not p7_final_stochastic_mean_passes(
        "P7.1", 700.0, 728.1936126415858,
        iterations=1000, stochastic=True)
    assert gate._source_native_world_parity(
        {"iterations": 1000, "native_dps": 700.0,
         "first_duration_s": 120.0},
        {"iterations_done": 1000, "native_dps": 700.0,
         "world_mean_dps": 700.0, "sampled_duration_s": 120.0,
         "native_damage_events": 1, "native_world_ticks": 1000,
         "per_iteration": [{"iteration_index": i, "duration_s": 120.0,
                            "world_dps": 700.0,
                            "world_applied_damage": 700.0 * 120.0}
                           for i in range(1000)]},
        1000) is None


def test_m1_action_prepares_exact_source_native_p7_without_heavy_opt_in():
    """The Actions wrapper must make the REAL P7 producer runnable.

    A three-fight source-backed diagnostic is not 3/1000 gate completion.
    Full stochastic acceptance remains explicit, and P6/P7.2+ stay heavy.
    """
    from tools.wf_gate import ROOT
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text()
    assert 'git submodule update --init --depth 1' in workflow
    assert 'git ls-tree HEAD -- "$engine"' in workflow
    assert 'RUST_FORK_SUBMODULE_PIN_MISMATCH' in workflow
    assert "patch_world_ingress.py upstream" not in workflow
    assert "cargo build --release --locked" in workflow
    assert "FOREVER_MYTHICSIM_RUST_BIN:" in workflow
    assert "FOREVER_P7_LIVE_PROBE_ITERATIONS=3" in workflow
    assert '"$gate" != P7.1' in workflow
    assert '"$entry" == *:P7.*' in workflow  # future P7.2-.5 use same native binary
    assert '"$gate" == P6' in workflow
    assert '"$gate" == P7.*' in workflow


def test_equal_aggregate_dps_cannot_hide_missing_or_reordered_world_fights():
    """Acceptance RED on prior main: equal means concealed wrong fight ledger."""
    native = {"iterations": 3, "native_dps": 700.0,
              "first_duration_s": 120.0}
    live = {"iterations_done": 3, "native_dps": 700.0,
            "world_mean_dps": 700.0, "sampled_duration_s": 120.0,
            "native_damage_events": 6, "native_world_ticks": 9,
            "source_request_raw_sha256": "source-sha",
            "per_iteration": [
                {"iteration_index": i, "duration_s": 120.0,
                 "world_dps": 700.0, "world_applied_damage": 700.0 * 120.0}
                for i in range(3)]}
    check = lambda: gate._source_native_world_parity(
        native, live, 3, expected_raw_sha="source-sha")
    assert check() is None
    live["per_iteration"][1]["iteration_index"] = 0
    assert check() == "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"
    live["per_iteration"][1]["iteration_index"] = 1
    live["per_iteration"][1]["world_dps"] = 701.0
    assert check() == "P7_1_WORLD_FIGHT_MEAN_DIVERGED"
    live["per_iteration"][1]["world_dps"] = 700.0
    live["source_request_raw_sha256"] = "different-source"
    assert check() == "P7_1_LIVE_SOURCE_REQUEST_IDENTITY_DIVERGED"
    live["source_request_raw_sha256"] = "source-sha"
    del live["per_iteration"][2]["world_applied_damage"]
    assert check() == "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"


def test_equal_reported_dps_cannot_hide_unapplied_or_prepull_world_damage():
    """Reject a forged ACK ledger even when mean native/world DPS agrees.

    The real producer scores (applied damage minus precombat damage)
    divided by duration. This is a production acceptance assertion test,
    not a substitute Rust/2D fight or a certified P7 result.
    """
    native = {"iterations": 2, "native_dps": 700.0,
              "first_duration_s": 120.0}
    live = {"iterations_done": 2, "native_dps": 700.0,
            "world_mean_dps": 700.0, "sampled_duration_s": 120.0,
            "native_damage_events": 10, "native_world_ticks": 20,
            "per_iteration": [
                {"iteration_index": 0, "duration_s": 120.0,
                 "world_dps": 700.0, "world_applied_damage": 84025.0,
                 "world_applied_precombat_damage": 25.0},
                {"iteration_index": 1, "duration_s": 120.0,
                 "world_dps": 700.0, "world_applied_damage": 84000.0,
                 "world_applied_precombat_damage": 0.0},
            ]}
    check = lambda: gate._source_native_world_parity(native, live, 2)
    assert check() is None
    live["per_iteration"][1]["world_applied_damage"] = 0.0
    assert check() == "P7_1_WORLD_FIGHT_DAMAGE_DIVERGED"
    live["per_iteration"][1]["world_applied_damage"] = 84000.0
    live["per_iteration"][0]["world_applied_precombat_damage"] = 24.0
    assert check() == "P7_1_WORLD_FIGHT_DAMAGE_DIVERGED"
    live["per_iteration"][0]["world_applied_precombat_damage"] = -1.0
    assert check() == "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"


def test_p7_native_world_parity_rejects_nonfinite_or_malformed_aggregate_scores():
    """RED on old production code: NaN skips every >= tolerance comparison.

    Exercises the shared real-producer acceptance assertion, not a simulated
    combat engine or a P7 PASS. Applies to all P7.1–P7.5 provider calls.
    """
    import copy

    native = {"iterations": 2, "native_dps": 90.0,
              "first_duration_s": 120.0}
    world = {"iterations_done": 2, "native_dps": 90.0,
             "world_mean_dps": 90.0, "sampled_duration_s": 120.0,
             "native_damage_events": 2, "native_world_ticks": 2,
             "per_iteration": [
                 {"iteration_index": i, "duration_s": 120.0,
                  "world_dps": 90.0, "world_applied_damage": 10800.0}
                 for i in range(2)]}
    assert gate._source_native_world_parity(native, world, 2) is None
    for invalid in (float("nan"), float("inf"), -float("inf"), "90", True):
        for side, field in (("native", "native_dps"),
                            ("world", "native_dps"),
                            ("world", "world_mean_dps")):
            changed_native, changed_world = copy.deepcopy(native), copy.deepcopy(world)
            (changed_native if side == "native" else changed_world)[field] = invalid
            assert gate._source_native_world_parity(
                changed_native, changed_world, 2) == "P7_1_NATIVE_WORLD_DPS_INVALID"


def test_p7_native_world_parity_rejects_nonfinite_first_fight_duration():
    import copy

    native = {"iterations": 2, "native_dps": 90.0,
              "first_duration_s": 120.0}
    world = {"iterations_done": 2, "native_dps": 90.0,
             "world_mean_dps": 90.0, "sampled_duration_s": 120.0,
             "native_damage_events": 2, "native_world_ticks": 2,
             "per_iteration": [
                 {"iteration_index": i, "duration_s": 120.0,
                  "world_dps": 90.0, "world_applied_damage": 10800.0}
                 for i in range(2)]}
    assert gate._source_native_world_parity(native, world, 2) is None
    for field, side in (("first_duration_s", "native"),
                        ("sampled_duration_s", "world")):
        for invalid in (float("nan"), float("inf"), -float("inf"), "120", True):
            n, w = copy.deepcopy(native), copy.deepcopy(world)
            (n if side == "native" else w)[field] = invalid
            assert gate._source_native_world_parity(n, w, 2) == (
                "P7_1_NATIVE_WORLD_DURATION_INVALID")


def _native_p71_mock(tmp_path, monkeypatch, *, dps=730.0, fights=None):
    """Stub only the native transport; never claim a mock as M1 evidence."""
    request = _fixture(tmp_path)
    source = json.loads(request.read_text())
    source["simOptions"]["iterations"] = 7
    request.write_text(json.dumps(source))
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("unit-test stub")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    selected = "1f170913f0af47f0de455c2b91581d777e713d3a"
    monkeypatch.setattr(gate, "_selected_rust_submodule",
                        lambda root, upstream: selected)
    provider = tmp_path / "integrations/mythicsim-rust/live_world_probe.py"
    provider.parent.mkdir(parents=True, exist_ok=True)
    provider.write_text(
        "def native_source_control(binary, request, iterations, *, rng_mode):\n"
        "    assert rng_mode == 'stochastic'\n"
        "    return {'iterations': " + (
            "iterations" if fights is None else str(fights)) +
        ", 'native_dps': " + repr(dps) + "}\n"
        "def run(*args, **kwargs):\n"
        "    raise AssertionError('P7.1 must not execute 2D world')\n"
        "def run_range_perturbation_pair(*args, **kwargs):\n"
        "    raise AssertionError('P7.1 must not require range perturbation')\n")
    return request, selected


def test_full_1000_stochastic_native_result_without_retired_world_requirement(
        monkeypatch, tmp_path):
    """Checks native forwarding, immutable reference and unrestricted labeling."""
    request, selected = _native_p71_mock(tmp_path, monkeypatch)
    from tools.wf_gate import _run_live_gate
    for spec in ("balance", "unrestricted"):
        result = _run_live_gate(tmp_path, "druid", 60, spec, "P7.1", "")
        assert result["status"] == "PASS"  # mocked transport, not actual M1
        assert result["reasons"] == []
        assert result["p7_1_1_reference_pinned"] is True
        assert result["p7_1_2_native_reproduced"] is True
        assert "p7_1_3_live_reproduced" not in result
        assert "world_range_perturbation" not in result
        assert result["production_engine"] == "pinned_mythicsim_rust_native"
        assert result["reference_profile"] == "balance"
        assert result["checkpoint_spec"] == spec
        assert result["iterations"] == 1000
        assert result["saved_source_iterations"] == 7
        assert result["runtime_proof"]["executed"] is True
        assert result["runtime_proof"]["source_revision"] == (
            hashlib.sha256(request.read_bytes()).hexdigest())
        assert result["runtime_proof"]["engine_revision"] == selected


def test_p71_bounded_sample_and_invalid_native_receipt_never_pass(
        monkeypatch, tmp_path):
    _native_p71_mock(tmp_path, monkeypatch)
    monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", "3")
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "FAIL"
    assert report["reasons"] == [
        "P7_1_BOUNDED_DIAGNOSTIC_NOT_FULL_SAVED_REFERENCE"]
    assert report["sampled_source_fights"] == 3

    monkeypatch.delenv("FOREVER_P7_LIVE_PROBE_ITERATIONS")
    _native_p71_mock(tmp_path, monkeypatch, fights=999)
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "FAIL"
    assert report["reasons"] == ["P7_1_NATIVE_STOCHASTIC_RESULT_INVALID"]


def test_p71_genuine_native_score_below_floor_cannot_pass(
        monkeypatch, tmp_path):
    _native_p71_mock(tmp_path, monkeypatch, dps=700.0)
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "FAIL"
    assert report["reasons"] == ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"]

"""Production P7.5 must compare against accepted *compatible* prior finals."""
import csv
import json

import pytest

from tools.wf_gate_p7_5_prior import strongest_accepted_prior


FIELDS = ("class", "level", "spec", "gate", "passed_at_utc", "commit",
          "run_url", "compatibility_id", "status", "verified", "applicable",
          "scope_provisional", "measured_at_utc")
SOURCE = "saved-raw-source-sha"
ENGINE = "selected-real-rust"
REFERENCE = 728.19


def _report(gate, dps, *, engine=ENGINE, source=SOURCE, reference=REFERENCE):
    report = {
        "status": "PASS", "reasons": [],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "native_source_revision": engine,
        "source_request_raw_sha256": source,
        "saved_reference_dps": reference,
        "runtime_proof": {"executed": True, "engine_revision": engine},
        "world_damage_events": 10, "world_boundaries": 20,
    }
    if gate == "P7.1":
        report.update(iterations=1000, stochastic_rng=True,
                      selected_validation="1000_native_and_live_stochastic_fights",
                      native_dps=dps, world_dps=dps)
    else:
        report.update(frozen_request_raw_sha256="frozen-" + gate,
                      frozen_stochastic_iterations=1000,
                      frozen_stochastic_native_dps=dps,
                      frozen_stochastic_world_dps=dps,
                      frozen_stochastic_world_damage_events=10,
                      frozen_stochastic_world_boundaries=20)
    return report


def _fixtures(tmp_path, monkeypatch, *, statuses=None):
    statuses = statuses or {"P7.1": "PASS", "P7.2": "PASS",
                            "P7.3": "PARTIAL", "P7.4": "PASS"}
    ledger = tmp_path / "docs/planning/M1_PASSES.tsv"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader()
        for gate, status in statuses.items():
            writer.writerow({"class": "druid", "level": "60",
                             "spec": "balance", "gate": gate,
                             "status": status,
                             "run_url": "https://github.com/example/actions/runs/" + gate,
                             "passed_at_utc": "2026-11-03T00:00:00Z"
                             if status == "PASS" else ""})
    receipts = [
        {"gate": gate,
         "run_url": "https://github.com/example/actions/runs/" + gate,
         "report": _report(gate, dps)}
        for gate, dps in (("P7.1", 728.0), ("P7.2", 731.0),
                          ("P7.4", 725.32))
    ]
    path = tmp_path / "accepted-priors.json"
    path.write_text(json.dumps({"receipts": receipts}))
    monkeypatch.setenv("FOREVER_P7_ACCEPTED_PRIOR_RECEIPTS", str(path))
    return receipts, path


def _read(tmp_path):
    return strongest_accepted_prior(
        tmp_path, "druid", 60, "balance", engine_revision=ENGINE,
        source_sha256=SOURCE, reference_dps=REFERENCE)


def test_uses_strongest_accepted_stochastic_final_not_only_reference(tmp_path, monkeypatch):
    _fixtures(tmp_path, monkeypatch)
    result = _read(tmp_path)
    assert result["dps"] == 731.0
    assert result["compatible_gates"] == ["P7.1", "P7.2", "P7.4"]


def test_unaccepted_partial_or_missing_prior_cannot_be_used(tmp_path, monkeypatch):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    path.write_text(json.dumps({"receipts": receipts[:-1]}))
    assert _read(tmp_path) is None
    receipts[-1]["report"]["status"] = "FAIL"
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None
    statuses = {"P7.3": "PARTIAL"}
    _fixtures(tmp_path, monkeypatch, statuses=statuses)
    assert _read(tmp_path) is None


@pytest.mark.parametrize("tamper", ["run_url", "source", "reference", "iterations",
                                     "runtime", "world", "engine"])
def test_rejects_unverifiable_prior_receipt(tmp_path, monkeypatch, tamper):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    record = receipts[1]
    report = record["report"]
    if tamper == "run_url":
        record["run_url"] = "https://github.com/example/actions/runs/WRONG"
    elif tamper == "source":
        report["source_request_raw_sha256"] = "different-raw-source"
    elif tamper == "reference":
        report["saved_reference_dps"] = 800.0
    elif tamper == "iterations":
        report["frozen_stochastic_iterations"] = 24
    elif tamper == "runtime":
        report["runtime_proof"]["executed"] = False
    elif tamper == "world":
        report["frozen_stochastic_world_damage_events"] = 0
    else:
        report["native_source_revision"] = "other-native-revision"
        report["runtime_proof"]["engine_revision"] = "other-native-revision"
        # Incompatible accepted receipts are excluded, never used in comparison.
        path.write_text(json.dumps({"receipts": receipts}))
        assert _read(tmp_path)["dps"] == 728.0
        return
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None


def test_without_accepted_receipt_file_stays_blocked(tmp_path, monkeypatch):
    _fixtures(tmp_path, monkeypatch)
    monkeypatch.delenv("FOREVER_P7_ACCEPTED_PRIOR_RECEIPTS")
    assert _read(tmp_path) is None

def test_real_m1_projection_from_accepted_1000_fight_runs_is_usable(tmp_path, monkeypatch):
    """M1 stdout is compact, not the full provider report; still real PASS."""
    receipts, path = _fixtures(tmp_path, monkeypatch)
    for receipt in receipts:
        gate = receipt["gate"]
        r = receipt["report"]
        value = r["world_dps"] if gate == "P7.1" else r["frozen_stochastic_world_dps"]
        r.pop("saved_reference_dps")
        r["runtime_proof"]["engine_revision"] = ENGINE
        r["dps_objective_scope"] = "COUPLED_LIVE_REFERENCE_DPS_ONLY"
        r["dps_objective_provisional"] = True
        r["dps_objective_gate_pass"] = False
        r["dps_objective_actual"] = value
        r["dps_objective_required"] = round(0.99 * REFERENCE, 4)
        if gate == "P7.1":
            r["sampled_source_fights"] = 1000
            r.pop("native_dps")
            r.pop("world_dps")
            r.pop("stochastic_rng")
            r.pop("selected_validation")
        else:
            for field in ("frozen_stochastic_iterations",
                          "frozen_stochastic_native_dps",
                          "frozen_stochastic_world_dps",
                          "frozen_stochastic_world_damage_events",
                          "frozen_stochastic_world_boundaries",
                          "frozen_request_raw_sha256"):
                r.pop(field)
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path)["dps"] == 731.0


@pytest.mark.parametrize("field,bad_value", [
    ("dps_objective_scope", "BALANCED_SCREEN_ONLY"),
    ("dps_objective_provisional", False),
    ("dps_objective_gate_pass", True),
    ("dps_objective_required", 700.0),
    ("dps_objective_actual", 0.0),
])
def test_m1_projection_rejects_fake_or_unverified_score(
        tmp_path, monkeypatch, field, bad_value):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    r = receipts[1]["report"]
    r.pop("saved_reference_dps")
    r["runtime_proof"]["engine_revision"] = ENGINE
    r.update(dps_objective_scope="COUPLED_LIVE_REFERENCE_DPS_ONLY",
             dps_objective_provisional=True, dps_objective_gate_pass=False,
             dps_objective_actual=731.0,
             dps_objective_required=round(0.99 * REFERENCE, 4))
    r[field] = bad_value
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None


def test_m1_projection_rejects_bounded_p71_and_mismatched_engine(
        tmp_path, monkeypatch):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    for receipt in receipts:
        receipt["report"]["runtime_proof"]["engine_revision"] = ENGINE
    r = receipts[0]["report"]
    r.pop("saved_reference_dps")
    r.update(dps_objective_scope="COUPLED_LIVE_REFERENCE_DPS_ONLY",
             dps_objective_provisional=True, dps_objective_gate_pass=False,
             dps_objective_actual=729.0,
             dps_objective_required=round(0.99 * REFERENCE, 4),
             sampled_source_fights=3, iterations=3)
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None
    r["sampled_source_fights"] = 1000
    r["iterations"] = 1000
    receipts[1]["report"]["runtime_proof"]["engine_revision"] = "wrong-fork"
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None


def _native_p71_receipt(dps=765.0):
    """Genuine-shape P7.1 result from the selected native stationary scorer."""
    report = _report("P7.1", dps)
    report["production_engine"] = "pinned_mythicsim_rust_native"
    report["selected_validation"] = "1000_native_stochastic_fights"
    report["sampled_source_fights"] = 1000
    report.pop("world_dps")
    report.pop("world_damage_events")
    report.pop("world_boundaries")
    return report


def test_native_only_accepted_p71_is_an_eligible_stochastic_prior(tmp_path, monkeypatch):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    receipts[0]["report"] = _native_p71_receipt(765.0)
    path.write_text(json.dumps({"receipts": receipts}))
    result = _read(tmp_path)
    assert result["dps"] == 765.0
    assert result["compatible_gates"] == ["P7.1", "P7.2", "P7.4"]
    assert "https://github.com/example/actions/runs/P7.1" in result["run_urls"]


@pytest.mark.parametrize("field,value", [
    ("iterations", 3),
    ("sampled_source_fights", 3),
    ("stochastic_rng", False),
    ("selected_validation", "bounded_native_stochastic_diagnostic"),
    ("saved_reference_dps", 900.0),
    ("native_dps", 0.0),
    ("native_dps", float("nan")),
])
def test_native_p71_rejects_unverified_or_bounded_holdout(
        tmp_path, monkeypatch, field, value):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    report = _native_p71_receipt()
    report[field] = value
    receipts[0]["report"] = report
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None


def test_native_stochastic_receipt_cannot_certify_non_p71_axis(
        tmp_path, monkeypatch):
    receipts, path = _fixtures(tmp_path, monkeypatch)
    receipts[1]["report"] = _native_p71_receipt()
    path.write_text(json.dumps({"receipts": receipts}))
    assert _read(tmp_path) is None

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
        "runtime_proof": {"executed": True},
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

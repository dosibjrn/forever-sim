"""P7.5 accepted prior bundle comes from real registered M1 workflow logs."""
import csv
import json

import pytest

from tools.wf_gate_p7_5_receipts import (
    _parse_accepted_gate_line, _registered_run_id, collect_accepted_receipts,
)
from tools.wf_gate_p7_5_prior import strongest_accepted_prior


FIELDS = ("class", "level", "spec", "gate", "passed_at_utc", "commit",
          "run_url", "compatibility_id", "status", "verified", "applicable",
          "scope_provisional", "measured_at_utc")
REPO = "dosibjrn/forever-sim"
SOURCE = "source-original-request"
ENGINE = "selected-real-rust"
REFERENCE = 728.19


def _gate_result(gate, dps, engine=ENGINE):
    return {
        "gate": gate, "status": "PASS", "reasons": [],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "native_source_revision": engine,
        "source_request_raw_sha256": SOURCE,
        "runtime_proof": {"executed": True, "engine_revision": engine},
        "dps_objective_scope": "COUPLED_LIVE_REFERENCE_DPS_ONLY",
        "dps_objective_provisional": True,
        "dps_objective_gate_pass": False,
        "dps_objective_actual": dps,
        "dps_objective_required": round(0.99 * REFERENCE, 4),
        **({"iterations": 1000, "sampled_source_fights": 1000}
           if gate == "P7.1" else {"frozen_stochastic_iterations": 1000}),
    }


def _log(gate, dps, engine=ENGINE):
    report = {
        "class": "druid", "level": 60, "spec": "balance",
        "gate": gate, "status": "PASS",
        "results": [_gate_result(gate, dps, engine)],
    }
    # Original wf_gate print and the M1 workflow's reprint of --out JSON.
    result = "record\tRun real production gates\t2026-11-03T01:49:53Z " + json.dumps(report)
    return "unrelated shell setup\n" + result + "\n" + result + "\n"


def _ledger(tmp_path):
    ledger = tmp_path / "docs/planning/M1_PASSES.tsv"
    ledger.parent.mkdir(parents=True)
    with ledger.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        for gate, status, run_id in [
                ("P7.1", "PASS", 1001),
                ("P7.2", "PASS", 1002),
                ("P7.3", "PASS", 1003),
                ("P7.4", "PARTIAL", 1004)]:
            writer.writerow({
                "class": "druid", "level": 60, "spec": "balance",
                "gate": gate, "status": status,
                "run_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
                "passed_at_utc": "2026-11-03T01:49:53Z" if status == "PASS" else "",
            })


def test_collects_registered_m1_logs_and_existing_p75_validator(tmp_path, monkeypatch):
    _ledger(tmp_path)
    logs = {1001: _log("P7.1", 729.7, "older-rust"),
            1002: _log("P7.2", 722.4, "older-rust"),
            1003: _log("P7.3", 749.54, ENGINE)}
    called = []

    def reader(repo, run_id):
        called.append((repo, run_id))
        return logs[run_id]

    bundle = collect_accepted_receipts(
        tmp_path, REPO, "druid", 60, "balance", read_run=reader)
    assert called == [(REPO, 1001), (REPO, 1002), (REPO, 1003)]
    assert [r["gate"] for r in bundle["receipts"]] == ["P7.1", "P7.2", "P7.3"]
    filename = tmp_path / "accepted.json"
    filename.write_text(json.dumps(bundle))
    monkeypatch.setenv("FOREVER_P7_ACCEPTED_PRIOR_RECEIPTS", str(filename))
    accepted = strongest_accepted_prior(
        tmp_path, "druid", 60, "balance",
        engine_revision=ENGINE, source_sha256=SOURCE, reference_dps=REFERENCE)
    assert accepted["dps"] == 749.54
    assert accepted["compatible_gates"] == ["P7.3"]


def test_rejects_cross_repo_registered_url():
    with pytest.raises(ValueError, match="CANONICAL_ACTIONS"):
        _registered_run_id(
            "https://github.com/someone/other/actions/runs/1003", REPO)


def test_rejects_unrelated_or_failed_gate_json():
    with pytest.raises(ValueError, match="NOT_IN_RUN_LOG"):
        _parse_accepted_gate_line(
            _log("P7.2", 722.4), class_key="druid",
            level=60, spec="balance", gate="P7.3")
    invalid = _log("P7.3", 749.54).replace(
        '"status": "PASS"', '"status": "FAIL"')
    with pytest.raises(ValueError, match="NOT_IN_RUN_LOG"):
        _parse_accepted_gate_line(
            invalid, class_key="druid", level=60, spec="balance", gate="P7.3")


def test_rejects_contradictory_reports_in_one_run():
    log = _log("P7.3", 749.54) + _log("P7.3", 683.74)
    with pytest.raises(ValueError, match="CONFLICTING"):
        _parse_accepted_gate_line(
            log, class_key="druid", level=60,
            spec="balance", gate="P7.3")

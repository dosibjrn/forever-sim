"""Read accepted M1 P7 final receipts for the P7.5 comparator.

The M1 TSV is Merge-only. An optional local JSON bundle of real gate reports
provides stochastic means absent from its small PASS rows. An unverified or
incompatible receipt must never manufacture an accepted prior or a gate PASS.
"""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path

_PRIORS = ("P7.1", "P7.2", "P7.3", "P7.4")
_ENGINE = "pinned_mythicsim_rust_gsim_2d"


def _positive_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _accepted_final(gate: str, report: dict, reference_dps: float,
                    source_sha256: str) -> float | None:
    """Return a genuine 1k live final, or reject a partial/proxy receipt."""
    if (not isinstance(report, dict) or report.get("status") != "PASS"
            or report.get("reasons") != []
            or report.get("production_engine") != _ENGINE
            or report.get("source_request_raw_sha256") != source_sha256
            or not _positive_number(report.get("saved_reference_dps"))
            or not math.isclose(float(report["saved_reference_dps"]),
                                reference_dps, rel_tol=0, abs_tol=1e-6)
            or not isinstance(report.get("runtime_proof"), dict)
            or report["runtime_proof"].get("executed") is not True):
        return None
    if gate == "P7.1":
        if (type(report.get("iterations")) is not int
                or report["iterations"] != 1000
                or report.get("stochastic_rng") is not True
                or report.get("selected_validation")
                != "1000_native_and_live_stochastic_fights"):
            return None
        native, world = report.get("native_dps"), report.get("world_dps")
        effects = report.get("world_damage_events")
        ticks = report.get("world_boundaries")
    else:
        if (type(report.get("frozen_stochastic_iterations")) is not int
                or report["frozen_stochastic_iterations"] != 1000
                or not report.get("frozen_request_raw_sha256")):
            return None
        native = report.get("frozen_stochastic_native_dps")
        world = report.get("frozen_stochastic_world_dps")
        effects = report.get("frozen_stochastic_world_damage_events")
        ticks = report.get("frozen_stochastic_world_boundaries")
    if (not _positive_number(native) or not _positive_number(world)
            or type(effects) is not int or effects <= 0
            or type(ticks) is not int or ticks <= 0):
        return None
    return float(world)


def strongest_accepted_prior(root: Path, class_key: str, level: int,
                             spec: str, *, engine_revision: str,
                             source_sha256: str,
                             reference_dps: float) -> dict | None:
    """Resolve strongest independently accepted compatible prior, fail closed.

    Set FOREVER_P7_ACCEPTED_PRIOR_RECEIPTS to a local JSON object containing
    receipts, each with gate, run_url and report from the registered real run.
    Each registered P7.1-P7.4 PASS requires a matching receipt. A different
    selected native revision makes a valid receipt incompatible, so it cannot
    be used for the current P7.5 floor.
    """
    input_path = os.environ.get("FOREVER_P7_ACCEPTED_PRIOR_RECEIPTS")
    if not input_path:
        return None
    try:
        with (root / "docs/planning/M1_PASSES.tsv").open(newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        approved = {
            row["gate"]: row
            for row in rows
            if (row.get("class") == class_key
                and row.get("level") == str(level)
                and row.get("spec") == spec
                and row.get("gate") in _PRIORS
                and row.get("status") == "PASS"
                and row.get("passed_at_utc"))
        }
        if not approved:
            return None
        with Path(input_path).open() as f:
            parsed = json.load(f)
        receipts = parsed["receipts"]
        if not isinstance(receipts, list) or len(receipts) != len(approved):
            return None
        by_gate = {r["gate"]: r for r in receipts}
        if len(by_gate) != len(receipts) or set(by_gate) != set(approved):
            return None
        compatible = []
        for gate, row in approved.items():
            receipt = by_gate[gate]
            if not row.get("run_url") or receipt.get("run_url") != row["run_url"]:
                return None
            report = receipt.get("report")
            value = _accepted_final(gate, report, reference_dps, source_sha256)
            if value is None:
                return None
            if report.get("native_source_revision") != engine_revision:
                continue
            compatible.append((gate, value, row["run_url"]))
        if not compatible:
            return None
        return {"dps": max(x[1] for x in compatible),
                "compatible_gates": sorted(x[0] for x in compatible),
                "run_urls": [x[2] for x in compatible]}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

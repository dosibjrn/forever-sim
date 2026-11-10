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
_NATIVE_ENGINE = "pinned_mythicsim_rust_native"


def _positive_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _accepted_final(gate: str, report: dict, reference_dps: float,
                    source_sha256: str) -> float | None:
    """Return a genuine 1k live final, or reject a partial/proxy receipt."""
    if (not isinstance(report, dict) or report.get("status") != "PASS"
            or report.get("reasons") != []
            or report.get("production_engine") not in (_ENGINE, _NATIVE_ENGINE)
            or report.get("source_request_raw_sha256") != source_sha256
            or not isinstance(report.get("runtime_proof"), dict)
            or report["runtime_proof"].get("executed") is not True
            or report["runtime_proof"].get("engine_revision")
               != report.get("native_source_revision")):
        return None

    # P7.1 is now accepted by the pinned stationary native scorer, without
    # a 2D world witness. Its actual 1,000-fight stochastic arithmetic mean is
    # a valid P7.5 comparator when the accepted run URL, source, engine and
    # executed proof all match. Do not mistake the old live-world receipt
    # requirements for a P7 stationary acceptance condition.
    if report["production_engine"] == _NATIVE_ENGINE:
        if gate != "P7.1":
            return None
        if (not _positive_number(report.get("saved_reference_dps"))
                or not math.isclose(float(report["saved_reference_dps"]),
                                    reference_dps, rel_tol=0, abs_tol=1e-6)
                or type(report.get("iterations")) is not int
                or report["iterations"] != 1000
                or type(report.get("sampled_source_fights")) is not int
                or report["sampled_source_fights"] != 1000
                or report.get("stochastic_rng") is not True
                or report.get("selected_validation") != "1000_native_stochastic_fights"
                or not _positive_number(report.get("native_dps"))):
            return None
        mean = float(report["native_dps"])
        return mean if mean >= 0.99 * reference_dps else None

    # The production M1 CLI deliberately projects the full provider receipt
    # into a compact JSON result. Earlier accepted P7.1/P7.2 M1 runs retain
    # the real 1000-stochastic world mean as dps_objective_actual, but not
    # every provider-only field (saved_reference_dps, native/world raw means,
    # stochastic_rng). This number is emitted ONLY by
    # measured_p7_dps_proximity after verifying full 1000 stochastic fights,
    # live world events, the selected source and frozen candidate. Requiring
    # raw provider fields here incorrectly rejects genuine accepted M1 PASSes.
    # Do not accept arbitrary score-only reports: this projection is usable
    # only via the enclosing matching accepted M1 ledger/run-URL receipt.
    projected = (
        report.get("dps_objective_scope") == "COUPLED_LIVE_REFERENCE_DPS_ONLY"
        and report.get("dps_objective_provisional") is True
        and report.get("dps_objective_gate_pass") is False
        and _positive_number(report.get("dps_objective_actual"))
        and _positive_number(report.get("dps_objective_required"))
        and math.isclose(float(report["dps_objective_required"]),
                         round(0.99 * reference_dps, 4),
                         rel_tol=0, abs_tol=0.00011)
    )
    if projected:
        # The real P7.1 CLI includes its actual execution count; the other
        # gates' DPS proximity helper itself refuses non-1000 holdouts.
        if gate == "P7.1" and (
                report.get("iterations") != 1000
                or report.get("sampled_source_fights") != 1000):
            return None
        if (gate != "P7.1"
                and "frozen_stochastic_iterations" in report
                and report["frozen_stochastic_iterations"] != 1000):
            return None
        value = float(report["dps_objective_actual"])
        return value if value + 0.00011 >= float(report["dps_objective_required"]) else None

    if (not _positive_number(report.get("saved_reference_dps"))
            or not math.isclose(float(report["saved_reference_dps"]),
                                reference_dps, rel_tol=0, abs_tol=1e-6)):
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
            registered = row.get("run_url")
            observed = receipt.get("run_url")
            if not registered:
                return None
            # An accepted PASS has exactly one permanently registered origin;
            # newer proof must not replace it for the current comparison.
            if observed != registered:
                return None
            report = receipt.get("report")
            value = _accepted_final(gate, report, reference_dps, source_sha256)
            if value is None:
                return None
            if report.get("native_source_revision") != engine_revision:
                continue
            # Compare only the genuine original accepted receipt when its
            # source and native engine match this new, unaccepted P7.5 run.
            # A differing engine excludes a numeric prior, not its PASS.
            compatible.append((gate, value, observed))
        if not compatible:
            return None
        return {"dps": max(x[1] for x in compatible),
                "compatible_gates": sorted(x[0] for x in compatible),
                "run_urls": [x[2] for x in compatible]}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None

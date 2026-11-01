#!/usr/bin/env python3
"""Independently audit archived WF613 Feral Cat P7.5 stochastic evidence.

Read-only: never rewrites the original FAIL verdict or claims P1–P7
certification. PROCESS v2.10 compares the frozen *mean* against the full
external reference and 99% of the strongest compatible accepted prior.
Compatibility/acceptance of that prior and live gsim↔Go causality still need
separate review; this tool only validates the archived numeric evidence.

Usage: python tools/audit_feral_p7_holdout.py "WF613_COMPATIBILITY_REPAIR_P75_FAIL_2026-10-28(2).zip"
"""
import argparse
import hashlib
import json
import math
import statistics
import zipfile
from pathlib import Path

ARCHIVE_SHA256 = "a95e89f1bbd36d3cccb3c605fb9c8c90490bdd857112fc2c6bb83ceac1785e5f"
HOLDOUT_MEMBER = "WF612/WF613_P75_HOLDOUT_1000.json"
HOLDOUT_SHA256 = "0a69446c09a63e638d632586f5b14907a3241dbacc6f57b5b3a3ea3a3dff646e"
EXTERNAL_REFERENCE_DPS = 811.0237260012982
STRONGEST_RECORDED_PRIOR_P74_DPS = 853.9305465836047


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def audit_payload(payload):
    """Validate every paid sample; return numbers, not a gate certification."""
    if payload.get("workflow") != "WF613" or payload.get("gate") != "P7.5":
        raise ValueError("Wrong workflow/gate")
    if payload.get("mode") != "stochastic":
        raise ValueError("Not a stochastic holdout")
    if payload.get("status") != "FAIL":
        raise ValueError("Historical original verdict was FAIL; do not rewrite it")
    runs = payload.get("runs")
    if not isinstance(runs, list) or len(runs) != 1000:
        raise ValueError("Expected all 1,000 raw fights")
    if payload.get("observed_n") != 1000 or payload.get("target_n") != 1000:
        raise ValueError("Frozen holdout sample count mismatch")
    seeds = [r.get("seed") for r in runs]
    if seeds != list(range(92000001, 92001001)):
        raise ValueError("Precommitted seeds missing, duplicated or out of order")
    if payload.get("precommitted_seed_range") != [92000001, 92001000]:
        raise ValueError("Precommit seed range mismatch")
    dps = [r.get("dps") for r in runs]
    if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in dps):
        raise ValueError("Invalid per-fight DPS")
    mean = statistics.mean(dps)
    std = statistics.stdev(dps)
    if not math.isclose(mean, payload.get("mean_dps", float("nan")), rel_tol=0, abs_tol=1e-8):
        raise ValueError("Raw fights disagree with recorded mean")
    if not math.isclose(std, payload.get("std_dps", float("nan")), rel_tol=0, abs_tol=1e-8):
        raise ValueError("Raw fights disagree with recorded sample std")
    if not math.isclose(payload.get("prior_p74_dps", float("nan")), STRONGEST_RECORDED_PRIOR_P74_DPS, rel_tol=0, abs_tol=1e-8):
        raise ValueError("Strongest historical prior has changed")
    floor = max(EXTERNAL_REFERENCE_DPS, 0.99 * STRONGEST_RECORDED_PRIOR_P74_DPS)
    return {
        "historical_original_verdict": "FAIL",
        "historical_original_95pct_lower_bound_rule": "superseded by approved PROCESS v2.10",
        "raw_fights": len(runs),
        "first_seed": seeds[0], "last_seed": seeds[-1],
        "recomputed_mean_dps": mean, "recomputed_sample_std_dps": std,
        "external_reference_dps": EXTERNAL_REFERENCE_DPS,
        "strongest_recorded_prior_p74_dps": STRONGEST_RECORDED_PRIOR_P74_DPS,
        "provisional_numeric_floor_dps": floor,
        "process_v2_10_numeric_pass_if_prior_accepted_compatible": mean >= floor,
        "full_process_gate_certified": False,
        "remaining_review": "prior acceptance/compatibility; source legality; live gsim-2D↔Go causality; self-contained raw artifacts",
    }


def audit_lineage(holdout, search, trace, precommit, search_bytes, precommit_bytes, generator_bytes):
    """Verify original search -> frozen winner -> precommit -> holdout -> 2D ACK identity.

    This is an archival *identity* audit, not independent source legality,
    proof of the stronger P7.4 comparator's acceptance, or gate certification.
    """
    def require(condition, label):
        if not condition:
            raise ValueError("WF613 archive lineage mismatch: " + label)

    config = holdout.get("frozen_config")
    require(isinstance(config, dict), "missing frozen config")
    config_hash = sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode())
    require(config_hash == holdout.get("frozen_config_hash"), "frozen config hash")
    require(sha256(search_bytes) == holdout.get("search_sha256"), "search member hash")
    require(sha256(precommit_bytes) == holdout.get("precommit_sha256"), "precommit member hash")
    require(sha256(generator_bytes) == search.get("generator_sha256"), "search source hash")
    winner = search.get("winner", {})
    require(winner.get("config") == config, "search winner vs frozen config")
    require(winner.get("config_hash") == config_hash, "search winner hash")
    require(trace.get("candidate_config_hash") == config_hash, "causal trace candidate")
    for field in ("binary_sha256", "reference_sha256"):
        require(holdout.get(field) and holdout[field] == search.get(field) == trace.get(field),
                field + " across search/holdout/trace")
    require(holdout.get("database_sha256") == search.get("db_sha256"), "source database hash")
    require(precommit.get("independent_from_search") is True, "precommitted independent holdout")
    require((precommit.get("first_seed"), precommit.get("last_seed"), precommit.get("count"))
            == (92000001, 92001000, 1000), "precommitted seed range")
    require(precommit.get("comparison_gate") == "P7.4", "precommitted comparison gate")
    require(precommit.get("prior_best_mean_dps") == holdout.get("prior_p74_dps"),
            "precommitted prior mean")
    require(isinstance(trace.get("world_ack_trace"), list)
            and trace.get("acks", 0) > 0
            and trace["acks"] == len(trace["world_ack_trace"]), "world ACK count")
    return {
        "archive_lineage_checks": "PASS",
        "linked_search_sha256": sha256(search_bytes),
        "linked_precommit_sha256": sha256(precommit_bytes),
        "linked_generator_sha256": sha256(generator_bytes),
        "frozen_config_sha256": config_hash,
        "causal_trace_acks": trace["acks"],
    }


def audit_archive(path):
    data = Path(path).read_bytes()
    if sha256(data) != ARCHIVE_SHA256:
        raise ValueError("Original WF613 archive SHA256 mismatch")
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(HOLDOUT_MEMBER)
        search_bytes = archive.read("WF612/WF613_P75_COLD_300S.json")
        precommit_bytes = archive.read("WF612/WF612_P75_HOLDOUT_PRECOMMIT.json")
        generator_bytes = archive.read("WF612/p75_joint_search_wf612.py")
        trace = json.loads(archive.read("WF612/WF613_P75_WINNER_CAUSAL_TRACE.json"))
    if sha256(raw) != HOLDOUT_SHA256:
        raise ValueError("Original WF613 holdout member SHA256 mismatch")
    holdout = json.loads(raw)
    result = audit_payload(holdout)
    result.update(audit_lineage(holdout, json.loads(search_bytes), trace,
                                json.loads(precommit_bytes), search_bytes,
                                precommit_bytes, generator_bytes))
    result.update({"archive_sha256": ARCHIVE_SHA256, "holdout_member": HOLDOUT_MEMBER,
                   "holdout_sha256": HOLDOUT_SHA256})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_archive(args.archive), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

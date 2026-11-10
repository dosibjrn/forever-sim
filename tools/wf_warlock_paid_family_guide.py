#!/usr/bin/env python3
"""Publish an already-paid Warlock build comparison as a bounded guide input.

This is presentation of existing native/gsim 100-target receipts, not a
new simulation, legality check, source model, or M1 gate. The comparison
producer has already validated its raw native attempt and route receipts.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse

FAMILIES = ("Affliction", "Demonology", "Destruction")
PAID_STATES = {"MEASURED_CROSS_TREE_100", "MEASURED_CROSS_TREE_TIE_100"}


def _run_link(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").split("/")
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or len(path) != 5 or path[2:4] != ["actions", "runs"]
            or not path[4].isdigit() or parsed.query or parsed.fragment):
        raise ValueError("source run must be a concrete GitHub Actions run URL")
    return url.rstrip("/")


def _paid_measurement(row: dict) -> dict:
    """Require source-linked native-paid identities, not a short DPS screen."""
    elapsed = row.get("elapsed_seconds")
    source_sha = row.get("original_source_sha256")
    executed_sha = row.get("executed_source_sha256")
    family = row.get("dominant_talent_tree_index")
    if (row.get("status") != "MEASURED_NATIVE_100"
            or row.get("targets_killed") != 100
            or row.get("native_world_ack") is not True
            or row.get("paid_native_recovery") is not True
            or type(elapsed) not in (int, float)
            or not math.isfinite(elapsed) or elapsed <= 0
            or type(family) is not int or family not in (0, 1, 2)
            or not isinstance(row.get("native_observation_id"), str)
            or not row["native_observation_id"]
            or not isinstance(row.get("native_summary"), str)
            or not row["native_summary"]
            or not isinstance(source_sha, str) or len(source_sha) != 64
            or not isinstance(executed_sha, str) or len(executed_sha) != 64
            or not isinstance(row.get("talents"), str) or not row["talents"]):
        raise ValueError("measured build lacks complete native-paid receipt provenance")
    return {
        "candidate_index": row["index"],
        "family": FAMILIES[family],
        "family_tree_index": family,
        "talents": row["talents"],
        "elapsed_seconds_for_100_mobs": elapsed,
        "seconds_per_mob": round(elapsed / 100, 6),
        "native_observation_id": row["native_observation_id"],
        "source_request_sha256": source_sha,
        "executed_source_sha256": executed_sha,
        "native_summary": row["native_summary"],
        "requires_respec_from_paid_predecessor": row["requires_talent_respec_from_paid_source"],
        "final_hp": row.get("final_hp"),
        "final_mana": row.get("final_mana"),
    }


def build(comparison: dict, *, source_run_url: str, artifact_id: int) -> dict:
    """Turn a native-paid comparison into portable, honestly scoped guide data.

    The run/artifact URL is operator-supplied attribution, not a new receipt
    verification. No new native combat is executed or replayed.
    """
    run = _run_link(source_run_url)
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("original artifact ID is required")
    if comparison.get("kind") != "warlock_native_world_finalist_comparison_v1":
        raise ValueError("not an original native paid world comparison")
    if comparison.get("talent_respec_cost_measured") is not False:
        raise ValueError("cannot infer counterfactual talent respec cost")
    if comparison.get("m1_recording_performed") is not False:
        raise ValueError("route comparison cannot claim formal M1 recording")
    level = comparison.get("level")
    if type(level) is not int or not 10 <= level <= 60:
        raise ValueError("missing measured actor level")
    rows = comparison.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("missing native candidate receipts")
    paid = comparison.get("paid_predecessor")
    binary_sha = comparison.get("native_binary_sha256")
    if (not isinstance(paid, dict) or not paid.get("observation_id")
            or not isinstance(binary_sha, str) or len(binary_sha) != 64):
        raise ValueError("missing paid predecessor or selected Rust binary identity")
    pending = comparison.get("pending_candidate_indexes")
    if not isinstance(pending, list):
        raise ValueError("missing native paid trial completion state")

    measured = [_paid_measurement(row) for row in rows
                if row.get("status") == "MEASURED_NATIVE_100"]
    measured.sort(key=lambda row: (row["elapsed_seconds_for_100_mobs"],
                                   row["candidate_index"]))
    complete = (comparison.get("status") in PAID_STATES
                and comparison.get("distinct_build_families_compared") is True
                and not pending and len(measured) >= 2
                and len({row["family_tree_index"] for row in measured}) >= 2)
    winner = comparison.get("world_winner")
    if complete:
        fastest = measured[0]["elapsed_seconds_for_100_mobs"]
        tied = [row for row in measured
                if row["elapsed_seconds_for_100_mobs"] == fastest]
        if comparison["status"] == "MEASURED_CROSS_TREE_TIE_100":
            if winner is not None or len(tied) < 2:
                raise ValueError("tie claim differs from paid native measurements")
        elif (len(tied) != 1 or not isinstance(winner, dict)
              or winner.get("candidate_index") != tied[0]["candidate_index"]
              or winner.get("elapsed_seconds") != fastest):
            raise ValueError("winner claim differs from paid native measurements")

    return {
        "kind": "warlock_paid_family_guide_input_v1",
        "status": ("MEASURED_BOUNDED_FAMILY_COMPARISON" if complete
                   else "PROVISIONAL_NO_COMPARABLE_FAMILY_GUIDE"),
        "actor_level": level,
        "scope": "one hostile 100-mob native/gsim scenario; counterfactual builds",
        "source_run_url": run,
        "original_artifact_id": artifact_id,
        "original_artifact_url": run + "/artifacts/" + str(artifact_id),
        "selected_native_binary_sha256": binary_sha,
        "paid_predecessor_observation_id": paid["observation_id"],
        "measurements": measured if complete else [],
        "bounded_fastest_family": (tied[0]["family"] if complete and len(tied) == 1
                                   else None),
        "tied_fastest_families": ([row["family"] for row in tied]
                                 if complete and len(tied) > 1 else []),
        "other_or_unpaid_candidate_indexes": sorted(
            {row["index"] for row in rows
             if row.get("status") != "MEASURED_NATIVE_100"} | set(pending)),
        "actual_respec_execution_measured": False,
        "talent_respec_cost_measured": False,
        "continuous_level_route_measured": False,
        "full_route_optimum_measured": False,
        "stat_weights_measured": False,
        "m1_recording_performed": False,
    }


def _code(value: object) -> str:
    """Render native-receipt identifiers literally, never as Markdown markup."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    # A variable-length code fence prevents receipt-controlled backticks from
    # escaping their literal span.
    import re
    delimiter = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{delimiter}{text}{delimiter}"


def render_markdown(payload: dict) -> str:
    """Render guide JSON without upgrading incomplete paid evidence to a winner.

    This consumes only the Work1 adapter's bounded comparison, not source
    mechanics or a newly executed route. It is safe to hand to Work2 as a
    standalone section of the route dossier.
    """
    if not isinstance(payload, dict) or payload.get("kind") != "warlock_paid_family_guide_input_v1":
        raise ValueError("expected Work1 paid-family guide input")
    status = payload.get("status")
    if status not in ("MEASURED_BOUNDED_FAMILY_COMPARISON",
                      "PROVISIONAL_NO_COMPARABLE_FAMILY_GUIDE"):
        raise ValueError("unrecognized paid-family comparison status")
    level = payload.get("actor_level")
    if type(level) is not int or not 10 <= level <= 60:
        raise ValueError("missing native actor level")
    run = _run_link(payload.get("source_run_url", ""))
    artifact_id = payload.get("original_artifact_id")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ValueError("original paid artifact identity is required")
    artifact_url = f"{run}/artifacts/{artifact_id}"
    if payload.get("original_artifact_url") != artifact_url:
        raise ValueError("paid artifact link differs from source run")
    binary = payload.get("selected_native_binary_sha256")
    predecessor = payload.get("paid_predecessor_observation_id")
    if (not isinstance(binary, str) or len(binary) != 64
            or not isinstance(predecessor, str) or not predecessor):
        raise ValueError("missing native binary or predecessor provenance")
    for flag in ("actual_respec_execution_measured", "talent_respec_cost_measured",
                 "continuous_level_route_measured", "full_route_optimum_measured",
                 "stat_weights_measured", "m1_recording_performed"):
        if payload.get(flag) is not False:
            raise ValueError(f"unmeasured route claim: {flag}")
    rows = payload.get("measurements")
    if not isinstance(rows, list):
        raise ValueError("native paid measurements must be a list")
    fastest = payload.get("bounded_fastest_family")
    tied = payload.get("tied_fastest_families")
    if not isinstance(tied, list) or any(family not in FAMILIES for family in tied):
        raise ValueError("invalid paid-family tie metadata")

    lines = [
        f"## L{level} Warlock — native-paid talent-family comparison",
        "",
        "This compares **counterfactual talent builds** in one fixed hostile "
        "native/gsim 100-mob scenario with paid recovery; it is not full leveling time.",
        "",
        f"Original evidence: [native run]({run}) · "
        f"[paid 100-mob candidate artifact]({artifact_url}).",
        f"Selected native binary SHA-256: {_code(binary)}. "
        f"Paid predecessor observation: {_code(predecessor)}.",
        "",
    ]
    if status == "MEASURED_BOUNDED_FAMILY_COMPARISON":
        if len(rows) < 2:
            raise ValueError("complete comparison requires multiple measured families")
        indexed = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("malformed measured candidate")
            family = row.get("family")
            index = row.get("candidate_index")
            elapsed = row.get("elapsed_seconds_for_100_mobs")
            per_mob = row.get("seconds_per_mob")
            if (family not in FAMILIES or type(index) is not int or index <= 0
                    or index in indexed or type(elapsed) not in (int, float)
                    or not math.isfinite(elapsed) or elapsed <= 0
                    or type(per_mob) not in (int, float)
                    or not math.isfinite(per_mob)
                    or not math.isclose(per_mob, elapsed / 100, abs_tol=0.000001)
                    or not isinstance(row.get("talents"), str) or not row["talents"]
                    or not isinstance(row.get("native_observation_id"), str)
                    or not row["native_observation_id"]
                    or not isinstance(row.get("native_summary"), str)
                    or not row["native_summary"]
                    or not isinstance(row.get("source_request_sha256"), str)
                    or len(row["source_request_sha256"]) != 64
                    or not isinstance(row.get("executed_source_sha256"), str)
                    or len(row["executed_source_sha256"]) != 64
                    or type(row.get("requires_respec_from_paid_predecessor")) is not bool):
                raise ValueError("malformed paid candidate for Markdown")
            indexed.add(index)
        if len({row["family"] for row in rows}) < 2:
            raise ValueError("paid comparison needs distinct talent families")
        minimum = min(row["elapsed_seconds_for_100_mobs"] for row in rows)
        actual_ties = [row["family"] for row in rows
                       if row["elapsed_seconds_for_100_mobs"] == minimum]
        if len(actual_ties) == 1:
            if fastest != actual_ties[0] or tied:
                raise ValueError("winner metadata contradicts paid native measurements")
            lines += [
                f"**Fastest in this scenario: {fastest}** "
                f"({minimum / 100:.3f} s/mob). "
                "This does not establish a route-wide spec winner.",
                "",
            ]
        else:
            if fastest is not None or tied != actual_ties:
                raise ValueError("tie metadata contradicts paid native measurements")
            lines += [
                "**Measured tie for fastest:** " + ", ".join(actual_ties) +
                f" ({minimum / 100:.3f} s/mob); no unique winner.",
                "",
            ]
        lines += ["### Measured native 100/100 candidates", ""]
        for row in sorted(rows, key=lambda item: (item["elapsed_seconds_for_100_mobs"],
                                                   item["candidate_index"])):
            lines += [
                f"- **{row['family']}** (candidate #{row['candidate_index']}): "
                f"**{row['seconds_per_mob']:.3f} s/mob**, "
                f"{row['elapsed_seconds_for_100_mobs']:.3f} s / 100 hostile kills; "
                f"native talents {_code(row['talents'])}; "
                f"observation {_code(row['native_observation_id'])}.",
                f"  - Original source SHA-256: {_code(row['source_request_sha256'])}; "
                f"executed source SHA-256: {_code(row['executed_source_sha256'])}.",
                f"  - Native summary in [original artifact]({artifact_url}): "
                f"{_code(row['native_summary'])}. "
                f"Respec from paid predecessor required: "
                f"**{'yes' if row['requires_respec_from_paid_predecessor'] else 'no'}** "
                "(cost unmeasured).",
            ]
    else:
        if rows or fastest is not None or tied:
            raise ValueError("provisional comparison cannot publish a measured winner")
        indexes = payload.get("other_or_unpaid_candidate_indexes")
        if (not isinstance(indexes, list)
                or any(type(index) is not int or index <= 0 for index in indexes)):
            raise ValueError("malformed unpaid-candidate provenance")
        lines += [
            "**No comparable paid family winner is measured.** "
            "The native comparison is incomplete, incomparable, or lacks enough "
            "distinct full 100/100 candidate receipts. No spec is ranked.",
            "",
            "Unpaid or refused candidate indexes: " +
            (", ".join(str(index) for index in indexes) if indexes else "none reported") + ".",
        ]
    lines += [
        "",
        "**Limitations:** Respec execution and cost, continuous L46→L47 ancestry, "
        "full L10–60 optimal route, stat weights and M1 gate certification "
        "are **not measured by this comparison**. Do not infer those from "
        "the observed 100-mob times.",
        "",
    ]
    return "\n".join(lines)


def publish(*, comparison: Path, source_run_url: str, artifact_id: int,
            out: Path, markdown_out: Path | None = None) -> dict:
    result = build(json.loads(comparison.read_text()),
                   source_run_url=source_run_url, artifact_id=artifact_id)
    section = render_markdown(result) if markdown_out is not None else None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if markdown_out is not None:
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(section)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", required=True, type=Path)
    parser.add_argument("--source-run-url", required=True)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--markdown-out", type=Path,
                        help="Optional player-readable bounded family comparison section")
    result = publish(**vars(parser.parse_args()))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

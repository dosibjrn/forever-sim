#!/usr/bin/env python3
"""Exercise real selected-Rust Druid rank-pair behavior for two native effects.

These are source-layout/runtime diagnostics, not a P2 acceptance run. The P2
gate still requires a complete per-rank native evidence set before it can
declare production_engine=msim.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine_client.native_p2_rank_probe import (
    NativeP2ProbeError,
    NativeRngMode,
    encode_native_druid_talents,
    load_native_druid_layout,
    run_native_rank_pair,
)


def _decode_fixture_talents(request: dict, layout: dict) -> dict[str, int]:
    player = request["raid"]["parties"][0]["players"][0]
    parts = player["talentsString"].split("-")
    if len(parts) != 3:
        raise AssertionError("Druid fixture must contain three talent-tree segments")
    selection = {}
    for (tree_key, entries), part in zip(layout.items(), parts):
        if len(part) > len(entries):
            raise AssertionError(f"{tree_key} fixture segment exceeds native layout")
        for index, char in enumerate(part):
            if not char.isdigit():
                raise AssertionError(f"Invalid talent rank character: {char!r}")
            rank = int(char)
            if rank:
                selection[entries[index]["field"]] = rank
    return selection


def _fixture_request(engine_root: Path, scenario: str) -> dict:
    path = engine_root / "tests" / "classes" / "druid" / "prepare" / f"{scenario}.request.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    args = parser.parse_args()

    layout, layout_metadata = load_native_druid_layout(
        args.engine_root, binary=args.binary
    )
    if (
        os.environ.get("FOREVER_EXPECT_NATIVE_TALENT_LAYOUT_API") == "1"
        and layout_metadata.get("source") != "native_cli"
    ):
        raise SystemExit(
            "NATIVE_DRUID_TALENT_LAYOUT_API_REQUIRED:"
            + str(layout_metadata.get("source"))
        )
    assert [len(layout[k]) for k in ("balance", "feral", "restoration")] == [16, 20, 16]
    assert layout["balance"][15]["field"] == "moonkin_form"
    assert layout["feral"][10]["field"] == "predatory_strikes"

    # Round-trip each pinned engine fixture through the Rust-derived layout.
    for scenario in ("balance",):
        fixture = _fixture_request(args.engine_root, scenario)
        selection = _decode_fixture_talents(fixture, layout)
        encoded = encode_native_druid_talents(selection, args.engine_root, layout=layout)
        roundtrip = _fixture_request(args.engine_root, scenario)
        roundtrip["raid"]["parties"][0]["players"][0]["talentsString"] = encoded
        assert _decode_fixture_talents(roundtrip, layout) == selection

    # Reject coercion: source rank facts must be exact integers.
    for invalid_rank in (True, 1.5, "1"):
        try:
            encode_native_druid_talents(
                {"predatory_strikes": invalid_rank}, args.engine_root, layout=layout
            )
        except NativeP2ProbeError:
            pass
        else:
            raise AssertionError(f"Non-integer source rank accepted: {invalid_rank!r}")

    # Use each selected-Rust fixture's own legal build, changing only the
    # target rank. This keeps gear, rotation, encounter and all other talents
    # byte-for-byte equivalent across the paired runs.
    moonkin_after = _decode_fixture_talents(
        _fixture_request(args.engine_root, "balance"), layout
    )
    assert moonkin_after.get("moonkin_form") == 1
    moonkin_before = dict(moonkin_after)
    moonkin_before.pop("moonkin_form")
    assert encode_native_druid_talents(moonkin_before, args.engine_root, layout=layout).split("-")[0][-1] == "0"

    # Construct a focused 15-point Feral control, then add only
    # Predatory Strikes rank 1. The adapter forwards the pair to the selected
    # native prepare/sim path; Python does not inspect or enforce rank caps.
    predatory_before = {
        "ferocity": 5,
        "furor": 5,
        "feral_swiftness": 2,
        "feral_instinct": 3,
    }
    predatory_after = {**predatory_before, "predatory_strikes": 1}
    predatory_request = _fixture_request(args.engine_root, "cat")
    predatory_request["raid"]["parties"][0]["players"][0]["talentsString"] = (
        encode_native_druid_talents(predatory_after, args.engine_root, layout=layout)
    )
    assert _decode_fixture_talents(predatory_request, layout) == predatory_after
    assert encode_native_druid_talents(predatory_before, args.engine_root, layout=layout).split("-")[1][10] == "0"

    results = {
        "moonkin_form": run_native_rank_pair(
            binary=args.binary,
            engine_root=args.engine_root,
            scenario="balance",
            before_selection=moonkin_before,
            after_selection=moonkin_after,
            target_talent_id="moonkin_form",
            target_rank=1,
            iterations=100,
            seed=647003,
            rng_mode=NativeRngMode.BALANCED,
        ),
        "predatory_strikes": run_native_rank_pair(
            binary=args.binary,
            engine_root=args.engine_root,
            scenario="cat",
            before_selection=predatory_before,
            after_selection=predatory_after,
            target_talent_id="predatory_strikes",
            target_rank=1,
            iterations=100,
            seed=647003,
            rng_mode=NativeRngMode.BALANCED,
        ),
    }
    for name, result in results.items():
        before = result.get("before", {}).get("prepared", {})
        after = result.get("after", {}).get("prepared", {})
        if not before.get("prepared_sha256") or not after.get("prepared_sha256"):
            raise SystemExit(f"NATIVE_P2_PREPARE_RECEIPT_MISSING:{name}")
        if before["prepared_sha256"] == after["prepared_sha256"]:
            raise SystemExit(f"NATIVE_P2_PREPARED_STATE_UNCHANGED:{name}")
        if result.get("accepted_for_p2") is not False:
            raise SystemExit(f"NATIVE_P2_DIAGNOSTIC_MUST_NOT_ACCEPT:{name}")
    print(json.dumps(results, sort_keys=True, indent=2))
    failed = [name for name, result in results.items() if result.get("status") != "PROBE_PASS"]
    if failed:
        raise SystemExit("NATIVE_P2_RANK_PAIR_DIAGNOSTIC_FAILED:" + ",".join(failed))
    # Exercise the actual P2 provider's bounded selected-native diagnostic
    # scope (Predatory Strikes ranks 1-3). These receipts are not acceptance.
    os.environ["FOREVER_MYTHICSIM_RUST_BIN"] = str(args.binary.resolve())
    from tools.wf_gate_p2_live import run_live

    p2_report = run_live(ROOT, "druid", 60, spec="balance")
    expected_rank_keys = {
        "predatory_strikes:1",
        "predatory_strikes:2",
        "predatory_strikes:3",
    }
    native_receipts = p2_report.get("native_rank_probe_results", [])
    actual_rank_keys = sorted(
        str(row.get("rank_key")) for row in native_receipts
        if isinstance(row, dict) and row.get("rank_key")
    )
    if set(actual_rank_keys) != expected_rank_keys:
        print(json.dumps({
            "expected_rank_keys": sorted(expected_rank_keys),
            "actual_rank_keys": actual_rank_keys,
            "p2_gate_status": p2_report.get("status"),
            "p2_gate_reasons": p2_report.get("reasons"),
            "source_db_kind": p2_report.get("source_db_kind"),
            "source_id": p2_report.get("source_id"),
            "reachability_count": p2_report.get("reachability_count"),
            "reachable_rank_keys": sorted(
                str(row.get("rank_key")) for row in p2_report.get("ranks", [])
                if isinstance(row, dict) and row.get("rank_key")
            ),
            "native_rank_probe_results": [
                {"rank_key": row.get("rank_key"), "status": row.get("status"),
                 "reason": row.get("reason")}
                for row in native_receipts if isinstance(row, dict)
            ],
            "native_rank_probe_summary": p2_report.get("native_rank_probe_summary"),
        }, sort_keys=True, indent=2))
        raise SystemExit("NATIVE_P2_LIVE_GATE_SOURCE_RANK_RECEIPTS_INCOMPLETE")
    if any(row.get("status") != "PROBE_PASS" for row in native_receipts):
        raise SystemExit("NATIVE_P2_LIVE_GATE_SOURCE_RANK_RECEIPT_FAILED")
    if any(row.get("accepted_for_p2") is not False for row in native_receipts):
        raise SystemExit("NATIVE_P2_LIVE_GATE_DIAGNOSTIC_MUST_NOT_ACCEPT")
    if p2_report.get("source_db_kind") != "staged_druid_source_catalogue":
        raise SystemExit("NATIVE_P2_LIVE_GATE_DID_NOT_USE_STAGED_SOURCE_CATALOGUE")
    if p2_report.get("native_rank_probe_summary", {}).get("counted_in_p2_acceptance") is not False:
        raise SystemExit("NATIVE_P2_LIVE_GATE_DIAGNOSTIC_COUNTED_AS_ACCEPTANCE")
    print(json.dumps({
        "p2_gate_status": p2_report.get("status"),
        "source_db_kind": p2_report.get("source_db_kind"),
        "native_rank_probe_summary": p2_report.get("native_rank_probe_summary"),
        "native_rank_probe_results": [
            {"rank_key": row.get("rank_key"), "status": row.get("status"),
             "reason": row.get("reason")}
            for row in native_receipts
        ],
        "production_engine": p2_report.get("production_engine"),
    }, sort_keys=True, indent=2))
    print("SELECTED_RUST_NATIVE_P2_SOURCE_BACKED_LIVE_GATE_DIAGNOSTICS_PASS_NOT_ACCEPTANCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Exercise real selected-Rust Druid rank-pair behavior for two native effects.

These are source-layout/runtime diagnostics, not a P2 acceptance run. The P2
gate still requires a complete per-rank native evidence set before it can
declare production_engine=msim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game.native_p2_rank_probe import (
    NativeP2ProbeError,
    NativeRngMode,
    encode_native_druid_talents,
    parse_native_druid_layout,
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

    layout = parse_native_druid_layout(args.engine_root)
    assert [len(layout[k]) for k in ("balance", "feral", "restoration")] == [16, 20, 16]
    assert layout["balance"][15]["field"] == "moonkin_form"
    assert layout["balance"][15]["max_rank"] == 1
    assert layout["feral"][10]["field"] == "predatory_strikes"
    assert layout["feral"][10]["max_rank"] == 3

    # Round-trip each pinned engine fixture through the Rust-derived layout.
    for scenario in ("balance", "cat"):
        fixture = _fixture_request(args.engine_root, scenario)
        selection = _decode_fixture_talents(fixture, layout)
        encoded = encode_native_druid_talents(selection, args.engine_root)
        roundtrip = _fixture_request(args.engine_root, scenario)
        roundtrip["raid"]["parties"][0]["players"][0]["talentsString"] = encoded
        assert _decode_fixture_talents(roundtrip, layout) == selection

    # Reject coercion: source rank facts must be exact integers.
    for invalid_rank in (True, 1.5, "1"):
        try:
            encode_native_druid_talents(
                {"predatory_strikes": invalid_rank}, args.engine_root
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
    assert encode_native_druid_talents(moonkin_before, args.engine_root).split("-")[0][-1] == "0"

    predatory_after = _decode_fixture_talents(
        _fixture_request(args.engine_root, "cat"), layout
    )
    assert predatory_after.get("predatory_strikes") == 1
    predatory_before = dict(predatory_after)
    predatory_before.pop("predatory_strikes")
    assert encode_native_druid_talents(predatory_before, args.engine_root).split("-")[1][10] == "0"

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
            rng_mode="balanced",
        ),
    }
    for name, result in results.items():
        before = result.get("before", {})
        after = result.get("after", {})
        if not before.get("prepared_sha256") or not after.get("prepared_sha256"):
            raise SystemExit(f"NATIVE_P2_PREPARE_RECEIPT_MISSING:{name}")
        if before["prepared_sha256"] == after["prepared_sha256"]:
            raise SystemExit(f"NATIVE_P2_PREPARED_STATE_UNCHANGED:{name}")
    print(json.dumps(results, sort_keys=True, indent=2))
    failed = [name for name, result in results.items() if result.get("status") != "PASS"]
    if failed:
        raise SystemExit("NATIVE_P2_RANK_PAIR_DIAGNOSTIC_FAILED:" + ",".join(failed))
    print("SELECTED_RUST_NATIVE_P2_RANK_PAIR_DIAGNOSTICS_PASS_NOT_ACCEPTANCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

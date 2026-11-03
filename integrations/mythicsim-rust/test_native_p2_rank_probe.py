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
    encode_native_druid_talents,
    parse_native_druid_layout,
    run_native_rank_pair,
)


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

    # Native source test witness: 30 prior Balance points unlock Moonkin Form.
    moonkin_before = {
        "improved_wrath": 5,
        "genesis": 5,
        "moonglow": 3,
        "improved_moonfire": 2,
        "natures_majesty": 2,
        "natures_reach": 2,
        "improved_entangling_roots": 3,
        "natures_splendor": 1,
        "insect_swarm": 1,
        "vengeance": 5,
        "improved_starfire": 1,
    }
    moonkin_after = {**moonkin_before, "moonkin_form": 1}
    moonkin_before_string = encode_native_druid_talents(
        moonkin_before, args.engine_root
    )
    moonkin_after_string = encode_native_druid_talents(
        moonkin_after, args.engine_root
    )
    assert moonkin_before_string.split("-")[0] == "5532223115100000"
    assert moonkin_after_string.split("-")[0] == "5532223115100001"

    # Native source test witness: Ferocity 5 + Furor 5 + Feral Swiftness 2
    # + Feral Instinct 3 = 15 prior Feral points before Predatory Strikes.
    predatory_before = {
        "ferocity": 5,
        "furor": 5,
        "feral_swiftness": 2,
        "feral_instinct": 3,
    }
    predatory_after = {**predatory_before, "predatory_strikes": 1}
    predatory_before_string = encode_native_druid_talents(
        predatory_before, args.engine_root
    )
    predatory_after_string = encode_native_druid_talents(
        predatory_after, args.engine_root
    )
    assert predatory_before_string.split("-")[1].startswith("5523000000")
    assert predatory_after_string.split("-")[1][10] == "1"

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
            rng_mode="balanced",
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
    print(json.dumps(results, sort_keys=True, indent=2))
    failed = [name for name, result in results.items() if result.get("status") != "PASS"]
    if failed:
        raise SystemExit("NATIVE_P2_RANK_PAIR_DIAGNOSTIC_FAILED:" + ",".join(failed))
    print("SELECTED_RUST_NATIVE_P2_RANK_PAIR_DIAGNOSTICS_PASS_NOT_ACCEPTANCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

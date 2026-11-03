#!/usr/bin/env python3
"""Real selected-Rust P1 direct-action probe for Druid L20 source Claw (1082).

This is a native request/response integration test, not a P1 gate or M1 PASS.
The checkpoint level selects the source action; the current RaidSimRequest
fixture has no player-level field, so this test makes no acquisition claim.
Claw is a direct damage action, so the P1 contract does not require a 2D world
bridge for this effect.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wf_p1_native_effects import (
    DRUID_CLAW_RANK1,
    VERIFIED_EFFECT,
    build_druid_cat_action_request,
    run_native,
)


def main() -> int:
    engine_root = ROOT / "integrations" / "mythicsim-rust" / "engine"
    binary = Path(os.environ.get(
        "FOREVER_ENGINE_BINARY",
        str(engine_root / "target" / "debug" / "forever-engine"),
    ))
    request = build_druid_cat_action_request(engine_root, DRUID_CLAW_RANK1)
    result = run_native(
        binary,
        request,
        class_key="druid",
        level=20,
        spell_id=DRUID_CLAW_RANK1,
        root=ROOT,
        iterations=10,
        seed=647003,
        world_required=False,
        scenario_label="p1-druid-l20-feral-claw-1082",
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    assert result.get("p1_certified") is False
    assert result.get("world_required") is False

    status = result.get("status")
    if status == VERIFIED_EFFECT:
        assert result.get("effect_observed") is True
        assert result.get("native_executed") is True
        assert result.get("observable_effects", {}).get("dps_delta", 0) > 0
        return 0

    # Native refusal or a genuine no-effect response is a valid authoritative
    # result for this adapter test, but never a P1 pass and never a GameIR
    # fallback. Adapter/build/timeout failures remain test failures.
    assert status in {"INVALID", "UNSUPPORTED", "NO_DIRECT_EFFECT_OBSERVED"}, result
    assert result.get("effect_observed") is False
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Real selected-pin P1 action/control plus live 2D world bridge integration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wf_gate_p1_live import run_live


def main() -> None:
    binary_value = os.environ.get("FOREVER_MYTHICSIM_RUST_BIN") or os.environ.get("FOREVER_ENGINE_BINARY")
    if not binary_value:
        raise SystemExit("FOREVER_MYTHICSIM_RUST_BIN or FOREVER_ENGINE_BINARY is required")

    # Exercise the actual tools/wf_gate.py -> run_live acceptance provider.
    # The provider selects this one source identity, then delegates validity
    # and behavior to the exact selected Rust PreparedV2 + live 2D path.
    report = run_live(ROOT, "druid", 60, spec="balance")
    probes = report.get("native_effect_probes", [])
    if len(probes) != 1:
        raise AssertionError(json.dumps({
            "gate_status": report.get("status"),
            "native_effect_probes": probes,
            "reasons": report.get("reasons"),
        }, sort_keys=True, allow_nan=False))
    result = probes[0]
    assert report["status"] == "FAIL"  # one canary is deliberately not full P1 acceptance
    assert report["native_migration_scope"] == "druid:60:balance:spell-9912"
    assert report["pass_count"] == 0 and report["reachability_count"] == 0
    if result.get("status") != "NATIVE_DIRECT_BEHAVIOR_VERIFIED":
        raise AssertionError(json.dumps(result, sort_keys=True, allow_nan=False))
    assert result["spell_id"] == 9912
    assert result["native_executed"] is True
    assert result["effect_observed"] is True
    assert result["controlled_behavior_assertion_passed"] is True
    assert result["dps_delta"] > 0
    assert result["world_targets_killed"] == 2
    assert result["native_damage_events"] > 0
    assert result["actual_2d_ack"] is True
    assert result["p1_certified"] is False

    print(json.dumps({
        "gate_status": report["status"],
        "native_probe": result,
        "p1_certified": False,
    }, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

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

from src.engine_client.native_p1_effect_probe import run_native_p1_direct_effect_probe


def main() -> None:
    binary_value = os.environ.get("FOREVER_ENGINE_BINARY")
    if not binary_value:
        raise SystemExit("FOREVER_ENGINE_BINARY is required")
    engine_root = ROOT / "integrations" / "mythicsim-rust" / "engine"
    fixture = engine_root / "tests" / "classes" / "druid" / "prepare" / "balance.request.json"
    request = json.loads(fixture.read_text(encoding="utf-8"))
    player = request["raid"]["parties"][0]["players"][0]
    if player.get("class") != "ClassDruid":
        raise AssertionError("Druid Balance fixture class changed")
    rows = player["rotation"]["priorityList"]
    if len(rows) != 1:
        raise AssertionError(f"expected one fixture action, got {len(rows)}")
    spell = rows[0]["action"]["castSpell"]["spellId"]["spellId"]
    if spell != 9912:
        raise AssertionError(f"expected fixture action 9912, got {spell}")

    result = run_native_p1_direct_effect_probe(
        binary=Path(binary_value),
        engine_root=engine_root,
        request=request,
        spell_id=spell,
        timeout_seconds=120.0,
        iterations=10,
        seed=647003,
        target_count=2,
        world_mob_health=1200.0,
    )
    if result.get("status") != "NATIVE_DIRECT_BEHAVIOR_VERIFIED":
        raise AssertionError(json.dumps(result, sort_keys=True, allow_nan=False))
    world = result["world_bridge"]
    assert result["positive_action_count"] == 1
    assert result["control_action_count"] == 0
    assert result["dps_delta"] > 0
    assert result["effect_observed"] is True
    assert result["controlled_behavior_assertion_passed"] is True
    assert world["actual_2d_ack"] is True
    assert world["continuous_native_actor"] is True
    assert world["native_damage_events"] > 0
    assert world["checkpoint_certified"] is False
    assert result["p1_certified"] is False

    print(json.dumps({
        "status": result["status"],
        "spell_id": spell,
        "dps_with_action": result["dps_with_action"],
        "dps_without_action": result["dps_without_action"],
        "dps_delta": result["dps_delta"],
        "world_targets_killed": world["world_targets_killed"],
        "native_damage_events": world["native_damage_events"],
        "actual_2d_ack": world["actual_2d_ack"],
        "engine_identity": result["engine_identity"],
        "p1_certified": False,
    }, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Real selected-pin P1 direct effects: native-only and native-to-2D diagnostics."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine_client.native_p1_effect_probe import run_native_p1_direct_effect_probe


def _cast_spell_id(row: dict) -> int | None:
    action = row.get("action") if isinstance(row, dict) else None
    cast = action.get("castSpell") if isinstance(action, dict) else None
    spell = cast.get("spellId") if isinstance(cast, dict) else None
    if isinstance(spell, dict):
        spell = spell.get("spellId")
    return spell if type(spell) is int else None


def _run_case(*, name: str, fixture: Path, expected_class: str, spell_id: int,
              binary: Path, engine_root: Path, requires_2d_world: bool) -> dict:
    request = json.loads(fixture.read_text(encoding="utf-8"))
    player = request["raid"]["parties"][0]["players"][0]
    if player.get("class") != expected_class:
        raise AssertionError(f"{name}: expected {expected_class}, got {player.get('class')!r}")

    action_row = None
    rows = player["rotation"]["priorityList"]
    if not any(_cast_spell_id(row) == spell_id for row in rows):
        raise AssertionError(f"{name}: selected action {spell_id} absent from fixture APL")
    if name == "hunter-marksmanship":
        # Keep the fixture's combat, gear and build, but clear its separate
        # pre-pull action channel symmetrically for a single-action pair.
        prepull = player["rotation"].get("prepullActions")
        if not isinstance(prepull, list):
            raise AssertionError("Hunter fixture pre-pull channel shape changed")
        player["rotation"]["prepullActions"] = []
        # An unconditional Aimed Shot row isolates the native action from the
        # fixture's APL timing condition; the no-action control differs only
        # in the priorityList.
        action_row = {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}

    result = run_native_p1_direct_effect_probe(
        binary=binary,
        engine_root=engine_root,
        request=request,
        spell_id=spell_id,
        action_row=action_row,
        timeout_seconds=120.0,
        iterations=10,
        seed=647003,
        target_count=100 if requires_2d_world else 0,
        requires_2d_world=requires_2d_world,
    )
    expected_status = (
        "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
        if requires_2d_world else "NATIVE_DIRECT_EFFECT_VERIFIED"
    )
    if result.get("status") != expected_status:
        raise AssertionError(json.dumps(result, sort_keys=True, allow_nan=False))
    assert result["native_executed"] is True
    assert result["effect_observed"] is True
    assert result["controlled_behavior_assertion_passed"] is True
    assert result["dps_delta"] > 0
    assert result["p1_certified"] is False

    output = {
        "case": name,
        "spell_id": spell_id,
        "status": result["status"],
        "dps_with_action": result["dps_with_action"],
        "dps_without_action": result["dps_without_action"],
        "dps_delta": result["dps_delta"],
        "engine_identity": result["engine_identity"],
        "p1_certified": False,
    }
    if requires_2d_world:
        world = result["world_bridge"]
        assert result["world_bridge_required"] is True
        assert world["actual_2d_ack"] is True
        assert world["continuous_native_actor"] is True
        assert world["world_targets_killed"] == 100
        assert len(world["world_kills"]) == 100
        assert len(world["native_windows"]) == 100
        assert world["native_damage_events"] >= 100
        assert world["checkpoint_certified"] is False
        output.update({
            "world_targets_requested": 100,
            "world_targets_killed": world["world_targets_killed"],
            "native_damage_events": world["native_damage_events"],
            "actual_2d_ack": world["actual_2d_ack"],
        })
    else:
        assert result["world_bridge_required"] is False
        assert result["world_bridge_status"] == "NOT_REQUIRED_NONSPATIAL_EFFECT"
        assert "world_bridge" not in result
    return output


def main() -> None:
    binary_value = os.environ.get("FOREVER_ENGINE_BINARY")
    if not binary_value:
        raise SystemExit("FOREVER_ENGINE_BINARY is required")
    engine_root = ROOT / "integrations" / "mythicsim-rust" / "engine"
    binary = Path(binary_value)

    results = [
        _run_case(
            name="druid-balance",
            fixture=engine_root / "tests" / "classes" / "druid" / "prepare" / "balance.request.json",
            expected_class="ClassDruid",
            spell_id=9912,
            binary=binary,
            engine_root=engine_root,
            requires_2d_world=True,
        ),
        _run_case(
            name="hunter-marksmanship",
            fixture=engine_root / "fixtures" / "mage" / "prepared-v2" / "production-marksmanship-hunter.request.json",
            expected_class="ClassHunter",
            spell_id=20904,
            binary=binary,
            engine_root=engine_root,
            requires_2d_world=False,
        ),
    ]
    print(json.dumps(results, sort_keys=True, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()

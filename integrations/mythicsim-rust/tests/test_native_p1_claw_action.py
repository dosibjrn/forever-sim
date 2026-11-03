"""Real selected-Rust PreparedV2 effect observation for the P1 Druid Claw caller.

This is deliberately not a spell-acquisition or L20 legality test. The source
action reference selects the spell identity; MythicSim owns prepare/sim
validity. The native request schema currently carries no player-level field.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    os.environ.setdefault("WOW_FOREVER_BUILD_AS_OF", "2026-10-17")

    from src.engine_client.native_p1_action import run_native_p1_action
    from src.game.data.forever.source_ability_semantics import latest_source_action_ref

    engine_root = ROOT / "integrations/mythicsim-rust/engine"
    binary = Path(
        os.environ.get(
            "FOREVER_ENGINE_BINARY",
            str(engine_root / "target/debug/forever-engine"),
        )
    )
    if not binary.is_file():
        raise SystemExit(f"selected Rust engine binary missing: {binary}")

    # Source identity only selects the action to submit. No spellbook,
    # learned-state, rank-eligibility, or Python legality proof is consulted.
    source_action = latest_source_action_ref("druid", "claw", 20)
    if source_action is None or source_action.spell_id <= 0:
        raise SystemExit("Druid Claw source action identity unavailable")
    if not str(source_action.id).startswith("claw:"):
        raise SystemExit(f"unexpected Claw source action identity: {source_action.id}")

    pin = subprocess.run(
        ["git", "-C", str(engine_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    ).stdout.strip()
    result = run_native_p1_action(
        binary=binary,
        engine_root=engine_root,
        spell_id=int(source_action.spell_id),
        action_id=str(source_action.id),
        source_level_hint=int(source_action.level),
        engine_sha=pin,
        iterations=100,
        seed=647003,
        timeout_seconds=180.0,
    )
    print(json.dumps(result, sort_keys=True, default=str))

    assert result["status"] == "NATIVE_EFFECT_OBSERVED", result
    assert result["effect_observed"] is True
    assert result["native_authority"] == "MythicSim Rust PreparedV2"
    assert result["engine_commit_sha"] == pin
    assert result["with_action_prepare"]["status"] == "PREPARED"
    assert result["no_action_prepare"]["status"] == "PREPARED"
    assert result["with_action_sim"]["status"] == "EXECUTED"
    assert result["no_action_sim"]["status"] == "EXECUTED"
    assert result["with_action_prepare"]["request_sha256"] != result["no_action_prepare"]["request_sha256"]
    assert result["baseline_dps"] > result["control_dps"]
    assert result["delta_dps"] > 0
    assert result["p1_certified"] is False
    assert result["accepted_for_p1"] is False
    assert result["native_player_level_modeled"] is False


if __name__ == "__main__":
    main()

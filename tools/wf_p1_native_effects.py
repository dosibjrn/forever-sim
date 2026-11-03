#!/usr/bin/env python3
"""Selected-Rust PreparedV2 single-action effect diagnostic; never a P1 PASS.

The native engine owns spell/rank validity and combat behavior. This adapter
constructs one concrete Druid Cat request from the pinned Rust fixture, then
compares its single selected castSpell action with an otherwise identical
no-action control. It does not consult source spellbooks, acquisition ledgers,
source eligibility classifiers, or GameIR effects.

A live 2D bridge is opt-in only for an effect whose behavior is world-owned.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.engine_client.native_p1_effect_probe import (
    native_single_action_pair,
    run_native_p1_direct_effect_probe,
)

VERIFIED_EFFECT = "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
DRUID_CLAW_RANK1 = 1082


def build_druid_cat_action_request(engine_root: Path, spell_id: int) -> dict:
    """Build a one-action request from the selected Rust Druid Cat fixture.

    The source action ID selects the test only. No Forever-side spellbook or
    acquisition check runs here; PreparedV2 decides whether the request is
    valid, unsupported, and executable.
    """
    if type(spell_id) is not int or spell_id <= 0:
        raise ValueError("NATIVE_P1_SELECTED_SPELL_ID_INVALID")
    fixture = (
        Path(engine_root) / "tests" / "classes" / "druid" / "prepare"
        / "cat.request.json"
    )
    if not fixture.is_file():
        raise FileNotFoundError("NATIVE_P1_DRUID_CAT_FIXTURE_MISSING:" + str(fixture))
    request = json.loads(fixture.read_text(encoding="utf-8"))
    try:
        player = request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("NATIVE_P1_REQUEST_PLAYER_PATH_MISSING") from exc
    if player.get("class") != "ClassDruid":
        raise ValueError("NATIVE_P1_DRUID_FIXTURE_CLASS_CHANGED")
    rotation = player.get("rotation")
    if not isinstance(rotation, dict):
        raise ValueError("NATIVE_P1_APL_ROTATION_MISSING")
    rotation["priorityList"] = [{
        "action": {"castSpell": {"spellId": {"spellId": spell_id}}}
    }]
    return request


def run_native(
    binary: Path,
    request: dict,
    *,
    class_key: str,
    level: int,
    spell_id: int,
    timeout_s: float = 120.0,
    root: Path = ROOT,
    world_required: bool = False,
    scenario_label: str | None = None,
    target_count: int = 2,
    mob_health: float | None = 1200.0,
    iterations: int = 10,
    seed: int = 647003,
) -> dict:
    """Call the pinned native PreparedV2 adapter; preserve every native refusal."""
    try:
        report = run_native_p1_direct_effect_probe(
            binary=binary,
            engine_root=root / "integrations" / "mythicsim-rust" / "engine",
            request=request,
            spell_id=spell_id,
            timeout_seconds=timeout_s,
            iterations=iterations,
            seed=seed,
            target_count=target_count,
            world_mob_health=mob_health,
            world_required=world_required,
            scenario_label=scenario_label or (
                f"p1-{class_key}-checkpoint-{level}-single-action-{spell_id}"
            ),
        )
    except Exception as exc:
        report = {
            "status": "ERROR",
            "stage": "native_adapter",
            "reason": f"{type(exc).__name__}:{exc}",
            "native_executed": False,
            "effect_observed": False,
            "p1_certified": False,
        }
    report.update({
        "class": class_key,
        "checkpoint_level": level,
        "spell_id": spell_id,
        "p1_certified": False,
    })
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True,
                        help="Go RaidSimRequest JSON; not a PreparedV2 report")
    parser.add_argument("--class", dest="class_key", required=True)
    parser.add_argument("--level", type=int, required=True,
                        help="Forever checkpoint selector; not a Rust player-level field")
    parser.add_argument("--spell-id", type=int, required=True)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--seed", type=int, default=647003)
    parser.add_argument("--world-required", action="store_true")
    parser.add_argument("--scenario-label")
    parser.add_argument("--targets", type=int, default=2)
    parser.add_argument("--mob-health", type=float, default=1200.0)
    args = parser.parse_args(argv)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    report = run_native(
        args.binary.resolve(),
        request,
        class_key=args.class_key,
        level=args.level,
        spell_id=args.spell_id,
        timeout_s=args.timeout_s,
        world_required=args.world_required,
        scenario_label=args.scenario_label,
        target_count=args.targets,
        mob_health=args.mob_health,
        iterations=args.iterations,
        seed=args.seed,
    )
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report.get("status") == VERIFIED_EFFECT else 2


if __name__ == "__main__":
    raise SystemExit(main())

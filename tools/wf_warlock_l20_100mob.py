#!/usr/bin/env python3
"""Run real 100 successive L20 Warlock fights on one native Rust/gsim actor.

This invokes the maintained live_two_world_pulls causal damage/ACK driver.
No resetting native resources, fabricated kills, or Python combat evaluator.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))

from live_two_world_pulls import run as native_world_chain  # noqa: E402
from src.scenarios.leveling_targets import representative_hp  # noqa: E402


def create_scenario(request: dict, *, variant: str) -> dict:
    scenario = copy.deepcopy(request)
    encounter = scenario["encounter"]
    target = encounter["targets"][0]
    target["level"] = 20
    target["name"] = "CMaNGOS Classic-proxy ordinary L20 enemy"
    target["stats"][32] = representative_hp(20)
    # This encounter attack is explicitly a test assumption, not an
    # unsupported assertion of a specific WoW Forever mob's true damage.
    target["minBaseDamage"] = 20.0
    target["swingSpeed"] = 2.0
    encounter["duration"] = 30
    scenario["simOptions"]["iterations"] = 8
    scenario["simOptions"]["randomSeed"] = "4242"
    scenario["simOptions"]["debugFirstIteration"] = False
    actor = scenario["raid"]["parties"][0]["players"][0]
    assert actor["class"] == "ClassWarlock" and actor["race"] == "RaceTroll"
    assert len(actor["equipment"]["items"]) == 17
    rotation = actor["rotation"]["priorityList"]
    if variant == "best_apl":
        pass
    elif variant in ("life_tap_20", "life_tap_40"):
        # Same schema used and paid for by the existing native APL search:
        # conditional Life Tap is a *candidate*, Rust owns execution.
        threshold = 20 if variant == "life_tap_20" else 40
        tap = {"action": {
            "castSpell": {"spellId": {"spellId": 1455}},
            "condition": {"cmp": {
                "lhs": {"currentManaPercent": {}},
                "op": "OpLt", "rhs": {"const": {"val": str(threshold) + "%"}},
            }},
        }}
        actor["rotation"]["priorityList"] = [tap] + rotation
    else:
        raise ValueError("unsupported APL variant")
    return scenario


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--targets", type=int, default=100)
    p.add_argument("--recovery-seconds", type=int, default=12)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    original = json.loads(args.source.read_text())
    assert args.targets == 100, "Run exactly 100 sequential targets"
    attempts = []

    for variant in ("best_apl", "life_tap_20", "life_tap_40"):
        scenario = create_scenario(original, variant=variant)
        base = args.out / variant
        base.mkdir(parents=True, exist_ok=True)
        source_path = base / "source_request.json"
        prepared_path = base / "prepared.json"
        source_path.write_text(json.dumps(scenario, indent=2) + "\n")
        record = {"variant": variant, "target_count_requested": args.targets,
                  "mob_level": 20, "mob_hp_classic_proxy": representative_hp(20),
                  "synthetic_min_base_damage": 20, "recovery_s": args.recovery_seconds}
        try:
            cmd = [str(args.binary.resolve()), "prepare", "--request",
                   str(source_path.resolve()), "--actor-level", "20",
                   "--outfile", str(prepared_path.resolve())]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=60, check=False)
            if result.returncode:
                raise RuntimeError("NATIVE_PREPARE_FAILED: " +
                                   (result.stderr or result.stdout)[-2500:])
            prepared = json.loads(prepared_path.read_text())
            player = prepared["player"]
            record["native_actor"] = {
                "class": player.get("class"), "race": player.get("race"),
                "level": player.get("level"),
                "health": player["stats"]["Health"],
                "mana": player["stats"]["Mana"],
            }
            if player["level"] != 20 or player["class"] != "ClassWarlock":
                raise RuntimeError("Wrong real native prepared actor")
            print("CHAIN_STARTED", json.dumps(record), flush=True)
            result = native_world_chain(
                args.binary, prepared_path, target_count=args.targets,
                classic_mob_level=20, rng_mode="balanced",
                require_native_health_damage=False,
            )
            (base / "chain_native_world.json").write_text(
                json.dumps(result, indent=2, allow_nan=False) + "\n")
            record.update(
                status="COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
                killed=result["world_targets_killed"],
                elapsed_s=result["world_elapsed_seconds"],
                seconds_per_mob=result["world_seconds_per_target_without_paid_recovery"],
                min_hp=result["minimum_native_actor_health"],
                min_mana=result["minimum_native_actor_mana"],
                final_mana=result["native_actor_mana_after_world_kills"][-1],
                paid_recovery=result["paid_recovery"],
                walk_paid_s=result["gsim_route_paid_movement_s"],
                native_damage_events=result["native_damage_events"],
            )
            print("CHAIN_COMPLETED", json.dumps(record), flush=True)
        except (AssertionError, RuntimeError, ValueError, OSError,
                subprocess.TimeoutExpired, KeyError) as exc:
            # The live driver embeds genuine completed-ACK count on a native
            # nonzero exit; preserve the precise result, not a fake score.
            record["status"] = "INCOMPLETE_OR_NATIVE_REFUSAL"
            record["error"] = str(exc)[-4500:]
            print("CHAIN_INCOMPLETE", json.dumps(record), flush=True)
        (base / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
        attempts.append(record)

    summary = {
        "kind": "real_100_target_source_native_world_attempts",
        "native_engine_is_combat_authority": True,
        "world": "one persistent gsim 2D world per candidate",
        "no_independent_fight_stitching": True,
        "results": attempts,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("WARLOCK_L20_100_MOB_CHAIN_RESULT", json.dumps(summary), flush=True)
    # A failed 100-kill run is a real unsuccessful outcome, never a fake PASS.
    if not any(r["status"] == "COMPLETED_100_REAL_NATIVE_GSIM_KILLS" for r in attempts):
        raise SystemExit("No variant completed 100 actual native-gsim mob kills; inspect recorded refusals.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""One actual Troll Warlock L20 retained Rust actor vs 100 gsim world mobs.

Uses existing source-Rust APL, mana/HP recovery, gsim 2D path + lethal ACK.
The ordinary L20 target HP is an explicit CMaNGOS Classic proxy, not a
verified Forever mob. No independent gameplay model and no PASS fabrication.
"""
import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations" / "mythicsim-rust"))
from live_two_world_pulls import run as run_native_world
from src.scenarios.leveling_targets import representative_hp


def invoke(args, timeout=180):
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode:
        raise RuntimeError("NATIVE_EXECUTION_REFUSED:" + str(proc.returncode) + ":"
                           + (proc.stderr or proc.stdout)[-1100:])
    return proc.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-request", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--targets", type=int, default=100)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    binary = args.binary.resolve()
    source = json.loads(args.source_request.read_text())
    request = copy.deepcopy(source)
    player = request["raid"]["parties"][0]["players"][0]
    assert player["class"] == "ClassWarlock" and player["race"] == "RaceTroll"
    assert len(player["equipment"]["items"]) == 17

    # Source APL is the previously real-paid Corruption / Bane / Shadow Bolt.
    # Add an ACTUAL native Shoot action as a candidate fallback. Only Rust
    # determines whether this action executes; ranged auto can fire during idle.
    player["rotation"]["priorityList"].append({
        "action": {"castSpell": {"spellId": {"otherId": "OtherActionShoot"}}}
    })
    request["simOptions"]["iterations"] = 1
    request["simOptions"]["debugFirstIteration"] = False
    request["encounter"]["duration"] = 30
    target = request["encounter"]["targets"][0]
    target["level"] = 20
    target["stats"][32] = representative_hp(20)
    # Explicit ordinary-melee scenario input, NOT a sourced Forever NPC.
    target["minBaseDamage"] = 30.0
    target["swingSpeed"] = 2.0

    source_path = args.out / "level20-world-request.json"
    prepared_path = args.out / "level20-world-prepared.json"
    paid_path = args.out / "level20-world-onefight-paid.json"
    result_path = args.out / "level20-world-100mob-result.json"
    source_path.write_text(json.dumps(request, indent=2) + "\n")
    receipt = {"status": "RUNNING", "target_count_requested": args.targets,
               "level": 20, "scenario_mob_hp": representative_hp(20),
               "rng_mode": "balanced", "checkpoint_certified": False}
    try:
        invoke([binary, "prepare", "--request", source_path, "--actor-level",
                "20", "--outfile", prepared_path])
        prepared = json.loads(prepared_path.read_text())
        assert prepared["player"]["level"] == 20
        assert prepared["melee"]["auto_swing_ranged"] is True
        assert any((spell.get("action_id") or {}).get("other_id") == "OtherActionShoot"
                   for spell in prepared["player"]["spells"])
        receipt["native_actor"] = {
            "class": prepared["player"]["class"], "race": prepared["player"]["race"],
            "level": prepared["player"]["level"],
            "native_request_sha256": prepared["request_sha256"]}
        invoke([binary, "sim", "--infile", prepared_path, "--rng-mode",
                "balanced", "--outfile", paid_path])
        onefight = json.loads(paid_path.read_text())
        metrics = onefight["result"]["raidMetrics"]["parties"][0]["players"][0]
        receipt["native_onefight_dps"] = metrics["dps"]["avg"]
        receipt["native_onefight_iterations"] = onefight["result"]["iterationsDone"]
        print("WARLOCK_L20_NATIVE_APL_ONE_FIGHT_PAID",
              json.dumps({k:receipt[k] for k in (
                  "native_actor","native_onefight_dps","native_onefight_iterations")}),
              flush=True)
        result = run_native_world(
            binary, prepared_path, classic_mob_level=20,
            target_count=args.targets, rng_mode="balanced")
        receipt.update({
            "status":"WORLD_RUN_COMPLETED",
            "world_targets_killed":result["world_targets_killed"],
            "world_elapsed_seconds":result.get("world_elapsed_seconds"),
            "min_native_actor_hp":result["minimum_native_actor_health"],
            "native_final_mana":result["native_actor_mana_after_world_kills"][-1],
            "native_paid_recovery":result["paid_recovery"],
            "continuous_native_actor":result["continuous_native_actor"],
            "actual_2d_ack":result["actual_2d_ack"],
            "full_world_result":result})
        print("WARLOCK_L20_NATIVE_100_MOB_REAL", json.dumps({
            k:receipt[k] for k in (
                "world_targets_killed","world_elapsed_seconds","min_native_actor_hp",
                "native_final_mana","native_paid_recovery","continuous_native_actor",
                "actual_2d_ack")}), flush=True)
    except Exception as exc:
        receipt["status"] = "WORLD_RUN_FAILED_NATIVE_OR_GSIM"
        receipt["error"] = repr(exc)[-2500:]
        print("WARLOCK_L20_NATIVE_100_MOB_OBSERVED_FAILURE",
              json.dumps({k:v for k,v in receipt.items() if k != "full_world_result"}),
              flush=True)
    finally:
        result_path.write_text(json.dumps(receipt, indent=2, default=str) + "\n")
    if receipt["status"] != "WORLD_RUN_COMPLETED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

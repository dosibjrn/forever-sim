#!/usr/bin/env python3
"""Run real 100 successive L20 Warlock fights on one native Rust/gsim actor.

This invokes the maintained live_two_world_pulls causal damage/ACK driver.
No resetting native resources, fabricated kills, or Python combat evaluator.
"""
from __future__ import annotations

import copy
import hashlib
import json
from math import isfinite
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))

from live_two_world_pulls import (  # noqa: E402
    NativeWorldChainFailure,
    run as native_world_chain,
)
from src.scenarios.leveling_targets import representative_hp  # noqa: E402


def file_sha256(path: Path) -> str:
    """Record actual source/binary bytes used by each native paid attempt."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guarded_life_tap_action(spell_id: int, *,
                            mana_percent: int, health_percent: int) -> dict:
    """Propose a native APL action, never a Python Life Tap implementation.

    Native evaluates mana AND health immediately before casting. Both
    thresholds are policy candidates, not invented Warcraft mechanics.
    """
    if (type(spell_id) is not int or spell_id <= 0
            or not 0 < mana_percent <= 100
            or not 0 < health_percent < 100):
        raise ValueError("INVALID_LIFE_TAP_APL_CANDIDATE")
    return {"action": {
        "castSpell": {"spellId": {"spellId": spell_id}},
        "condition": {"and": {"vals": [
            {"cmp": {
                "lhs": {"currentManaPercent": {}},
                "op": "OpLt",
                "rhs": {"const": {"val": f"{mana_percent}%"}},
            }},
            {"cmp": {
                "lhs": {"currentHealthPercent": {}},
                "op": "OpGt",
                "rhs": {"const": {"val": f"{health_percent}%"}},
            }},
        ]}},
    }}


def create_scenario(request: dict, *, variant: str) -> dict:
    scenario = copy.deepcopy(request)
    encounter = scenario["encounter"]
    target = encounter["targets"][0]
    target["level"] = 20
    # Preserve explicit source labels and hostile attack parameters when the
    # candidate supplies them. The legacy stationary source has no attack
    # fields, so only that caller receives proxy defaults. In particular a
    # paid changed-hostile request must reach native with its own swing/damage
    # values instead of being silently replaced by the old proxy scenario.
    target.setdefault("name", "CMaNGOS Classic-proxy ordinary L20 enemy")
    # A zero source-HP slot is the legacy ordinary-mob placeholder. When a
    # caller supplies actual target health, keep that hostile scenario intact
    # for the selected Rust prepare/world executor instead of silently
    # replacing it with the generic L20 proxy.
    if target["stats"][32] == 0:
        target["stats"][32] = representative_hp(20)
    # Defaults are scenario assumptions, not facts about WoW Forever mobs.
    target.setdefault("minBaseDamage", 20.0)
    target.setdefault("swingSpeed", 2.0)
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
        # A Life Tap candidate must not repeatedly exchange the last HP
        # for mana. The native APL engine evaluates both resources before
        # every cast; this is a search policy, not a Python combat rule.
        threshold = 20 if variant == "life_tap_20" else 40
        tap = guarded_life_tap_action(
            1455, mana_percent=threshold, health_percent=50)
        actor["rotation"]["priorityList"] = [tap] + rotation
    else:
        raise ValueError("unsupported APL variant")
    return scenario


def native_failure_receipt(exc: BaseException) -> dict:
    """Preserve actual ACKed kills from the native-world driver refusal.

    The Rust/gsim boundary raises this structured tuple *after* the native
    process exits nonzero. Never parse counts from arbitrary error text.
    """
    if not isinstance(exc, AssertionError) or not exc.args:
        return {}
    row = exc.args[0]
    if (not isinstance(row, tuple) or len(row) != 5
            or row[0] != "RUST_TWO_WORLD_NATIVE_FAILED"
            or type(row[1]) is not int or row[1] == 0
            or type(row[3]) is not int or row[3] < 0
            or type(row[4]) is not int or row[4] < 0):
        return {}
    return {
        "native_exit_code": row[1],
        "native_world_ack_kills_before_refusal": row[3],
        "native_damage_events_before_refusal": row[4],
    }


def native_actor_receipt_complete(result: dict, requested_targets: int) -> bool:
    """Require the full per-kill retained-actor trace before scoring a chain.

    This verifies only the native transport shape, not Warcraft combat rules:
    Rust is authoritative for survival, resource changes and kill semantics.
    An ACK count without the corresponding actor state is not a comparable
    100-mob objective receipt.
    """
    windows = result.get("native_windows")
    mana = result.get("native_actor_mana_after_world_kills")
    return (
        isinstance(windows, list) and len(windows) == requested_targets
        and all(isinstance(window, dict)
                and type(window.get("actor_health")) in (int, float)
                and isfinite(window["actor_health"]) for window in windows)
        and isinstance(mana, list) and len(mana) == requested_targets
        and all(type(value) in (int, float) and isfinite(value)
                for value in mana)
    )


def classify_native_chain(result: dict, requested_targets: int, *,
                          recovery_policy: str,
                          expected_world_hp: float,
                          require_native_consumption: bool = False,
                          require_native_health_damage: bool = False) -> tuple[str, bool]:
    """Score only native-reported paid 2D kills, never a policy fallback.

    For an explicit eight-target Decisions proof, demand source-reported
    charged food/water time AND a positive matching native resource gain.
    Normal routes may legitimately need no consumable at some encounters.
    """
    killed = result.get("world_targets_killed")
    seconds_per_mob = result.get("world_seconds_per_target_paid_recovery")
    paid = result.get("paid_recovery") is True
    # On Decisions, native no-rest gaps are valid if the complete native
    # recovery/food/water clock is accounted. Fixed must still pay every gap.
    accounted = (result.get("native_recovery_clock_accounted") is True
                 if recovery_policy == "decisions" else paid)
    if (killed != requested_targets or not accounted
            or type(seconds_per_mob) not in (float, int)
            or not isfinite(seconds_per_mob) or seconds_per_mob <= 0):
        return "INCOMPLETE_UNPAID_NATIVE_RECOVERY", False
    # The 2D world is Forever-owned. A native/ACK chain measured against a
    # different world target HP cannot score this requested hostile scenario.
    # This is request/result forwarding integrity, not a second game rule.
    actual_world_hp = result.get("world_target_hp")
    if (type(actual_world_hp) not in (int, float)
            or not isfinite(actual_world_hp)
            or actual_world_hp != expected_world_hp):
        return "NATIVE_WORLD_TARGET_HEALTH_MISMATCH", False
    if recovery_policy == "decisions":
        if (result.get("native_recovery_mode") != "decisions_food_water"
                or result.get("native_food_water_observed") is not True):
            return "INCOMPLETE_NATIVE_DECISIONS_RECEIPT", False
        values = tuple(result.get(key) for key in (
            "native_food_seconds_total", "native_water_seconds_total",
            "native_food_health_gain_total", "native_water_mana_gain_total"))
        if any(type(value) not in (int, float) or not isfinite(value)
               or value < 0 for value in values):
            return "INCOMPLETE_NATIVE_DECISIONS_RECEIPT", False
        food_seconds, water_seconds, health_gain, mana_gain = values
        if require_native_consumption and not (
                (food_seconds > 0 and health_gain > 0)
                or (water_seconds > 0 and mana_gain > 0)):
            return "NO_NATIVE_FOOD_WATER_RESOURCE_GAIN", False
    elif recovery_policy != "fixed":
        raise ValueError("UNKNOWN_NATIVE_RECOVERY_POLICY")
    if require_native_health_damage:
        # The native/gsim bridge reports damage from the Rust actor, never
        # from the synthetic 2D player or target attack assumptions.
        damage = result.get("native_health_damage")
        if (not isinstance(damage, dict) or damage.get("observed") is not True
                or type(damage.get("damage_taken")) not in (float, int)
                or not isfinite(damage["damage_taken"])
                or damage["damage_taken"] < 0
                or type(damage.get("damage_events")) is not int
                or damage["damage_events"] < 0
                or (damage["damage_taken"] > 0) != (damage["damage_events"] > 0)):
            return "INCOMPLETE_NATIVE_HEALTH_DAMAGE_RECEIPT", False
        if damage["damage_events"] == 0:
            # Explicitly observed zero is a real native outcome, not a missing
            # receipt. Keep the strict survival proof failed without discarding
            # already ACKed paid Decisions/consumption evidence.
            return "NO_NATIVE_INCOMING_PLAYER_DAMAGE", False
    return f"COMPLETED_{requested_targets}_REAL_NATIVE_GSIM_KILLS", True


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--targets", type=int, choices=(2, 8, 100), default=100)
    p.add_argument("--variant", choices=("all", "best_apl", "life_tap_20",
                                         "life_tap_40"), default="all")
    p.add_argument("--recovery-policy", choices=("fixed", "decisions"),
                   default="fixed")
    p.add_argument("--recovery-seconds", type=int)
    p.add_argument("--health-threshold", type=float, default=0.5)
    p.add_argument("--mana-threshold", type=float, default=0.1)
    p.add_argument("--require-native-health-damage", action="store_true",
                   help="Require real positive incoming damage to the Rust actor "
                        "on the same retained native/2D world chain")
    p.add_argument("--require-native-consumption", action="store_true",
                   help="Eight-target Decisions smoke: native paid food/water "
                        "with a positive HP or mana gain")
    args = p.parse_args()
    if args.recovery_policy == "decisions" and args.recovery_seconds is not None:
        p.error("--recovery-seconds cannot be combined with Decisions recovery")
    if args.require_native_consumption and (
            args.recovery_policy != "decisions" or args.targets != 8):
        p.error("--require-native-consumption requires eight Decisions targets")
    native_recovery = (
        {"recovery_policy": "fixed",
         "recovery_seconds": (12 if args.recovery_seconds is None
                              else args.recovery_seconds)}
        if args.recovery_policy == "fixed"
        else {"recovery_policy": "decisions",
              "health_threshold": args.health_threshold,
              "mana_threshold": args.mana_threshold}
    )
    args.out.mkdir(parents=True, exist_ok=True)
    original = json.loads(args.source.read_text())
    binary_sha256 = file_sha256(args.binary)
    original_source_sha256 = file_sha256(args.source)
    attempts = []
    variants = (("best_apl", "life_tap_20", "life_tap_40")
                if args.variant == "all" else (args.variant,))

    for variant in variants:
        scenario = create_scenario(original, variant=variant)
        base = args.out / variant
        base.mkdir(parents=True, exist_ok=True)
        source_path = base / "source_request.json"
        prepared_path = base / "prepared.json"
        source_path.write_text(json.dumps(scenario, indent=2) + "\n")
        source_health = original["encounter"]["targets"][0]["stats"][32]
        chosen_target = scenario["encounter"]["targets"][0]
        record = {"variant": variant, "target_count_requested": args.targets,
                  "native_binary_sha256": binary_sha256,
                  "original_source_sha256": original_source_sha256,
                  "source_request_sha256": file_sha256(source_path),
                  "mob_level": 20,
                  "mob_hp_classic_proxy": (representative_hp(20)
                                           if source_health == 0 else None),
                  "mob_hp_native_scenario": chosen_target["stats"][32],
                  "scenario_min_base_damage": chosen_target["minBaseDamage"],
                  "scenario_swing_speed": chosen_target["swingSpeed"],
                  "scenario_target_name": chosen_target["name"],
                  "recovery_request": native_recovery,
                  "native_2d_paid_objective_eligible": False,
                  "native_health_damage_proof_required": args.require_native_health_damage}
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
            record["native_prepared_sha256"] = file_sha256(prepared_path)
            record["native_prepared_request_sha256"] = prepared.get("request_sha256")
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
                # World target HP must match the explicit source scenario used
                # in native prepare, not silently revert to the L20 proxy.
                # Keep the original sourced Classic proxy on zero-HP fixtures.
                mob_health=(chosen_target["stats"][32]
                            if source_health != 0 else None),
                classic_mob_level=(20 if source_health == 0 else None),
                rng_mode="balanced",
                # Collect the native health receipt even when damage is zero.
                # The strict positive-damage criterion is applied below by
                # classify_native_chain to preserve real ACK/recovery evidence
                # from an unsuccessful survival proof. No false completion.
                require_native_health_damage=False,
                **native_recovery,
            )
            # An incomplete native actor trace must still produce a durable
            # refusal summary. Non-finite native data cannot be written as
            # standard JSON; retain the structured refusal instead of
            # crashing before the 100-target attempt is classified.
            try:
                native_json = json.dumps(result, indent=2, allow_nan=False)
            except (TypeError, ValueError):
                native_json = None
            if native_json is not None:
                (base / "chain_native_world.json").write_text(native_json + "\n")
            killed = result["world_targets_killed"]
            paid = result.get("paid_recovery") is True
            seconds_per_mob = result.get("world_seconds_per_target_paid_recovery")
            status, complete = classify_native_chain(
                result, args.targets, recovery_policy=args.recovery_policy,
                expected_world_hp=chosen_target["stats"][32],
                require_native_consumption=args.require_native_consumption,
                require_native_health_damage=args.require_native_health_damage)
            actor_receipt_complete = native_actor_receipt_complete(
                result, args.targets)
            if complete and not actor_receipt_complete:
                status, complete = "INCOMPLETE_NATIVE_ACTOR_CONTINUITY_RECEIPT", False
            if complete and native_json is None:
                status, complete = "INCOMPLETE_NONFINITE_NATIVE_RECEIPT", False
            # Independent transport proofs: a native health-damage refusal
            # must not erase genuine paid food/water evidence, or vice versa.
            # Neither individual proof grants an accepted chain objective.
            # Observed native proofs are independent of whether this run
            # *requires* them for acceptance. The latter only controls the
            # combined status above. Reuse actual paid observations when
            # ranking subsequent 100-mob/native optimizer candidates.
            _, consumption_complete = classify_native_chain(
                result, args.targets, recovery_policy=args.recovery_policy,
                expected_world_hp=chosen_target["stats"][32],
                require_native_consumption=True)
            _, health_complete = classify_native_chain(
                result, args.targets, recovery_policy=args.recovery_policy,
                expected_world_hp=chosen_target["stats"][32],
                require_native_health_damage=True)
            record.update(
                status=status,
                killed=killed,
                world_target_hp_observed=(result.get("world_target_hp")
                    if type(result.get("world_target_hp")) in (int, float)
                    and isfinite(result["world_target_hp"]) else None),
                world_target_hp_matches_request=(
                    result.get("world_target_hp") == chosen_target["stats"][32]),
                elapsed_s=result["world_elapsed_seconds"],
                seconds_per_mob=(seconds_per_mob if complete else None),
                min_hp=result["minimum_native_actor_health"],
                min_mana=result["minimum_native_actor_mana"],
                final_hp=(result["native_windows"][-1]["actor_health"]
                          if actor_receipt_complete else None),
                final_mana=(result["native_actor_mana_after_world_kills"][-1]
                            if actor_receipt_complete else None),
                native_actor_continuity_receipt_complete=actor_receipt_complete,
                native_actor_health_windows_recorded=len(
                    result.get("native_windows", [])),
                native_actor_mana_windows_recorded=len(
                    result.get("native_actor_mana_after_world_kills", [])),
                paid_recovery=paid,
                native_recovery_clock_accounted=result.get(
                    "native_recovery_clock_accounted"),
                native_recovery_mode=result.get("native_recovery_mode"),
                native_recovery_seconds=result.get(
                    "native_passive_recovery_elapsed_seconds"),
                native_recovery_ns_by_target=result.get(
                    "native_passive_recovery_ns_by_target"),
                native_recovery_ticks_by_target=result.get(
                    "native_passive_recovery_ticks_by_target"),
                native_food_water_observed=result.get("native_food_water_observed"),
                native_food_seconds=result.get("native_food_seconds_total"),
                native_water_seconds=result.get("native_water_seconds_total"),
                native_food_health_gain=result.get("native_food_health_gain_total"),
                native_water_mana_gain=result.get("native_water_mana_gain_total"),
                native_consumption_proof_required=args.require_native_consumption,
                native_consumption_proven=(actor_receipt_complete
                                           and consumption_complete
                                           and args.recovery_policy == "decisions"),
                native_health_damage=result.get("native_health_damage"),
                # Transport the existing source-native per-mob attack receipt.
                # A world damage-to-target event is not incoming player damage.
                # This identifies zero/missing *individual* windows for the
                # Rust owner without inventing Python attack mechanics.
                native_incoming_player_damage_by_target=[
                    {"index": window.get("index"),
                     "native_kill_ns": window.get("native_kill_ns"),
                     "damage_taken": window.get("native_health_damage_taken"),
                     "damage_events": window.get("native_health_damage_events")}
                    for window in result["native_windows"]
                ],
                native_health_damage_proven=(actor_receipt_complete
                                            and health_complete),
                walk_paid_s=result["gsim_route_paid_movement_s"],
                native_damage_events=result["native_damage_events"],
                # Frozen-build screen only: never promote it to cold-search
                # P4/P5/P6 acceptance, even after 100 paid kills.
                native_2d_paid_objective_eligible=complete and args.targets == 100,
            )
            print("CHAIN_COMPLETED" if complete else "CHAIN_INCOMPLETE",
                  json.dumps(record), flush=True)
        except (AssertionError, RuntimeError, ValueError, OSError,
                subprocess.TimeoutExpired, KeyError, IndexError, TypeError) as exc:
            # The live driver embeds genuine completed-ACK count on a native
            # nonzero exit; preserve the precise result, not a fake score.
            record["status"] = "INCOMPLETE_OR_NATIVE_REFUSAL"
            record["error"] = str(exc)[-4500:]
            if isinstance(exc, NativeWorldChainFailure):
                # Only actual acknowledged 2D kills; never score a partial
                # native chain as completed or interpolate its remaining time.
                record["killed"] = exc.killed
                record["native_damage_events"] = exc.native_damage_events
                record["native_exit_code"] = exc.exit_code
            record.update(native_failure_receipt(exc))
            print("CHAIN_INCOMPLETE", json.dumps(record), flush=True)
        (base / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
        attempts.append(record)

    summary = {
        "kind": ("real_100_target_source_native_world_attempts"
                 if args.targets == 100 else
                 "two_target_native_world_screen" if args.targets == 2
                 else "eight_target_native_world_smoke"),
        "native_engine_is_combat_authority": True,
        "world": "one persistent gsim 2D world per candidate",
        "no_independent_fight_stitching": True,
        "target_count_requested": args.targets,
        "native_binary_sha256": binary_sha256,
        "original_source_sha256": original_source_sha256,
        "native_recovery_requested": native_recovery,
        "native_consumption_proof_required": args.require_native_consumption,
        "native_health_damage_proof_required": args.require_native_health_damage,
        "cold_30_300_search_executed": False,
        "p4_p5_p6_pass": False,
        "results": attempts,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("WARLOCK_L20_100_MOB_CHAIN_RESULT", json.dumps(summary), flush=True)
    # A failed 100-kill run is a real unsuccessful outcome, never a fake PASS.
    expected = f"COMPLETED_{args.targets}_REAL_NATIVE_GSIM_KILLS"
    if not any(r["status"] == expected for r in attempts):
        raise SystemExit(
            f"No variant completed {args.targets} retained native/2D kills "
            "with paid recovery; inspect recorded refusals.")


if __name__ == "__main__":
    main()

"""Feral L60 source-build -> native Rust -> persistent gsim world smoke.

The actor, equipment, talents and APL come unchanged from the supplied
MythicSim request. Only the *scenario-owned* ordinary L60 target is changed:
the Classic-proxy HP and an explicit incoming-damage test parameter are not
claims about a particular Forever NPC. Native Rust decides whether the build
can execute. A 2-target smoke is not P4/P5/P6 acceptance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
# Direct `python tools/...` execution puts tools/, not the repo root, on sys.path.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scenarios.leveling_targets import representative_hp
FERAL_SOURCE = ROOT / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json"


def run_feral_l60_world(binary: str | Path, source_request: str | Path = FERAL_SOURCE,
                        *, target_count: int = 2,
                        scenario_min_base_damage: float = 100.,
                        recovery_seconds: int | None = None,
                        world_run=None, prepare_run=None) -> dict:
    """Execute consecutive world kills on one prepared Feral actor.

    The native world runner owns actor continuity, causal ACKs, movement,
    health/resource changes and paid recovery. This wrapper cannot grant
    a gate PASS or turn a partial native refusal into a completed screen.
    """
    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("FERAL_L60_WORLD_TARGET_COUNT_INVALID")
    if (type(scenario_min_base_damage) not in (int, float)
            or not math.isfinite(scenario_min_base_damage)
            or scenario_min_base_damage < 0):
        raise ValueError("FERAL_L60_WORLD_SCENARIO_DAMAGE_INVALID")
    if recovery_seconds is not None and (
            type(recovery_seconds) is not int
            or not 1 <= recovery_seconds <= 120):
        raise ValueError("FERAL_L60_WORLD_RECOVERY_SECONDS_INVALID")
    path = Path(source_request).resolve()
    raw = path.read_bytes()
    request = json.loads(raw)
    try:
        players = request["raid"]["parties"][0]["players"]
        targets = request["encounter"]["targets"]
        player = players[0]
        target = targets[0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("FERAL_L60_SOURCE_REQUEST_INCOMPLETE") from exc
    if (len(players) != 1 or len(targets) != 1
            or not isinstance(player, dict)
            or player.get("class") != "ClassDruid"
            or not isinstance(target, dict)
            or not isinstance(target.get("stats"), list)
            or len(target["stats"]) <= 32):
        raise ValueError("FERAL_L60_SOURCE_ACTOR_OR_TARGET_INVALID")

    # The saved Feral source omits player.level; native prepare, not a Python\n    # source-level check, determines the actual level-60 actor.\n    # Explicit scenario transformation, not a new Warcraft legality model:
    # leave the Feral source actor/build/APL byte-for-byte equivalent.
    leveling = copy.deepcopy(request)
    mob = leveling["encounter"]["targets"][0]
    mob["level"] = 60
    mob["stats"][32] = representative_hp(60)
    mob["minBaseDamage"] = float(scenario_min_base_damage)
    if world_run is None:
        integration = ROOT / "integrations/mythicsim-rust"
        if str(integration) not in sys.path:
            sys.path.insert(0, str(integration))
        from live_two_world_pulls import run as world_run
    prepare_run = prepare_run or subprocess.run
    binary = Path(binary).resolve()
    with TemporaryDirectory(prefix="feral-l60-native-world-") as folder:
        request_path = Path(folder) / "leveling-request.json"
        prepared_path = Path(folder) / "prepared.json"
        request_path.write_text(json.dumps(leveling, sort_keys=True),
                                encoding="utf-8")
        # This pinned Feral source uses native Go-reference rules; never
        # reinterpret its talent ranks in Python.
        try:
            prepare_run(
                [str(binary), "prepare", "--request", str(request_path),
                 "--outfile", str(prepared_path), "--go-rules"],
                check=True, capture_output=True, text=True, timeout=25)
        except subprocess.CalledProcessError as exc:
            # Native Rust is authoritative: retain its *actual* refusal,
            # not a Python-inferred legality reason or opaque exit code.
            detail = str(exc.stderr or exc.stdout or "")[-800:]
            raise RuntimeError(
                f"FERAL_L60_NATIVE_PREPARE_REFUSED:exit={exc.returncode}:{detail}"
            ) from exc
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        native_player = prepared.get("player")
        native_sha = prepared.get("request_sha256")
        if (not isinstance(native_player, dict)
                or native_player.get("class") != "ClassDruid"
                or native_player.get("level") != 60
                or not isinstance(native_sha, str)
                or len(native_sha) != 64):
            raise RuntimeError("FERAL_L60_NATIVE_PREPARED_ACTOR_INVALID")
        world_kwargs = {
            "classic_mob_level": 60,
            "target_count": target_count,
            "rng_mode": "balanced",
            "require_native_moving": True,
        }
        if recovery_seconds is not None:
            world_kwargs["native_recovery_seconds"] = recovery_seconds
        proof = world_run(binary, prepared_path, **world_kwargs)
    if (not isinstance(proof, dict)
            or proof.get("continuous_native_actor") is not True
            or proof.get("actual_2d_ack") is not True
            or proof.get("world_targets_killed") != target_count
            or len(proof.get("world_kills", ())) != target_count
            or len(proof.get("native_windows", ())) != target_count
            or type(proof.get("paid_recovery")) is not bool
            or len({k.get("target_id") for k in proof["world_kills"]})
               != target_count):
        raise RuntimeError("FERAL_L60_NATIVE_WORLD_RECEIPT_INCOMPLETE")

    # P4–P6 score elapsed time, not single-target DPS. Only expose a
    # comparable 100-mob objective after native/world has really completed
    # all kills, paid inter-pull recovery and executed the 99 spatial legs.
    # This does NOT certify P4/P5/P6: the cold 30s/300s search is separate.
    objective_100 = None
    if target_count == 100:
        elapsed = proof.get("world_elapsed_seconds")
        movement = proof.get("gsim_route_paid_movement_s")
        recovery_ns = proof.get("native_passive_recovery_ns_by_target")
        legs = proof.get("gsim_route_paid_receipts")
        min_health = proof.get("minimum_native_actor_health")
        # On a genuine 100-target native/world completion, preserve the
        # precise missing *receipt*, not a guessed engine failure. This
        # diagnostic is bounded and contains no untrusted Warcraft rules.
        missing = []
        if proof.get("paid_recovery") is not True:
            missing.append("native_paid_recovery_flag")
        if proof.get("native_passive_recovery_observed") is not True:
            missing.append("native_passive_recovery_unobserved")
        if (type(elapsed) not in (int, float)
                or not math.isfinite(elapsed) or elapsed <= 0):
            missing.append("world_elapsed_seconds")
        if (type(movement) not in (int, float)
                or not math.isfinite(movement) or movement <= 0):
            missing.append("world_paid_movement")
        if not isinstance(legs, list) or len(legs) != 99:
            missing.append("world_route_legs")
        if (not isinstance(recovery_ns, list)
                or len(recovery_ns) != 100
                or any(type(ns) is not int or ns < 0 for ns in recovery_ns)):
            missing.append("native_recovery_windows")
        elif not any(ns > 0 for ns in recovery_ns[1:]):
            missing.append("native_recovery_never_paid")
        if (type(min_health) not in (int, float)
                or not math.isfinite(min_health) or min_health <= 0):
            missing.append("native_actor_survival")
        if missing:
            raise RuntimeError(
                "FERAL_L60_100_MOB_PAID_OBJECTIVE_INCOMPLETE:"
                + ",".join(missing)
                + ":world_elapsed=" + str(elapsed)
                + ":world_movement=" + str(movement)
                + ":native_recovery_positive_gaps="
                + str(sum(ns > 0 for ns in recovery_ns[1:])
                      if isinstance(recovery_ns, list) else "unknown"))
        objective_100 = {
            "targets": 100,
            "mean_seconds_per_mob": float(elapsed) / 100,
            "total_elapsed_seconds": float(elapsed),
            "paid_world_movement_seconds": float(movement),
            "native_passive_recovery_seconds": sum(recovery_ns) / 1e9,
            "minimum_native_actor_health": float(min_health),
        }
    return {
        "source_request_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "native_prepared_request_sha256": native_sha,
        "source_actor": "ClassDruid:60",
        "world_target_scenario": "Classic-proxy-L60",
        "world_target_hp": representative_hp(60),
        "scenario_min_base_damage": float(scenario_min_base_damage),
        "requested_native_recovery_seconds": recovery_seconds,
        "native_world": proof,
        "objective_100_mobs": objective_100,
        "p4_p5_p6_certified": False,
    }



def search_feral_native_recovery(binary: str | Path,
                                 source_request: str | Path = FERAL_SOURCE,
                                 *, recovery_candidates: tuple[int, ...],
                                 world_run=None, prepare_run=None) -> dict:
    """Compare genuinely paid source-native 100-mob rest candidates.

    A candidate that kills its retained native player is rejected, not scored.
    The first lethal index and actual adjacent Rust receipts stay visible in
    the rejection. This is a bounded one-axis producer probe, NOT the eventual
    cold gear/talent/APL 30s/300s P4-P6 optimizer or a gate certificate.
    """
    if (not isinstance(recovery_candidates, tuple)
            or not 1 <= len(recovery_candidates) <= 4
            or any(type(seconds) is not int or not 1 <= seconds <= 120
                   for seconds in recovery_candidates)
            or len(set(recovery_candidates)) != len(recovery_candidates)):
        raise ValueError("FERAL_L60_RECOVERY_CANDIDATES_INVALID")
    attempts = []
    fastest = None
    for seconds in recovery_candidates:
        try:
            result = run_feral_l60_world(
                binary, source_request, target_count=100,
                recovery_seconds=seconds, world_run=world_run,
                prepare_run=prepare_run)
        except AssertionError as exc:
            # Only the actual selected-native survival refusal is a rejected
            # search candidate. Propagate all other clock/ACK/transport errors.
            detail = str(exc)
            prefix = "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index="
            if not detail.startswith(prefix):
                raise
            index = detail[len(prefix):].split(":", 1)[0]
            if not index.isdecimal() or not 0 <= int(index) < 100:
                raise
            attempts.append({
                "recovery_seconds": seconds, "native_survived": False,
                "first_native_death_index": int(index),
                "native_failure": detail,
            })
            continue
        objective = result["objective_100_mobs"]
        if objective is None:
            raise AssertionError("FERAL_L60_SURVIVAL_SEARCH_NO_PAID_OBJECTIVE")
        attempt = {
            "recovery_seconds": seconds, "native_survived": True,
            "mean_seconds_per_mob": objective["mean_seconds_per_mob"],
            "minimum_native_actor_health": objective["minimum_native_actor_health"],
        }
        attempts.append(attempt)
        if (fastest is None
                or attempt["mean_seconds_per_mob"] < fastest["mean_seconds_per_mob"]):
            fastest = attempt
    if fastest is None:
        raise RuntimeError(
            "FERAL_L60_NO_SURVIVING_NATIVE_RECOVERY_CANDIDATE:"
            + json.dumps(attempts, sort_keys=True))
    return {
        "best_surviving_candidate": fastest,
        "paid_native_attempts": attempts,
        "p4_p5_p6_certified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source-request", type=Path, default=FERAL_SOURCE)
    parser.add_argument("--targets", type=int, choices=(2, 100), default=2)
    rest = parser.add_mutually_exclusive_group()
    rest.add_argument("--recovery-seconds", type=int, default=None,
                      help="native-paid between-pull recovery 1..120s (default selected engine)")
    rest.add_argument("--recovery-candidates", type=str, default=None,
                      help="comma-separated 1..4 genuine native-paid rest choices for 100-mob selection")
    args = parser.parse_args()
    if args.recovery_candidates is not None:
        if args.targets != 100:
            parser.error("--recovery-candidates requires --targets 100")
        try:
            candidates = tuple(int(piece) for piece in args.recovery_candidates.split(","))
        except ValueError:
            parser.error("--recovery-candidates must contain only integer seconds")
        result = search_feral_native_recovery(
            args.binary, args.source_request, recovery_candidates=candidates)
        print(json.dumps(result, sort_keys=True))
        return
    result = run_feral_l60_world(
        args.binary, args.source_request, target_count=args.targets,
        recovery_seconds=args.recovery_seconds)
    proof = result["native_world"]
    print(json.dumps({
        "source_request_raw_sha256": result["source_request_raw_sha256"],
        "native_prepared_request_sha256": result["native_prepared_request_sha256"],
        "world_target_scenario": result["world_target_scenario"],
        "world_targets_killed": proof["world_targets_killed"],
        "continuous_native_actor": proof["continuous_native_actor"],
        "actual_2d_ack": proof["actual_2d_ack"],
        "paid_recovery": proof["paid_recovery"],
        "requested_native_recovery_seconds": result["requested_native_recovery_seconds"],
        "world_elapsed_seconds": proof.get("world_elapsed_seconds"),
        "objective_100_mobs": result["objective_100_mobs"],
        "p4_p5_p6_certified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

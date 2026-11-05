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

from src.scenarios.leveling_targets import representative_hp

ROOT = Path(__file__).resolve().parents[1]
FERAL_SOURCE = ROOT / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json"


def run_feral_l60_world(binary: str | Path, source_request: str | Path = FERAL_SOURCE,
                        *, target_count: int = 2,
                        scenario_min_base_damage: float = 100.,
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
            or type(player.get("level")) is not int or player["level"] != 60
            or not isinstance(target, dict)
            or not isinstance(target.get("stats"), list)
            or len(target["stats"]) <= 32):
        raise ValueError("FERAL_L60_SOURCE_ACTOR_OR_TARGET_INVALID")

    # Explicit scenario transformation, not a new Warcraft legality model:
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
        prepare_run(
            [str(binary), "prepare", "--request", str(request_path),
             "--outfile", str(prepared_path)],
            check=True, capture_output=True, text=True, timeout=25)
        prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
        native_player = prepared.get("player")
        native_sha = prepared.get("request_sha256")
        if (not isinstance(native_player, dict)
                or native_player.get("class") != "ClassDruid"
                or native_player.get("level") != 60
                or not isinstance(native_sha, str)
                or len(native_sha) != 64):
            raise RuntimeError("FERAL_L60_NATIVE_PREPARED_ACTOR_INVALID")
        proof = world_run(
            binary, prepared_path, classic_mob_level=60,
            target_count=target_count, rng_mode="balanced",
            require_native_moving=True)
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
    return {
        "source_request_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "native_prepared_request_sha256": native_sha,
        "source_actor": "ClassDruid:60",
        "world_target_scenario": "Classic-proxy-L60",
        "world_target_hp": representative_hp(60),
        "scenario_min_base_damage": float(scenario_min_base_damage),
        "native_world": proof,
        "p4_p5_p6_certified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source-request", type=Path, default=FERAL_SOURCE)
    parser.add_argument("--targets", type=int, choices=(2, 100), default=2)
    args = parser.parse_args()
    result = run_feral_l60_world(
        args.binary, args.source_request, target_count=args.targets)
    proof = result["native_world"]
    print(json.dumps({
        "source_request_raw_sha256": result["source_request_raw_sha256"],
        "native_prepared_request_sha256": result["native_prepared_request_sha256"],
        "world_target_scenario": result["world_target_scenario"],
        "world_targets_killed": proof["world_targets_killed"],
        "continuous_native_actor": proof["continuous_native_actor"],
        "actual_2d_ack": proof["actual_2d_ack"],
        "paid_recovery": proof["paid_recovery"],
        "world_elapsed_seconds": proof.get("world_elapsed_seconds"),
        "p4_p5_p6_certified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

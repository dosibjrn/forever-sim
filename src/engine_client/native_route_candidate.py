"""Native prepare/score/2D-world seam for route candidate evaluation.

The caller supplies a complete candidate RaidSimRequest. This adapter performs
no GameIR lookup, talent/spell legality inference, or Python combat scoring:
MythicSim prepare and sim are authoritative. A separate 2D world execution
uses one retained native actor across the requested targets.

This is an atomic candidate scorer, not yet a cross-level route executor.
The selected engine's current request contract is level-60-only.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_ROOT = _REPO_ROOT / "integrations" / "mythicsim-rust" / "engine"
_NATIVE_INTEGRATION = _REPO_ROOT / "integrations" / "mythicsim-rust"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_NATIVE_INTEGRATION) not in sys.path:
    sys.path.insert(0, str(_NATIVE_INTEGRATION))

from .native_candidate_client import (  # noqa: E402
    NativeRngMode,
    _request_player,
    _simulate_prepared,
    prepare_native_request,
)


def _run_world_bridge(
    binary: Path,
    prepared_path: Path,
    *,
    mob_health: float,
    target_count: int,
) -> dict[str, Any]:
    # Import lazily: unit tests for request/response forwarding do not need
    # the gsim world stack or its optional source-data dependencies.
    import live_two_world_pulls

    return live_two_world_pulls.run(
        binary,
        prepared_path,
        mob_health=mob_health,
        target_count=target_count,
    )


def _validate_world_receipt(world: dict[str, Any], target_count: int) -> dict[str, Any]:
    if not isinstance(world, dict):
        raise ValueError("NATIVE_ROUTE_WORLD_REPORT_NOT_OBJECT")
    if world.get("world_targets_killed") != target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_TARGET_COUNT_MISMATCH")
    if world.get("continuous_native_actor") is not True:
        raise ValueError("NATIVE_ROUTE_WORLD_ACTOR_NOT_CONTINUOUS")
    if world.get("actual_2d_ack") is not True:
        raise ValueError("NATIVE_ROUTE_WORLD_2D_ACK_MISSING")
    if world.get("checkpoint_certified") is not False:
        raise ValueError("NATIVE_ROUTE_WORLD_MUST_NOT_CERTIFY_CHECKPOINT")
    if world.get("paid_recovery") is not False:
        raise ValueError("NATIVE_ROUTE_WORLD_PAID_RECOVERY_SCOPE_MISMATCH")
    if not isinstance(world.get("world_target_provenance"), dict):
        raise ValueError("NATIVE_ROUTE_WORLD_TARGET_PROVENANCE_MISSING")

    windows = world.get("native_windows")
    kills = world.get("world_kills")
    if not isinstance(windows, list) or len(windows) != target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_NATIVE_WINDOW_COUNT_MISMATCH")
    if not isinstance(kills, list) or len(kills) != target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_ACK_KILL_COUNT_MISMATCH")

    target_ids: list[str] = []
    previous_kill_ns = -1
    for index, (window, kill) in enumerate(zip(windows, kills)):
        if not isinstance(window, dict) or not isinstance(kill, dict):
            raise ValueError("NATIVE_ROUTE_WORLD_RECEIPT_ROW_INVALID")
        native_kill_ns = window.get("native_kill_ns")
        world_kill_ns = kill.get("world_kill_clock_ns")
        if (
            window.get("index") != index
            or type(native_kill_ns) is not int
            or native_kill_ns <= previous_kill_ns
            or world_kill_ns != native_kill_ns
        ):
            raise ValueError("NATIVE_ROUTE_WORLD_KILL_CLOCK_NOT_CAUSAL")
        previous_kill_ns = native_kill_ns

        target_id = kill.get("target_id")
        ack_sha256 = kill.get("ack_sha256")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("NATIVE_ROUTE_WORLD_TARGET_ID_MISSING")
        if (
            not isinstance(ack_sha256, str)
            or len(ack_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in ack_sha256.lower())
        ):
            raise ValueError("NATIVE_ROUTE_WORLD_ACK_ID_INVALID")
        target_ids.append(target_id)

    if len(set(target_ids)) != target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_TARGETS_NOT_DISTINCT")
    native_damage_events = world.get("native_damage_events")
    world_ticks = world.get("world_ticks")
    if type(native_damage_events) is not int or native_damage_events < target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_NATIVE_DAMAGE_EVENTS_INCOMPLETE")
    if type(world_ticks) is not int or world_ticks < target_count:
        raise ValueError("NATIVE_ROUTE_WORLD_TICKS_INCOMPLETE")

    return {
        "world_targets_killed": target_count,
        "continuous_native_actor": True,
        "actual_2d_ack": True,
        "native_damage_events": native_damage_events,
        "world_ticks": world_ticks,
        "world_elapsed_seconds": world.get("world_elapsed_seconds"),
        "paid_recovery": world.get("paid_recovery"),
        "target_provenance": world.get("world_target_provenance"),
    }


def run_native_route_candidate(
    *,
    binary: str | Path,
    request: dict[str, Any],
    scenario: str,
    mob_health: float,
    iterations: int = 30,
    seed: int = 647003,
    target_count: int = 100,
    timeout_seconds: float = 180.0,
    engine_root: str | Path = _ENGINE_ROOT,
) -> dict[str, Any]:
    """Prepare, natively score and 2D-execute one complete route candidate.

    mob_health is an explicit diagnostic target profile supplied by the
    caller; the returned provenance is retained and is not a Forever source
    claim. timeout_seconds bounds prepare and sim. The workflow timeout
    bounds the synchronous 2D world bridge.
    """
    if type(iterations) is not int or not 1 <= iterations <= 1_000_000:
        raise ValueError("NATIVE_ROUTE_ITERATIONS_INVALID")
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("NATIVE_ROUTE_SEED_INVALID")
    if type(target_count) is not int or not 2 <= target_count <= 100:
        raise ValueError("NATIVE_ROUTE_TARGET_COUNT_INVALID")
    if (
        isinstance(mob_health, bool)
        or not isinstance(mob_health, (int, float))
        or not math.isfinite(float(mob_health))
        or not 0 < float(mob_health) <= 100_000_000
    ):
        raise ValueError("NATIVE_ROUTE_MOB_HEALTH_INVALID")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0.1 <= float(timeout_seconds) <= 600
    ):
        raise ValueError("NATIVE_ROUTE_TIMEOUT_INVALID")

    selected_root = Path(engine_root).resolve()
    binary_path = Path(binary).resolve()
    if not binary_path.is_file():
        return {
            "status": "BLOCKED",
            "stage": "engine",
            "reason": "SELECTED_RUST_BINARY_MISSING",
            "python_fallback": False,
            "checkpoint_certified": False,
        }
    if not binary_path.is_relative_to(selected_root):
        return {
            "status": "BLOCKED",
            "stage": "engine",
            "reason": "NATIVE_BINARY_OUTSIDE_SELECTED_ENGINE_ROOT",
            "python_fallback": False,
            "checkpoint_certified": False,
        }

    candidate_request = copy.deepcopy(request)
    player = _request_player(candidate_request)
    options = candidate_request["simOptions"]
    options["iterations"] = iterations
    options["randomSeed"] = str(seed)
    options["debugFirstIteration"] = False
    submitted_class = player.get("class")
    submitted_talents = player.get("talentsString")

    deadline = time.monotonic() + float(timeout_seconds)
    prepared = prepare_native_request(
        binary=binary_path,
        request=candidate_request,
        scenario=scenario,
        deadline=deadline,
    )
    if prepared.get("status") != "PREPARED":
        return {
            "status": prepared.get("status", "ERROR"),
            "stage": "prepare",
            "native_validation_status": prepared.get("status", "ERROR"),
            "reason": prepared.get("reason"),
            "native_prepare": {key: value for key, value in prepared.items() if key != "prepared"},
            "python_fallback": False,
            "checkpoint_certified": False,
        }

    simulated = _simulate_prepared(
        binary_path=binary_path,
        prepared=prepared["prepared"],
        rng_mode=NativeRngMode.BALANCED,
        iterations=iterations,
        seed=seed,
        deadline=deadline,
    )
    if simulated.get("status") != "EXECUTED":
        return {
            "status": simulated.get("status", "ERROR"),
            "stage": "sim",
            "native_validation_status": "VALID",
            "native_execution_status": simulated.get("status", "ERROR"),
            "native_score_dps": None,
            "reason": simulated.get("reason"),
            "native_prepare": {key: value for key, value in prepared.items() if key != "prepared"},
            "native_sim": simulated,
            "python_fallback": False,
            "checkpoint_certified": False,
        }

    try:
        with tempfile.TemporaryDirectory(prefix="forever-native-route-world-") as directory:
            prepared_path = Path(directory) / "prepared.json"
            prepared_path.write_text(
                json.dumps(prepared["prepared"], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            world = _run_world_bridge(
                binary_path,
                prepared_path,
                mob_health=float(mob_health),
                target_count=target_count,
            )
        world_summary = _validate_world_receipt(world, target_count)
    except Exception as exc:
        return {
            "status": "ERROR",
            "stage": "world",
            "native_validation_status": "VALID",
            "native_execution_status": "EXECUTED",
            "native_score_dps": simulated["dps"],
            "reason": f"NATIVE_ROUTE_WORLD_FAILED:{type(exc).__name__}:{exc}",
            "native_prepare": {key: value for key, value in prepared.items() if key != "prepared"},
            "native_sim": simulated,
            "python_fallback": False,
            "checkpoint_certified": False,
        }

    return {
        "status": "SCORED",
        "stage": "complete",
        "scenario": scenario,
        "source_class": submitted_class,
        "source_talents_string": submitted_talents,
        "native_validation_status": "VALID",
        "native_execution_status": "EXECUTED",
        "native_score_dps": simulated["dps"],
        "iterations_done": simulated.get("iterations_done"),
        "rng_mode": NativeRngMode.BALANCED.value,
        "world_execution": world_summary,
        "world_rng_mode": "stochastic",
        "engine_identity": prepared.get("engine_identity"),
        "request_sha256": prepared.get("request_sha256"),
        "prepared_sha256": prepared.get("prepared_sha256"),
        "report_sha256": simulated.get("report_sha256"),
        "python_fallback": False,
        "cross_level_resource_carry_verified": False,
        "route_transition_supported": False,
        "checkpoint_certified": False,
    }

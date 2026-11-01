"""Source-bound gsim 2D -> pinned Go *range-only* tick projection (#28).

Not a native action ACK, not a simulation backend, not P7 evidence. The only
public feed entrypoint snapshots a real CombatRuntime at every tick; the pure
projection helper is for testing and provides no provenance by itself.
"""
from __future__ import annotations

import hashlib
import json
from math import hypot, isfinite
from typing import Mapping


class GoWorldRangeError(ValueError):
    pass


def _finite(value, field: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise GoWorldRangeError(f"INVALID_{field}")
    return float(value)


def _coordinates(xy, field: str) -> tuple[float, float]:
    if not isinstance(xy, (list, tuple)) or len(xy) != 2:
        raise GoWorldRangeError(f"INVALID_{field}")
    return _finite(xy[0], field), _finite(xy[1], field)


def _projection_from_snapshot(world: Mapping, *, sequence: int, native_player_index: int) -> dict:
    """Pure validation/encoding only; callers MUST NOT treat arbitrary JSON as gsim."""
    if not isinstance(world, Mapping) or world.get("world_2d_source") != "gsim.CombatRuntime":
        raise GoWorldRangeError("WORLD_SOURCE_NOT_GSIM_2D")
    if type(sequence) is not int or sequence < 0 or type(native_player_index) is not int or native_player_index < 0:
        raise GoWorldRangeError("INVALID_NATIVE_SEQUENCE_OR_PLAYER_INDEX")
    clock = world.get("clock_ms")
    if type(clock) is not int or clock < 0:
        raise GoWorldRangeError("INVALID_WORLD_CLOCK_MS")
    player = _coordinates(world.get("player_xy_yards"), "PLAYER_COORDINATES")
    target_id = world.get("selected_target_id")
    enemies = world.get("enemies")
    if not isinstance(target_id, str) or not target_id or not isinstance(enemies, Mapping) or target_id not in enemies:
        raise GoWorldRangeError("WORLD_SELECTED_TARGET_MISSING")
    target = enemies[target_id]
    if not isinstance(target, Mapping) or target.get("alive") is not True:
        raise GoWorldRangeError("WORLD_SELECTED_TARGET_NOT_ALIVE")
    xy = _coordinates(target.get("xy_yards"), "TARGET_COORDINATES")
    distance = hypot(xy[0] - player[0], xy[1] - player[1])
    if not isfinite(distance):
        raise GoWorldRangeError("WORLD_DISTANCE_OVERFLOW")
    if not isinstance(target.get("controls"), Mapping):
        raise GoWorldRangeError("WORLD_CONTROLS_MISSING")
    # Same canonical JSON hashing as native_step_protocol.state_hash.
    try:
        raw = json.dumps(world, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GoWorldRangeError("INVALID_WORLD_SNAPSHOT_JSON") from exc
    return {
        "type": "gsim_world_range_tick", "protocol": "gsim-go-range-v1",
        "sequence": sequence, "clock_ms": clock,
        "native_clock_ns": clock * 1_000_000,
        "native_player_index": native_player_index,
        "world_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "selected_target_id": target_id,
        "distance_yards": distance,
        "world_source": "gsim.CombatRuntime",
        # PR #47 only applies Unit.DistanceFromTarget. Unimplemented semantics
        # must never silently be presented as applied world controls/actions.
        "range_only": True, "facing_applied": False, "controls_applied": False,
        "native_action_ack": False, "checkpoint_certified": False,
    }


class GsimGoRangeFeed:
    """Serial source-validated gsim range feed, at most one unACKed tick.

    The receipt is only a Go WorldRangeReceipt. It cannot prove a native spell
    decision, world-action ACK or a causal perturbation by itself.
    """

    def __init__(self, runtime, *, native_player_index: int):
        from .native_step_protocol import snapshot_gsim_world
        self._snapshot = snapshot_gsim_world
        self._runtime = runtime
        self._native_player_index = native_player_index
        self._pending: dict | None = None
        self._last_clock_ms = -1
        self._sequence = 0
        # Immediately reject fake/non-2D runtimes, not only on first tick.
        self._snapshot(runtime)

    def next_tick(self) -> dict:
        if self._pending is not None:
            raise GoWorldRangeError("PREVIOUS_NATIVE_RANGE_RECEIPT_MISSING")
        world = self._snapshot(self._runtime)
        projection = _projection_from_snapshot(world,
            sequence=self._sequence, native_player_index=self._native_player_index)
        # First native decision (and each new serial target) must consume the
        # actual gsim target's starting HP, not the native request's full HP.
        selected = projection["selected_target_id"]
        health = _finite(world["enemies"][selected]["health"], "WORLD_TARGET_HEALTH")
        max_health = _finite(self._runtime.targets[selected].max_health, "WORLD_TARGET_MAX_HEALTH")
        if health <= 0 or max_health <= 0 or health > max_health:
            raise GoWorldRangeError("WORLD_TARGET_HEALTH_INVALID")
        projection["world_target_health_before"] = health
        projection["world_target_max_health"] = max_health
        if projection["clock_ms"] <= self._last_clock_ms:
            raise GoWorldRangeError("WORLD_CLOCK_NOT_MONOTONIC")
        self._pending = projection
        return dict(projection)

    def accept_range_receipt(self, receipt: Mapping) -> dict:
        """Validate a receipt *shape*, not its origin; never award combat PASS."""
        pending = self._pending
        if pending is None:
            raise GoWorldRangeError("NATIVE_RANGE_RECEIPT_WITHOUT_WORLD_TICK")
        if not isinstance(receipt, Mapping):
            raise GoWorldRangeError("INVALID_NATIVE_RANGE_RECEIPT")
        if (type(receipt.get("sequence")) is not int or receipt["sequence"] != pending["sequence"]
                or type(receipt.get("native_clock_ns")) is not int
                or receipt["native_clock_ns"] != pending["native_clock_ns"]
                or type(receipt.get("player_index")) is not int
                or receipt["player_index"] != pending["native_player_index"]):
            raise GoWorldRangeError("NATIVE_RANGE_RECEIPT_IDENTITY_MISMATCH")
        applied = _finite(receipt.get("applied_yards"), "APPLIED_RANGE")
        damage = _finite(receipt.get("native_encounter_damage"), "NATIVE_DAMAGE")
        if abs(applied - pending["distance_yards"]) > 1e-6 or damage < 0:
            raise GoWorldRangeError("NATIVE_RANGE_RECEIPT_VALUES_MISMATCH")
        # The gsim world must not advance while a native receipt is in flight.
        current = _projection_from_snapshot(self._snapshot(self._runtime),
            sequence=self._sequence, native_player_index=self._native_player_index)
        if current["world_sha256"] != pending["world_sha256"]:
            raise GoWorldRangeError("WORLD_MUTATED_BEFORE_NATIVE_RECEIPT")
        self._last_clock_ms = pending["clock_ms"]
        self._sequence += 1
        self._pending = None
        return {"type": "native_range_receipt_fields_validated",
                "sequence": pending["sequence"], "world_sha256": pending["world_sha256"],
                "native_spell_action_ack": False, "checkpoint_certified": False}

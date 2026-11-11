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


def _projection_from_snapshot(world: Mapping, *, sequence: int, native_player_index: int,
                              allow_acknowledged_dead_selected: bool = False) -> dict:
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
    if type(allow_acknowledged_dead_selected) is not bool:
        raise GoWorldRangeError("WORLD_DEAD_SELECTED_ALLOWANCE_INVALID")
    if not isinstance(target, Mapping):
        raise GoWorldRangeError("WORLD_SELECTED_TARGET_NOT_ALIVE")
    if target.get("alive") is not True:
        # The normal range feed always rejects dead targets. An explicit
        # source-ACKed overlap continuation may retain dead B as selected
        # while A is alive/engaged and its native DoTs still need range
        # receipts. This flag is authorization from the native world ACK
        # caller, NOT evidence created by this range projection itself.
        if (not allow_acknowledged_dead_selected
                or target.get("alive") is not False
                or not any(isinstance(other, Mapping)
                           and other.get("alive") is True
                           and other.get("engaged") is True
                           for identity, other in enemies.items()
                           if identity != target_id)):
            raise GoWorldRangeError("WORLD_SELECTED_TARGET_NOT_ALIVE")
    xy = _coordinates(target.get("xy_yards"), "TARGET_COORDINATES")
    distance = hypot(xy[0] - player[0], xy[1] - player[1])
    if not isfinite(distance):
        raise GoWorldRangeError("WORLD_DISTANCE_OVERFLOW")
    if not isinstance(target.get("controls"), Mapping):
        raise GoWorldRangeError("WORLD_CONTROLS_MISSING")
    # Source-facing comes from gsim's actual heading and coordinates.
    heading = target.get("facing_xy_yards")
    in_front = None
    if heading is not None:
        facing = _coordinates(heading, "TARGET_FACING")
        norm = hypot(*facing)
        if not isfinite(norm) or norm <= 0 or distance <= 0:
            raise GoWorldRangeError("WORLD_TARGET_FACING_UNDEFINED")
        dot = facing[0]*(player[0]-xy[0]) + facing[1]*(player[1]-xy[1])
        if not isfinite(dot) or abs(dot) <= 1e-9*norm*distance:
            raise GoWorldRangeError("WORLD_TARGET_FACING_PERPENDICULAR")
        in_front = dot > 0
    # Same canonical JSON hashing as native_step_protocol.state_hash.
    try:
        raw = json.dumps(world, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise GoWorldRangeError("INVALID_WORLD_SNAPSHOT_JSON") from exc
    projection = {
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
        "range_only": True, "facing_applied": in_front is not None,
        "controls_applied": False,
        "native_action_ack": False, "checkpoint_certified": False,
    }
    if in_front is not None:
        projection["in_front_of_target"] = in_front
    return projection


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
        self._pending_allow_dead_selected = False
        self._last_clock_ms = -1
        self._sequence = 0
        # Immediately reject fake/non-2D runtimes, not only on first tick.
        self._snapshot(runtime)

    def next_tick(self, *, native_world_applier=None) -> dict:
        if self._pending is not None:
            raise GoWorldRangeError("PREVIOUS_NATIVE_RANGE_RECEIPT_MISSING")
        world = self._snapshot(self._runtime)
        allow_acknowledged_dead_selected = False
        if native_world_applier is not None:
            from .go_native_world_damage_ack import GsimNativeDamageWorldApplier
            if (not isinstance(native_world_applier, GsimNativeDamageWorldApplier)
                    or native_world_applier._runtime is not self._runtime):
                raise GoWorldRangeError("WORLD_NATIVE_ACK_SOURCE_MISMATCH")
            allow_acknowledged_dead_selected = (
                native_world_applier.is_native_acked_dead_selected_overlap(
                    world.get("selected_target_id")))
        projection = _projection_from_snapshot(
            world, sequence=self._sequence,
            native_player_index=self._native_player_index,
            allow_acknowledged_dead_selected=allow_acknowledged_dead_selected)
        # The selected-dead exception is only available through a matching
        # source-native lethal ACK ledger, not through an untrusted opt-in.
        # First native decision (and each new serial target) must consume the
        # actual gsim target's starting HP, not the native request's full HP.
        selected = projection["selected_target_id"]
        health = _finite(world["enemies"][selected]["health"], "WORLD_TARGET_HEALTH")
        max_health = _finite(self._runtime.targets[selected].max_health, "WORLD_TARGET_MAX_HEALTH")
        if (health < 0 or max_health <= 0 or health > max_health
                or (health == 0 and not allow_acknowledged_dead_selected)
                or (health == 0 and world["enemies"][selected]["alive"] is not False)):
            raise GoWorldRangeError("WORLD_TARGET_HEALTH_INVALID")
        projection["world_target_health_before"] = health
        projection["world_target_max_health"] = max_health
        if projection["clock_ms"] <= self._last_clock_ms:
            raise GoWorldRangeError("WORLD_CLOCK_NOT_MONOTONIC")
        self._pending = projection
        self._pending_allow_dead_selected = allow_acknowledged_dead_selected
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
        if (receipt.get("facing_applied", False) is not pending["facing_applied"]
                or (pending["facing_applied"] and
                    receipt.get("in_front_of_target") is not pending["in_front_of_target"])):
            raise GoWorldRangeError("NATIVE_FACING_RECEIPT_MISMATCH")
        # The gsim world must not advance while a native receipt is in flight.
        current = _projection_from_snapshot(
            self._snapshot(self._runtime),
            sequence=self._sequence, native_player_index=self._native_player_index,
            allow_acknowledged_dead_selected=self._pending_allow_dead_selected)
        if current["world_sha256"] != pending["world_sha256"]:
            raise GoWorldRangeError("WORLD_MUTATED_BEFORE_NATIVE_RECEIPT")
        self._last_clock_ms = pending["clock_ms"]
        self._sequence += 1
        self._pending = None
        self._pending_allow_dead_selected = False
        return {"type": "native_range_receipt_fields_validated",
                "sequence": pending["sequence"], "world_sha256": pending["world_sha256"],
                "native_spell_action_ack": False, "checkpoint_certified": False}

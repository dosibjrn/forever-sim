"""Actual gsim target-state application of source-native Go spell damage.

A real native per-spell DealDamage event, not a cumulative DPS counter, is
applied to an actual gsim CombatRuntime target. The returned ACK binds the
native event IDs and the measured before/after world hashes to one tick.
This is a narrow one-enemy source event seam, NOT a full P7 certificate.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from .go_world_range_feed import GoWorldRangeError
from .native_step_protocol import snapshot_gsim_world, state_hash


class NativeDamageWorldApplicationError(GoWorldRangeError):
    pass


class GsimNativeDamageWorldApplier:
    def __init__(self, runtime):
        # Source-validate the real 2D controller immediately.
        snapshot_gsim_world(runtime)
        self._runtime = runtime
        self._next_seq = 0
        self._previous_event_id = 0
        self._last_native_time_ns = -1
        self._last_world_tick_ns = -1
        self._target_id = None
        self._native_target_identity = None

    def apply(self, tick: Mapping, response: Mapping) -> dict:
        if not isinstance(tick, Mapping) or not isinstance(response, Mapping):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_PAYLOAD_INVALID")
        seq = tick.get("sequence")
        if type(seq) is not int or seq != self._next_seq or response.get("sequence") != seq:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SEQUENCE_REPLAY")
        clock_ns = tick.get("native_clock_ns")
        if (type(clock_ns) is not int or clock_ns < 0
                or clock_ns <= self._last_world_tick_ns):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_CLOCK_INVALID")
        before = snapshot_gsim_world(self._runtime)
        digest = state_hash(before)
        if digest != tick.get("world_sha256") or digest != response.get("observed_input_world_sha256"):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_WORLD_HASH_INVALID")
        target_id = tick.get("selected_target_id")
        if not isinstance(target_id, str) or target_id not in self._runtime.targets:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_MISSING")
        if self._target_id is not None and target_id != self._target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_GSIM_TARGET_SWITCH")
        target = self._runtime.targets[target_id]
        if not target.alive:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_ALREADY_DEAD")
        events = response.get("native_damage_events")
        pid = response.get("native_process_id")
        if not isinstance(events, list) or type(pid) is not int or pid <= 0:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENTS_OR_PID_INVALID")
        last_event_id = self._previous_event_id
        last_native_time = self._last_native_time_ns
        target_identity = self._native_target_identity
        ids = []
        damage = 0.0
        for event in events:
            if not isinstance(event, Mapping):
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENT_MALFORMED")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id.startswith("native-effect-"):
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_MISSING")
            try:
                ordinal = int(event_id.removeprefix("native-effect-"))
            except ValueError as exc:
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_INVALID") from exc
            # The pinned native Go journal emits a gapless, monotonic event
            # sequence across drains. Accepting a skipped ID would let an
            # omitted native effect disappear without changing gsim HP.
            if ordinal != last_event_id + 1 or event_id != f"native-effect-{ordinal}":
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_GAP")
            timestamp = event.get("native_time_ns")
            value = event.get("damage")
            current_native_target = (event.get("native_target_index"),
                                     event.get("native_target_unit_index"),
                                     event.get("native_target_label"))
            if (ordinal <= last_event_id or type(timestamp) is not int
                    or timestamp < 0 or timestamp < last_native_time
                    or timestamp < self._last_world_tick_ns or timestamp > clock_ns
                    or type(value) not in (float, int) or not isfinite(value) or value <= 0
                    or type(event.get("native_target_index")) is not int
                    or event["native_target_index"] != 0
                    or type(event.get("native_target_unit_index")) is not int
                    or event["native_target_unit_index"] < 0
                    or not isinstance(event.get("native_target_label"), str)
                    or not event["native_target_label"]
                    or not isinstance(event.get("source_action_id"), str)
                    or not event["source_action_id"]
                    or type(event.get("rank")) is not int or event["rank"] < 0
                    or any(type(event.get(flag)) is not bool for flag in ("landed", "crit", "periodic"))
                    or not event["landed"]
                    or (target_identity is not None and current_native_target != target_identity)):
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_EVENT_INVALID")
            ids.append(event_id)
            damage += float(value)
            last_event_id = ordinal
            last_native_time = timestamp
            target_identity = current_native_target
        # Fail closed BEFORE world mutation. Truncated overkill must not be
        # acknowledged as full native damage or attributed to another target.
        if not isfinite(damage) or damage > target.health + 1e-8:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_OVERKILL_UNSUPPORTED")
        old_health = float(target.health)
        for event in events:
            target.apply_damage(float(event["damage"]))
        applied = old_health - float(target.health)
        if abs(applied - damage) > 1e-6:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_HEALTH_DELTA_MISMATCH")
        after_hash = state_hash(snapshot_gsim_world(self._runtime))
        if (damage > 0 and after_hash == digest) or (damage == 0 and after_hash != digest):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_WORLD_NOT_CHANGED_AS_EXPECTED")
        self._target_id = target_id
        self._native_target_identity = target_identity
        self._next_seq += 1
        self._previous_event_id = last_event_id
        self._last_native_time_ns = last_native_time
        # Even an empty world ACK is a causal barrier: source effects reported
        # in a later tick may not be backdated before this acknowledged tick.
        self._last_world_tick_ns = clock_ns
        return {
            "type": "gsim_native_damage_applied_ack",
            "sequence": seq, "native_process_id": pid,
            "world_before_sha256": digest,
            "world_after_sha256": after_hash,
            "applied_event_ids": ids,
            "applied_events": [dict(event) for event in events],
            "applied_native_damage": damage,
        }

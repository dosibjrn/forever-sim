"""Apply source-native damage and landed control events to a real gsim target.

Damage and landed Roots control events are validated against one retained
native process, monotonic clock, target identity and world hash. Control is
applied through CombatRuntime's event queue so 2D movement and expiry remain
owned by gsim. This is not a full P1/P7 certificate.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping

from .events import CombatEvent
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
        self._previous_control_event_id = 0
        self._native_process_id = None
        self._last_native_time_ns = -1
        self._last_world_tick_ns = -1
        self._target_id = None
        self._native_target_identity = None
        # A dead gsim mob alone is not evidence that the native actor killed it.
        self._last_native_lethal_target_id = None
        # Damage for a later mob must not be dated before its live world handoff.
        self._target_handoff_ns = None

    def begin_next_world_target(self, next_target_id: str) -> None:
        """Retarget only after an ACKed lethal event, preserving PID/event clocks.

        The same native enemy slot represents the next identical source mob;
        the native actor and journal must never restart or renumber events.
        """
        if (self._target_id is None or next_target_id == self._target_id
                or next_target_id not in self._runtime.targets
                or self._runtime.targets[self._target_id].alive
                or not self._runtime.targets[next_target_id].alive):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_NOT_READY")
        if self._last_native_lethal_target_id != self._target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_NOT_NATIVE_LETHAL")
        world = snapshot_gsim_world(self._runtime)
        if world["selected_target_id"] != next_target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_NOT_SELECTED")
        handoff_ns = world["clock_ms"] * 1_000_000
        if handoff_ns < self._last_world_tick_ns:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_CLOCK_REWIND")
        self._target_id = next_target_id
        self._target_handoff_ns = handoff_ns
        self._last_native_lethal_target_id = None

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
        # Native time is not authority for gsim time. Reject a fabricated
        # future tick before any source event can mutate target HP, including
        # empty ticks that would otherwise establish a false ACK barrier.
        world_clock_ms = before["clock_ms"]
        if (type(tick.get("clock_ms")) is not int
                or tick["clock_ms"] != world_clock_ms
                or clock_ns != world_clock_ms * 1_000_000):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_WORLD_CLOCK_MISMATCH")
        digest = state_hash(before)
        if digest != tick.get("world_sha256") or digest != response.get("observed_input_world_sha256"):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_WORLD_HASH_INVALID")
        target_id = tick.get("selected_target_id")
        if not isinstance(target_id, str) or target_id not in self._runtime.targets:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_MISSING")
        # The native single-target slot must map to the target actually
        # selected by the live gsim controller at this exact world snapshot.
        # A valid world hash does not authorize a forged tick to redirect
        # source-native damage to another living mob.
        if target_id != before["selected_target_id"]:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_NOT_SELECTED")
        if self._target_id is not None and target_id != self._target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_GSIM_TARGET_SWITCH")
        target = self._runtime.targets[target_id]
        if not target.alive:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_ALREADY_DEAD")
        events = response.get("native_damage_events")
        control_events = response.get("native_control_events", [])
        pid = response.get("native_process_id")
        if (not isinstance(events, list) or not isinstance(control_events, list)
                or type(pid) is not int or pid <= 0):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENTS_OR_PID_INVALID")
        # Event ordinals are only meaningful within one retained native process.
        # A restarted process cannot continue a paid world session by merely
        # supplying plausible new event IDs and a valid gsim snapshot.
        if self._native_process_id is not None and pid != self._native_process_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_PROCESS_RESTARTED")
        last_event_id = self._previous_event_id
        last_control_event_id = self._previous_control_event_id
        # A genuine source pre-pull spell can deal damage before encounter t=0.
        # It is visible to gsim at the first world ACK, with its original
        # negative native timestamp retained (not fabricated as a t=0 hit).
        # Later ticks may never smuggle in pre-pull damage retroactively.
        first_precombat_boundary = seq == 0 and clock_ns == 0
        previous_native_time = (
            -(1 << 63) if first_precombat_boundary else self._last_native_time_ns
        )
        last_native_time = previous_native_time
        control_last_native_time = previous_native_time
        # Validate all native effects before mutating the real gsim target.
        # An ACK batch cannot hide a second, later native hit after the first
        # already killed this same world mob. Equal-time effects are atomic.
        max_health = float(target.max_health)
        old_health = float(target.health)
        if (not isfinite(max_health) or max_health <= 0
                or not isfinite(old_health) or old_health <= 0
                or old_health > max_health):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_MAX_HEALTH_INVALID")
        health_at_event = old_health
        lethal_native_time_ns = None
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
            caster_type = event.get("native_caster_type", "")
            caster_index = event.get("native_caster_unit_index", 0)
            caster_label = event.get("native_caster_label", "")
            if (ordinal <= last_event_id or type(timestamp) is not int
                    or (timestamp < 0 and not first_precombat_boundary)
                    or timestamp < last_native_time
                    or (timestamp < self._last_world_tick_ns and not first_precombat_boundary)
                    or timestamp > clock_ns
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
                    or caster_type not in ("", "pet")
                    or (caster_type == "pet" and (
                        type(caster_index) is not int or caster_index < 0
                        or not isinstance(caster_label, str) or not caster_label))
                    or (caster_type == "" and (caster_index != 0 or caster_label != ""))
                    or (target_identity is not None and current_native_target != target_identity)):
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_EVENT_INVALID")
            # The old target's native damage journal cannot leak into a new
            # gsim mob during paid travel/recovery after its world handoff.
            if (self._target_handoff_ns is not None
                    and timestamp < self._target_handoff_ns):
                raise NativeDamageWorldApplicationError(
                    "WORLD_DAMAGE_ACK_EVENT_BEFORE_TARGET_HANDOFF")
            if lethal_native_time_ns is not None and timestamp > lethal_native_time_ns:
                raise NativeDamageWorldApplicationError(
                    "WORLD_DAMAGE_ACK_NATIVE_EVENT_AFTER_WORLD_DEATH")
            health_at_event = max(0.0, health_at_event - float(value))
            if health_at_event == 0.0 and lethal_native_time_ns is None:
                lethal_native_time_ns = timestamp
            ids.append(event_id)
            damage += float(value)
            last_event_id = ordinal
            last_native_time = timestamp
            target_identity = current_native_target

        # Control events have their own gapless ordinal stream, but share the
        # retained process, native clock and single native target identity.
        # Validate the entire batch before applying damage or control to gsim.
        control_payloads = []
        for event in control_events:
            if not isinstance(event, Mapping):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_MALFORMED")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id.startswith("native-control-"):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_ID_MISSING")
            try:
                ordinal = int(event_id.removeprefix("native-control-"))
            except ValueError as exc:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_ID_INVALID") from exc
            if ordinal != last_control_event_id + 1 or event_id != f"native-control-{ordinal}":
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_ID_GAP")
            timestamp = event.get("native_time_ns")
            duration_ns = event.get("duration_ns")
            rank = event.get("rank")
            target_index = event.get("native_target_index")
            unit_index = event.get("native_target_unit_index")
            target_label = event.get("native_target_label")
            source_action_id = event.get("source_action_id")
            if (type(timestamp) is not int or timestamp < 0 or timestamp > clock_ns
                    or timestamp < self._last_world_tick_ns
                    or timestamp < control_last_native_time):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_TIME_INVALID")
            if type(duration_ns) is not int or duration_ns <= 0:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_DURATION_INVALID")
            expiry_ns = timestamp + duration_ns
            if expiry_ns > (1 << 63) - 1 or expiry_ns <= clock_ns:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_EXPIRED_BEFORE_APPLY")
            if event.get("control_id") != "root" or event.get("landed") is not True:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_NOT_LANDED_ROOT")
            if type(rank) is not int or rank < 0:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_RANK_INVALID")
            if (type(target_index) is not int or target_index != 0
                    or type(unit_index) is not int or unit_index < 0
                    or not isinstance(target_label, str) or not target_label):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_TARGET_INVALID")
            if not isinstance(source_action_id, str) or not source_action_id:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_ACTION_INVALID")
            current_native_target = (target_index, unit_index, target_label)
            if target_identity is not None and current_native_target != target_identity:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_TARGET_IDENTITY_CHANGED")
            if self._target_handoff_ns is not None and timestamp < self._target_handoff_ns:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_BEFORE_TARGET_HANDOFF")
            if (lethal_native_time_ns is not None
                    and timestamp > lethal_native_time_ns):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_ACK_EVENT_AFTER_WORLD_DEATH")
            target_identity = current_native_target
            control_last_native_time = timestamp
            last_control_event_id = ordinal
            control_payloads.append((event, expiry_ns, expiry_ns - clock_ns))

        # Native spell damage can exceed remaining target HP on a lethal hit.
        # Preserve the full source-native event transcript while clamping only
        # the actual gsim world-health delta. Overkill must not block a kill.
        if not isfinite(damage):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_DAMAGE_INVALID")
        for event in events:
            target.apply_damage(float(event["damage"]))
        applied = old_health - float(target.health)
        if abs(applied - min(damage, old_health)) > 1e-6:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_HEALTH_DELTA_MISMATCH")

        # Apply control through the same CombatRuntime queue used by native
        # world mechanics. The remaining duration is measured from this ACK
        # clock so the original native expiry timestamp is preserved.
        control_runtime_events = []
        for event, expiry_ns, remaining_ns in control_payloads:
            runtime_event = CombatEvent(
                time_s=clock_ns / 1_000_000_000.0,
                kind="ControlApplied",
                actor_id=self._runtime.actor.id,
                target_id=target_id,
                action_id=event["source_action_id"],
                payload={
                    "control_id": "root",
                    "duration_s": remaining_ns / 1_000_000_000.0,
                    "proc_chance": 1.0,
                    "effect_index": 0,
                    "prevents_enemy_actions": False,
                    # Damage-break is explicitly outside this first slice.
                    "breaks_on_damage": False,
                    "native_event_id": event["event_id"],
                    "native_time_ns": event["native_time_ns"],
                    "native_duration_ns": event["duration_ns"],
                    "native_source_rank": event["rank"],
                    "native_damage_break_implemented": False,
                },
            )
            self._runtime.queue.push(runtime_event)
            control_runtime_events.append((event, runtime_event, expiry_ns))
        if control_runtime_events:
            self._runtime.advance_to(clock_ns / 1_000_000_000.0)

        applied_control_event_ids = [event["event_id"] for event in control_events]
        applied_control_events = [
            {
                **dict(event),
                "applied": bool(runtime_event.payload.get("applied", False)),
                "applied_at_ns": clock_ns,
                "expires_at_ns": expiry_ns,
            }
            for event, runtime_event, expiry_ns in control_runtime_events
        ]

        after_hash = state_hash(snapshot_gsim_world(self._runtime))
        if ((damage > 0 and after_hash == digest)
                or (damage == 0 and not control_events and after_hash != digest)):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_WORLD_NOT_CHANGED_AS_EXPECTED")
        self._target_id = target_id
        # Only THIS native ACK's applied effects may authorize switching mobs.
        # An unrelated gsim/world health change must not satisfy causality.
        self._last_native_lethal_target_id = (
            target_id if damage > 0.0 and not target.alive else None
        )
        self._native_target_identity = target_identity
        self._next_seq += 1
        self._previous_event_id = last_event_id
        self._previous_control_event_id = last_control_event_id
        self._native_process_id = pid
        self._last_native_time_ns = max(last_native_time, control_last_native_time)
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
            "applied_control_event_ids": applied_control_event_ids,
            "applied_control_events": applied_control_events,
            "applied_native_damage": damage,
            "world_target_health_before": old_health,
            "world_target_health_after": float(target.health),
            "world_target_max_health": max_health,
        }

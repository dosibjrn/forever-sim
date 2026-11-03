"""Actual gsim target-state application of source-native Go spell damage.

A real native per-spell DealDamage event, not a cumulative DPS counter, is
applied to an actual gsim CombatRuntime target. The returned ACK binds the
native event IDs and the measured before/after world hashes to one tick.
This is a narrow one-enemy source event seam, NOT a full P7 certificate.
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
        self._native_process_id = None
        self._last_native_time_ns = -1
        self._last_world_tick_ns = -1
        self._target_id = None
        self._native_target_identity = None
        # A dead gsim mob alone is not evidence that the native actor killed it.
        self._last_native_lethal_target_id = None
        # Damage for a later mob must not be dated before its live world handoff.
        self._target_handoff_ns = None
        # Exact source-native Roots expiry currently synchronized to the selected gsim mob.
        self._native_root_expiry_ns = None

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
        self._native_root_expiry_ns = None

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
        pid = response.get("native_process_id")
        if not isinstance(events, list) or type(pid) is not int or pid <= 0:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENTS_OR_PID_INVALID")
        # Event ordinals are only meaningful within one retained native process.
        # A restarted process cannot continue a paid world session by merely
        # supplying plausible new event IDs and a valid gsim snapshot.
        if self._native_process_id is not None and pid != self._native_process_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_PROCESS_RESTARTED")
        last_event_id = self._previous_event_id
        # A genuine source pre-pull spell can deal damage before encounter t=0.
        # It is visible to gsim at the first world ACK, with its original
        # negative native timestamp retained (not fabricated as a t=0 hit).
        # Later ticks may never smuggle in pre-pull damage retroactively.
        first_precombat_boundary = seq == 0 and clock_ns == 0
        last_native_time = -(1 << 63) if first_precombat_boundary else self._last_native_time_ns
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
        # Native spell damage can exceed remaining target HP on a lethal hit.
        # Preserve the full source-native event transcript while clamping only
        # the actual gsim world-health delta. Overkill must not block a kill.
        if not isfinite(damage):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_DAMAGE_INVALID")

        # The selected Rust Druid source reports the exact native Roots-dot
        # expiry separately from damage. Apply that control to the same live
        # 2D gsim target; do not infer it from spell names or damage events.
        range_receipt = response.get("native_range_receipt", {})
        if not isinstance(range_receipt, Mapping):
            raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_RECEIPT_INVALID")
        root_expiry_ns = range_receipt.get("native_rooted_until_ns")
        root_changed_at_ns = range_receipt.get("native_root_control_changed_at_ns")
        if (root_expiry_ns is not None
                and (type(root_expiry_ns) is not int or root_expiry_ns <= clock_ns)):
            raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_EXPIRY_INVALID")
        if (root_changed_at_ns is not None
                and (type(root_changed_at_ns) is not int or root_changed_at_ns < 0
                     or root_changed_at_ns > clock_ns
                     or clock_ns - root_changed_at_ns > 1_000_000)):
            raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_CHANGE_TIME_INVALID")
        root_state_changed = root_expiry_ns != self._native_root_expiry_ns
        if root_state_changed != (root_changed_at_ns is not None):
            raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_CHANGE_RECEIPT_MISMATCH")

        root_applied = False
        if root_state_changed and root_expiry_ns is not None:
            if (self._native_root_expiry_ns is not None
                    and root_expiry_ns <= self._native_root_expiry_ns):
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_REFRESH_NOT_EXTENDING")
            duration_s = (root_expiry_ns - clock_ns) / 1_000_000_000
            self._runtime.queue.push(CombatEvent(
                time_s=clock_ns / 1_000_000_000,
                kind="ControlApplied",
                actor_id=self._runtime.actor.id,
                target_id=target_id,
                action_id="native:entangling-roots",
                payload={
                    "control_id": "root",
                    "duration_s": duration_s,
                    "proc_chance": 1.0,
                    # Damage-break is intentionally not claimed until its
                    # source rank/target rules are ported and independently tested.
                    "breaks_on_damage": False,
                    "break_chance_on_damage": None,
                    "prevents_enemy_actions": False,
                },
            ))
            self._runtime.advance_to(clock_ns / 1_000_000_000)
            active_until = float(target.active_controls.get("root", 0.0))
            if abs(active_until - root_expiry_ns / 1_000_000_000) > 1e-6:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_APPLY_ACK_MISMATCH")
            root_applied = True
        elif root_state_changed:
            # This first source slice supports natural dot expiry only. An
            # earlier clear (e.g. damage break/dispel) must fail closed until
            # its native probability and target semantics are implemented.
            previous_expiry_ns = self._native_root_expiry_ns
            if previous_expiry_ns is None or root_changed_at_ns is None:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_CLEAR_WITHOUT_PRIOR_ROOT")
            if root_changed_at_ns < previous_expiry_ns:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_EARLY_CLEAR_UNSUPPORTED")
            if root_changed_at_ns - previous_expiry_ns > 1_000_000:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_EXPIRY_LATE")
            if float(target.active_controls.get("root", 0.0)) > clock_ns / 1_000_000_000 + 1e-9:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_DID_NOT_EXPIRE")
        elif root_expiry_ns is not None:
            active_until = float(target.active_controls.get("root", 0.0))
            if abs(active_until - root_expiry_ns / 1_000_000_000) > 1e-6:
                raise NativeDamageWorldApplicationError("WORLD_ROOT_CONTROL_STATE_DIVERGED")

        if root_state_changed:
            self._native_root_expiry_ns = root_expiry_ns

        for event in events:
            target.apply_damage(float(event["damage"]))
        applied = old_health - float(target.health)
        if abs(applied - min(damage, old_health)) > 1e-6:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_HEALTH_DELTA_MISMATCH")
        after_hash = state_hash(snapshot_gsim_world(self._runtime))
        if ((damage > 0 and after_hash == digest)
                or (damage == 0 and not root_applied and after_hash != digest)
                or (root_applied and after_hash == digest)):
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
        self._native_process_id = pid
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
            "world_target_health_before": old_health,
            "world_target_health_after": float(target.health),
            "world_target_max_health": max_health,
            "native_rooted_until_ns": root_expiry_ns,
            "native_root_control_changed_at_ns": root_changed_at_ns,
            "world_target_rooted": (
                float(target.active_controls.get("root", 0.0))
                > clock_ns / 1_000_000_000 + 1e-9
            ),
        }

"""Actual gsim target-state application of source-native damage and root control.

Damage events mutate target HP; a landed native Entangling Roots control event
immobilizes a moving 2D target until its source duration expires. Root damage-
break semantics remain explicitly unimplemented, so this is not a P1/P2 PASS
or a full P7 certificate.
"""
from __future__ import annotations

from math import isfinite
import re
from typing import Mapping

from .events import CombatEvent

from .go_world_range_feed import GoWorldRangeError
from .native_step_protocol import snapshot_gsim_world, state_hash


class NativeDamageWorldApplicationError(GoWorldRangeError):
    pass


# The six genuine Forever Entangling Roots ranks have distinct spell IDs.
# Source-native controls carry both the spell ID and rank: reject mismatches
# without incorrectly rejecting lower-level, source-legal Roots casts.
_ROOTS_SPELL_IDS_BY_RANK = (0, 339, 1062, 5195, 5196, 9852, 9853)


def _roots_action_matches_rank(action_id: str, rank: int) -> bool:
    if type(rank) is not int or not 1 <= rank <= 6:
        return False
    spell_id = _ROOTS_SPELL_IDS_BY_RANK[rank]
    return re.search(rf"(?<!\w)SpellID:\s*{spell_id}(?!\d)", action_id) is not None


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
        # Native enemy slots stay bound to distinct real world IDs across
        # overlapping ACKs. A serial handoff can reuse slot zero only after
        # a source-native lethal ACK.
        self._native_target_ids: dict[int, str] = {}
        self._native_identities: dict[int, tuple] = {}
        self._native_handoff_ns: dict[int, int] = {}
        # A dead gsim mob alone is not evidence that the native actor killed it.
        self._last_native_lethal_target_id = None
        # Remember real native effects already applied to each dead 2D target.
        # A selected dead B can remain selected while A's DoTs still tick.
        self._native_lethal_acked_ids: set[str] = set()
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
        # After an overlapping switch, killing only the selected mob does
        # not retire old-target DoTs or authorize reuse of its native slot.
        if any(self._runtime.targets[world_id].alive
               for world_id in self._native_target_ids.values()):
            raise NativeDamageWorldApplicationError(
                "WORLD_DAMAGE_ACK_PREVIOUS_NATIVE_TARGET_STILL_LIVE")
        world = snapshot_gsim_world(self._runtime)
        if world["selected_target_id"] != next_target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_NOT_SELECTED")
        handoff_ns = world["clock_ms"] * 1_000_000
        if handoff_ns < self._last_world_tick_ns:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NEXT_TARGET_CLOCK_REWIND")
        self._target_id = next_target_id
        self._native_target_ids = {0: next_target_id}
        self._native_identities.clear()
        self._native_handoff_ns = {0: handoff_ns}
        self._native_lethal_acked_ids.clear()
        self._last_native_lethal_target_id = None

    def begin_overlapping_world_target(self, next_target_id: str,
                                       *, native_target_index: int = 1) -> None:
        """Bind a second engaged living mob after a real prior native/world ACK.

        This permits subsequent old-target DoTs to retain native slot zero.
        Caller must acquire/select the second gsim target from a source-native
        switch request; this method does not decide when to pull or certify a
        rolling World-APL policy on its own.
        """
        if (type(native_target_index) is not int or native_target_index != 1
                or self._next_seq == 0 or self._target_id is None
                or self._native_target_ids != {0: self._target_id}
                or next_target_id in self._native_target_ids.values()
                or next_target_id not in self._runtime.targets):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_OVERLAP_SLOT_INVALID")
        world = snapshot_gsim_world(self._runtime)
        old = self._target_id
        if (world["selected_target_id"] != next_target_id
                or not world["enemies"][old]["alive"]
                or not world["enemies"][old]["engaged"]
                or not world["enemies"][next_target_id]["alive"]
                or not world["enemies"][next_target_id]["engaged"]):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_OVERLAP_NOT_TWO_LIVE")
        handoff_ns = world["clock_ms"] * 1_000_000
        if handoff_ns < self._last_world_tick_ns:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_OVERLAP_CLOCK_REWIND")
        self._native_target_ids[1] = next_target_id
        self._native_handoff_ns[1] = handoff_ns
        self._target_id = next_target_id

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
        # future tick before any source event can mutate target HP or controls.
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
        if target_id != before["selected_target_id"]:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_NOT_SELECTED")
        if self._target_id is not None and target_id != self._target_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_GSIM_TARGET_SWITCH")
        target_by_index = self._native_target_ids or {0: target_id}
        if target_id not in target_by_index.values():
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_TARGET_UNBOUND")
        target = self._runtime.targets[target_id]
        if not target.alive:
            # Rust may keep B selected after its real lethal ACK while an
            # older live A has source DoTs pending. A fresh/pre-dead B, an
            # unbound slot or a fully dead encounter cannot use this path.
            if (target_by_index.get(1) != target_id
                    or target_id not in self._native_lethal_acked_ids
                    or 0 not in target_by_index
                    or not self._runtime.targets[target_by_index[0]].alive):
                raise NativeDamageWorldApplicationError(
                    "WORLD_DAMAGE_ACK_TARGET_ALREADY_DEAD")
        events = response.get("native_damage_events")
        control_events = response.get("native_control_events", [])
        pid = response.get("native_process_id")
        if (not isinstance(events, list) or not isinstance(control_events, list)
                or type(pid) is not int or pid <= 0):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENTS_OR_PID_INVALID")
        if self._native_process_id is not None and pid != self._native_process_id:
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_PROCESS_RESTARTED")
        last_event_id = self._previous_event_id
        first_precombat_boundary = seq == 0 and clock_ns == 0
        last_native_time = -(1 << 63) if first_precombat_boundary else self._last_native_time_ns
        max_health = float(target.max_health)
        old_health = float(target.health)
        if (not isfinite(max_health) or max_health <= 0
                or not isfinite(old_health) or old_health < 0
                or old_health > max_health):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_TARGET_MAX_HEALTH_INVALID")

        # Damage and control share one gapless source-native event ordinal.
        # The wire keeps separate arrays, so merge them before validating or
        # applying anything; never let a control event disappear between IDs.
        # A native batch can already contain events later than its first lethal
        # timestamp: the engine cannot observe gsim death until this ACK. Consume
        # the complete ordered journal, but only effects seen while the target
        # was alive may mutate its world state.
        ordered = []
        for kind, batch in (("damage", events), ("control", control_events)):
            for event in batch:
                if not isinstance(event, Mapping):
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_NATIVE_EVENT_MALFORMED")
                event_id = event.get("event_id")
                if not isinstance(event_id, str) or not event_id.startswith("native-effect-"):
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_MISSING")
                try:
                    ordinal = int(event_id.removeprefix("native-effect-"))
                except ValueError as exc:
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_INVALID") from exc
                if event_id != f"native-effect-{ordinal}":
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_INVALID")
                ordered.append((ordinal, kind, event))
        ordered.sort(key=lambda item: item[0])

        health_before_by_index = {
            index: float(self._runtime.targets[world_id].health)
            for index, world_id in target_by_index.items()
        }
        health_at_event = dict(health_before_by_index)
        target_identity = dict(self._native_identities)
        ids = []
        damage_ids = []
        damage = 0.0
        damage_by_index: dict[int, float] = {}
        validated = []
        for ordinal, kind, event in ordered:
            if ordinal != last_event_id + 1:
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_EVENT_ID_GAP")
            event_id = event["event_id"]
            timestamp = event.get("native_time_ns")
            current_native_target = (
                event.get("native_target_index"),
                event.get("native_target_unit_index"),
                event.get("native_target_label"),
            )
            caster_type = event.get("native_caster_type", "")
            caster_index = event.get("native_caster_unit_index", 0)
            caster_label = event.get("native_caster_label", "")
            source_action_id = event.get("source_action_id")
            value = event.get("damage", 0.0)
            effect_kind = event.get("effect_kind", kind)
            if (type(timestamp) is not int
                    or (timestamp < 0 and not first_precombat_boundary)
                    or timestamp < last_native_time
                    or (timestamp < self._last_world_tick_ns and not first_precombat_boundary)
                    or timestamp > clock_ns
                    or effect_kind != kind
                    or type(event.get("native_target_index")) is not int
                    or event["native_target_index"] not in target_by_index
                    or type(event.get("native_target_unit_index")) is not int
                    or event["native_target_unit_index"] < 0
                    or not isinstance(event.get("native_target_label"), str)
                    or not event["native_target_label"]
                    or not isinstance(source_action_id, str) or not source_action_id
                    or type(event.get("rank")) is not int or event["rank"] < 0
                    or any(type(event.get(flag)) is not bool
                           for flag in ("landed", "crit", "periodic"))
                    or not event["landed"]
                    or caster_type not in ("", "pet")
                    or (caster_type == "pet" and (
                        type(caster_index) is not int or caster_index < 0
                        or not isinstance(caster_label, str) or not caster_label))
                    or (caster_type == "" and (caster_index != 0 or caster_label != ""))
                    or (event["native_target_index"] in target_identity
                        and current_native_target !=
                        target_identity[event["native_target_index"]])):
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_EVENT_INVALID")

            native_index = event["native_target_index"]
            handoff_ns = self._native_handoff_ns.get(native_index)
            if handoff_ns is not None and timestamp < handoff_ns:
                raise NativeDamageWorldApplicationError(
                    "WORLD_DAMAGE_ACK_EVENT_BEFORE_TARGET_HANDOFF")
            if kind == "damage":
                if (type(value) not in (float, int) or not isfinite(value) or value <= 0
                        or event.get("control_id") is not None
                        or event.get("duration_ns") is not None
                        or event.get("break_semantics_status") is not None):
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_SOURCE_EVENT_INVALID")
                world_effect_allowed = health_at_event[native_index] > 0.0
                health_at_event[native_index] = max(
                    0.0, health_at_event[native_index] - float(value))
                damage += float(value)
                damage_by_index[native_index] = (
                    damage_by_index.get(native_index, 0.0) + float(value))
                damage_ids.append(event_id)
            else:
                duration_ns = event.get("duration_ns")
                if (type(value) not in (float, int) or not isfinite(value) or value != 0
                        or event.get("control_id") != "root"
                        or type(duration_ns) is not int or duration_ns <= 0
                        or event.get("break_semantics_status") != "unimplemented"
                        or type(event.get("rank")) is not int
                        or not 1 <= event["rank"] <= 6
                        or event.get("crit") is not False
                        or event.get("periodic") is not False
                        or caster_type != "" or caster_index != 0 or caster_label != ""
                        or not _roots_action_matches_rank(source_action_id, event["rank"])):
                    raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_CONTROL_EVENT_INVALID")
                world_effect_allowed = health_at_event[native_index] > 0.0
            ids.append(event_id)
            validated.append((
                kind, event, world_effect_allowed, target_by_index[native_index]))
            last_event_id = ordinal
            last_native_time = timestamp
            target_identity[native_index] = current_native_target

        if not isfinite(damage):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_DAMAGE_INVALID")

        acknowledged_control_ids = []
        acknowledged_control_events = []
        applied_control_ids = []
        applied_control_events = []
        for kind, event, world_effect_allowed, event_world_id in validated:
            event_target = self._runtime.targets[event_world_id]
            if kind == "damage":
                # A buffered overkill event is still consumed in native
                # ordinal order, but cannot mutate the already-dead world mob.
                if world_effect_allowed:
                    event_target.apply_damage(float(event["damage"]))
                continue
            # ACK every valid source event, but preserve its absolute source
            # expiry. If a pre-pull root has already expired before the first
            # world boundary, consume the event without inventing a live root.
            acknowledged_control_ids.append(event["event_id"])
            acknowledged = dict(event)
            if not world_effect_allowed:
                acknowledged["world_application_status"] = "discarded_after_target_death"
                acknowledged_control_events.append(acknowledged)
                continue
            world_time_s = float(self._runtime.actor.current_time_s)
            remaining_ns = int(event["native_time_ns"]) + int(event["duration_ns"]) - clock_ns
            if remaining_ns <= 0:
                acknowledged["world_application_status"] = "expired_before_world_ack"
                acknowledged_control_events.append(acknowledged)
                continue
            control = CombatEvent(
                time_s=world_time_s,
                kind="ControlApplied",
                actor_id=self._runtime.actor.id,
                target_id=event_world_id,
                action_id=str(event["source_action_id"]),
                payload={
                    "control_id": "root",
                    "duration_s": float(remaining_ns) / 1_000_000_000.0,
                    "prevents_enemy_actions": False,
                    "breaks_on_damage": False,
                    "break_chance_on_damage": None,
                    "effect_index": 0,
                    "proc_chance": 1.0,
                    "native_event_id": event["event_id"],
                    "native_time_ns": event["native_time_ns"],
                    "break_semantics_status": "unimplemented",
                },
            )
            self._runtime.queue.push(control)
            self._runtime.advance_to(world_time_s)
            if control.payload.get("applied") is not True:
                raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_CONTROL_NOT_APPLIED")
            applied_control_ids.append(event["event_id"])
            acknowledged["world_application_status"] = "applied"
            acknowledged_control_events.append(acknowledged)
            applied_control_events.append(dict(event))

        for native_index, world_id in target_by_index.items():
            applied = health_before_by_index[native_index] - float(
                self._runtime.targets[world_id].health)
            amount = damage_by_index.get(native_index, 0.0)
            if abs(applied - min(amount, health_before_by_index[native_index])) > 1e-6:
                raise NativeDamageWorldApplicationError(
                    "WORLD_DAMAGE_ACK_HEALTH_DELTA_MISMATCH")
        after_hash = state_hash(snapshot_gsim_world(self._runtime))
        world_changed = any(
            self._runtime.targets[world_id].health != health_before_by_index[index]
            for index, world_id in target_by_index.items()
        ) or bool(applied_control_ids)
        if (world_changed and after_hash == digest) or (not world_changed and after_hash != digest):
            raise NativeDamageWorldApplicationError("WORLD_DAMAGE_ACK_WORLD_NOT_CHANGED_AS_EXPECTED")
        # Commit deaths only when a valid source event actually took a living
        # 2D target to zero. A later old-target overkill is a no-op, not a
        # second kill or a newly acquired dead enemy.
        self._native_lethal_acked_ids.update(
            world_id for index, world_id in target_by_index.items()
            if health_before_by_index[index] > 0
            and self._runtime.targets[world_id].health == 0
            and damage_by_index.get(index, 0.0) > 0
        )
        self._target_id = target_id
        # Preserve B's prior lethal ancestry while A's old DoTs finish.
        # A later serial handoff is still forbidden until BOTH targets die.
        self._last_native_lethal_target_id = (
            target_id if target_id in self._native_lethal_acked_ids else None
        )
        self._native_target_ids = dict(target_by_index)
        self._native_identities = target_identity
        self._next_seq += 1
        self._previous_event_id = last_event_id
        self._native_process_id = pid
        self._last_native_time_ns = last_native_time
        self._last_world_tick_ns = clock_ns
        # Per-target committed health rows are necessary only for overlap.
        # The legacy serial scalar ACK remains byte-shape compatible.
        multi_target_ack = {}
        if len(target_by_index) > 1:
            selected_index = next(
                index for index, world_id in target_by_index.items()
                if world_id == target_id)
            multi_target_ack = {
                "selected_native_target_index": selected_index,
                "native_target_health_acks": [
                    {
                        "native_target_index": index,
                        "world_target_id": target_by_index[index],
                        "world_target_health_before": health_before_by_index[index],
                        "world_target_health_after": float(
                            self._runtime.targets[target_by_index[index]].health),
                        "world_target_max_health": float(
                            self._runtime.targets[target_by_index[index]].max_health),
                    }
                    for index in sorted(damage_by_index)
                ],
            }
        return {
            **multi_target_ack,
            "type": "gsim_native_damage_applied_ack",
            "sequence": seq,
            "native_process_id": pid,
            "world_before_sha256": digest,
            "world_after_sha256": after_hash,
            "applied_event_ids": ids,
            "applied_damage_event_ids": damage_ids,
            "acknowledged_control_event_ids": acknowledged_control_ids,
            "acknowledged_control_events": acknowledged_control_events,
            "applied_control_event_ids": applied_control_ids,
            "applied_events": [dict(event) for _, event, _, _ in validated],
            "applied_control_events": applied_control_events,
            "applied_native_damage": damage,
            "world_target_health_before": old_health,
            "world_target_health_after": float(target.health),
            "world_target_max_health": max_health,
            "root_break_semantics": "unimplemented",
        }

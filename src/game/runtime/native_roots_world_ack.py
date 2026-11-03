"""Apply source-native Roots control receipts to the real gsim 2D world.

Rust decides the binary hit and exact DoT lifetime. This adapter only applies
the resulting generic root state to gsim's movement controller and binds the
control-event IDs to the same before/after world ACK as native damage.
"""
from __future__ import annotations

from typing import Mapping

from .go_native_world_damage_ack import (
    GsimNativeDamageWorldApplier,
    NativeDamageWorldApplicationError,
)
from .native_step_protocol import snapshot_gsim_world, state_hash


class GsimNativeRootsWorldApplier:
    def __init__(self, runtime):
        self._runtime = runtime
        self._damage = GsimNativeDamageWorldApplier(runtime)
        self._next_control_event = 1
        self._last_control_time_ns = -1

    def apply(self, tick: Mapping, response: Mapping) -> dict:
        if not isinstance(tick, Mapping) or not isinstance(response, Mapping):
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_PAYLOAD_INVALID")
        events = response.get("native_control_events", [])
        if not isinstance(events, list):
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_EVENTS_INVALID")
        clock_ns = tick.get("native_clock_ns")
        if type(clock_ns) is not int or clock_ns < 0:
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_CLOCK_INVALID")
        target_id = tick.get("selected_target_id")
        if not isinstance(target_id, str) or target_id not in self._runtime.targets:
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_TARGET_MISSING")
        target = self._runtime.targets[target_id]
        previous_world_tick_ns = self._damage._last_world_tick_ns

        # Validate the entire control batch before the damage applier mutates HP.
        # Attempt/apply are emitted synchronously by the same native cast; expiry
        # is emitted only by the Rust DoT's real aura-expiration callback.
        last_id = self._next_control_event - 1
        last_time = self._last_control_time_ns
        shadow_root_expiry = target.active_controls.get("root")
        ids: list[str] = []
        copied: list[dict] = []
        for event in events:
            if not isinstance(event, Mapping):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_EVENT_MALFORMED")
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id.startswith("native-control-"):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_EVENT_ID_MISSING")
            try:
                ordinal = int(event_id.removeprefix("native-control-"))
            except ValueError as exc:
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_EVENT_ID_INVALID") from exc
            timestamp = event.get("native_time_ns")
            kind = event.get("event_kind")
            control_id = event.get("control_id")
            landed = event.get("landed")
            expiry_ns = event.get("expires_at_ns")
            action_id = event.get("source_action_id")
            rank_spell_id = event.get("source_rank_spell_id")
            label = event.get("native_target_label")
            if (ordinal != last_id + 1 or event_id != f"native-control-{ordinal}"
                    or type(timestamp) is not int
                    or timestamp < previous_world_tick_ns or timestamp < last_time
                    or timestamp > clock_ns
                    or kind not in ("attempt", "apply", "expire")
                    or control_id != "root"
                    or type(event.get("native_target_index")) is not int
                    or event["native_target_index"] != 0
                    or type(event.get("native_target_unit_index")) is not int
                    or event["native_target_unit_index"] != 0
                    or label != "Target"
                    or type(rank_spell_id) is not int or rank_spell_id <= 0
                    or not isinstance(action_id, str) or action_id != f"spell:{rank_spell_id}"):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_SOURCE_EVENT_INVALID")
            if not target.alive and kind != "expire":
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_TARGET_ALREADY_DEAD")
            if kind == "attempt":
                if type(landed) is not bool or expiry_ns is not None:
                    raise NativeDamageWorldApplicationError("WORLD_CONTROL_ATTEMPT_INVALID")
            elif kind == "apply":
                if (landed is not True or type(expiry_ns) is not int
                        or expiry_ns <= timestamp):
                    raise NativeDamageWorldApplicationError("WORLD_CONTROL_APPLY_INVALID")
                shadow_root_expiry = max(
                    float(expiry_ns) / 1e9,
                    float(shadow_root_expiry or 0.0),
                )
            else:
                if (landed is not None or expiry_ns is not None
                        or (shadow_root_expiry is None and target.alive)):
                    raise NativeDamageWorldApplicationError("WORLD_CONTROL_EXPIRE_WITHOUT_ACTIVE_ROOT")
                shadow_root_expiry = None
            last_id = ordinal
            last_time = timestamp
            ids.append(event_id)
            copied.append(dict(event))

        # A landed binary attempt must synchronously produce the native DoT gain;
        # a miss must not produce a gain at that same native timestamp.
        for event in copied:
            if event["event_kind"] != "attempt":
                continue
            same_cast = [
                candidate for candidate in copied
                if candidate["source_action_id"] == event["source_action_id"]
                and candidate["native_time_ns"] == event["native_time_ns"]
            ]
            gains = [candidate for candidate in same_cast if candidate["event_kind"] == "apply"]
            if bool(event["landed"]) != bool(gains):
                raise NativeDamageWorldApplicationError("WORLD_CONTROL_HIT_GAIN_MISMATCH")

        ack = self._damage.apply(tick, response)
        before_control_hash = ack["world_after_sha256"]
        control_changed = False
        for event in copied:
            kind = event["event_kind"]
            if kind == "attempt":
                continue
            if kind == "apply":
                # Preserve the source control state even if a simultaneous
                # lethal native hit has already made the world mob inert.
                expiry_s = float(event["expires_at_ns"]) / 1e9
                old_expiry = target.active_controls.get("root")
                new_expiry = max(expiry_s, float(old_expiry or 0.0))
                if old_expiry != new_expiry:
                    target.active_controls["root"] = new_expiry
                    control_changed = True
                self._runtime._control_behaviors[(target_id, "root")] = {
                    "prevents_enemy_actions": False,
                    "breaks_on_damage": False,
                    "break_chance_on_damage": None,
                }
                if target.alive and self._runtime.multi_target:
                    self._runtime._freeze_enemy_approach(target_id)
            else:
                old_expiry = target.active_controls.pop("root", None)
                self._runtime._control_behaviors.pop((target_id, "root"), None)
                if old_expiry is not None:
                    control_changed = True
                    if target.alive and self._runtime.multi_target:
                        self._runtime._begin_enemy_approach(target_id)

        after_control_hash = state_hash(snapshot_gsim_world(self._runtime))
        if control_changed and after_control_hash == before_control_hash:
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_MUTATION_NOT_ACKNOWLEDGED")
        if not control_changed and after_control_hash != before_control_hash:
            raise NativeDamageWorldApplicationError("WORLD_CONTROL_UNEXPECTED_MUTATION")
        ack["world_after_sha256"] = after_control_hash
        ack["applied_control_event_ids"] = ids
        ack["applied_control_events"] = [
            {**event, "gsim_target_id": target_id} for event in copied
        ]
        active = "root" in target.active_controls
        expiry_ns = (int(round(float(target.active_controls["root"]) * 1e9))
                     if active else None)
        ack["world_control_state"] = {
            "target_id": target_id,
            "control_id": "root",
            "native_target_index": 0,
            "native_target_unit_index": 0,
            "native_target_label": "Target",
            "active": active,
            "expires_at_ns": expiry_ns,
        }
        self._next_control_event = last_id + 1
        self._last_control_time_ns = last_time
        self._damage._last_native_time_ns = max(
            self._damage._last_native_time_ns, last_time,
        )
        return ack

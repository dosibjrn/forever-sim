"""Read a native Paladin L20 actor/weapon context for the active P3 producer.

MythicSim owns the race/class/level stats, resource maxima and equipped
weapon. This module only forwards the query and replaces *existing* P3
runtime fields; it does not calculate Warcraft stats or infer legality.
The returned context is not a full native PreparedV2 actor.
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Callable


class NativePlayerContextError(ValueError):
    """The selected engine refused or did not supply the requested context."""


def query_native_player_context(
    binary: str | Path, class_key: str, level: int, *,
    race: str | None = None, runner: Callable = subprocess.run,
) -> dict:
    command = [str(binary), "player-context", "--class", str(class_key),
               "--level", str(int(level))]
    if race is not None:
        command.extend(("--race", str(race)))
    try:
        completed = runner(command, capture_output=True, text=True,
                           timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_EXECUTION_FAILED") from exc
    if completed.returncode != 0:
        # Rust may emit a structured source refusal even when its CLI exits
        # nonzero. Preserve the authoritative reason before the transport
        # fallback; a refusal remains a refusal, never a valid P3 candidate.
        try:
            failure = json.loads(completed.stdout)
        except (ValueError, TypeError):
            failure = None
        if isinstance(failure, dict) and failure.get("status") == "refused":
            refusal = failure.get("refusal")
            code = refusal.get("code") if isinstance(refusal, dict) else None
            raise NativePlayerContextError(
                "P3_NATIVE_PLAYER_CONTEXT_REFUSED:" + str(code or "UNKNOWN"))
        raise NativePlayerContextError(
            "P3_NATIVE_PLAYER_CONTEXT_EXECUTION_FAILED:" +
            str(completed.stderr or "")[-400:])
    try:
        response = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_INVALID_JSON") from exc
    if not isinstance(response, dict):
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_INVALID_RESPONSE")
    if response.get("status") == "refused":
        refusal = response.get("refusal") or {}
        code = refusal.get("code") if isinstance(refusal, dict) else None
        raise NativePlayerContextError(
            "P3_NATIVE_PLAYER_CONTEXT_REFUSED:" + str(code or "UNKNOWN"))
    if (response.get("status") != "ok"
            or response.get("class") != str(class_key).lower()
            or type(response.get("level")) is not int
            or response["level"] != int(level)
            or (race is not None and response.get("race") != str(race).lower())
            or response.get("context_kind") !=
                "source_backed_baseline_context_not_full_native_sim_actor"
            or not isinstance(response.get("source_context_id"), str)
            or not response["source_context_id"]
            or not isinstance(response.get("source_scope"), str)
            or not isinstance(response.get("provenance"), dict)):
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_IDENTITY_INVALID")
    for group, keys in (
        ("base_stats", ("strength", "agility", "stamina", "intellect",
                        "spirit", "attack_power", "armor")),
        ("resources", ("max_health", "max_mana")),
        ("weapon", ("weapon_dps", "weapon_speed_s", "weapon_damage_min",
                    "weapon_damage_max")),
    ):
        values = response.get(group)
        if not isinstance(values, dict):
            raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_FIELDS_UNAVAILABLE")
        for key in keys:
            value = values.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_FIELDS_UNAVAILABLE")
    weapon = response["weapon"]
    if (type(weapon.get("item_id")) is not int
            or not isinstance(response.get("race"), str)
            or not response["race"]):
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_FIELDS_UNAVAILABLE")
    return response


def apply_native_player_context(ir, context: dict):
    """Substitute native values into existing live P3 runtime fields.

    Keep unresolved regen/crit and the legacy executor's limitations visible;
    native context facts are not proof of a prepared level-20 Rust actor.
    """
    from src.game.model.ir import WeaponDamageEffect

    if context.get("status") != "ok":
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_NOT_OK")
    identity = str(context["source_context_id"])
    fact = {"authority": "mythicsim_native_player_context",
            "source_context_id": identity,
            "source_scope": context["source_scope"],
            "provenance": context["provenance"]}
    base = dict(ir.actor.base_stats)
    base.update({key: float(value) for key, value in context["base_stats"].items()})
    actor = replace(
        ir.actor, base_stats=base,
        state_status="native_source_backed_baseline_context_not_full_sim_actor",
        provenance=(fact,),
        metadata={**dict(ir.actor.metadata),
                  "base_stats_are_zero_proxy": False,
                  "race_key": context["race"],
                  "native_player_context_id": identity,
                  "native_player_context_kind": context["context_kind"],
                  "weapon_speed_s": float(context["weapon"]["weapon_speed_s"])})
    resources = []
    for resource in ir.resources:
        key = {"health": "max_health", "mana": "max_mana"}.get(resource.id)
        if key is None:
            resources.append(resource)
            continue
        amount = float(context["resources"][key])
        resources.append(replace(
            resource, initial_amount=amount, capacity=amount,
            state_status="native_source_backed_capacity_legacy_regeneration",
            provenance=(fact,),
            metadata={**dict(resource.metadata),
                      "native_player_context_id": identity}))
    weapon = context["weapon"]
    attack_sources = {}
    attacks = []
    for attack in ir.auto_attacks:
        if attack.owner_actor_id != ir.actor.id:
            attacks.append(attack)
            continue
        source = replace(attack.damage_source, flat_dps=float(weapon["weapon_dps"]))
        attack_sources[attack.id] = source
        attacks.append(replace(
            attack, swing_time_s=float(weapon["weapon_speed_s"]),
            damage_source=source, provenance=(fact,),
            metadata={**dict(attack.metadata),
                      "native_equipped_weapon_item_id": weapon["item_id"]}))
    # The old source provider shares one weapon damage source across auto and
    # weapon-based actions. Preserve that identity when replacing the proxy.
    actions = []
    for action in ir.actions:
        effects = []
        for effect in action.effects:
            if isinstance(effect, WeaponDamageEffect) and attack_sources:
                effects.append(replace(
                    effect, damage_source=next(iter(attack_sources.values())),
                    weapon_damage_time_s=float(weapon["weapon_speed_s"]),
                    provenance=tuple(effect.provenance) + (fact,)))
            else:
                effects.append(effect)
        actions.append(replace(action, effects=tuple(effects)))
    unsupported = tuple(ir.unsupported_semantics) + ({
        "code": "native_player_context_not_full_native_sim_actor",
        "source_context_id": identity,
        "unresolved_fields": list(context.get("unsupported_fields") or ()),
        "legacy_resource_regeneration_retained": True,
    },)
    return replace(
        ir, actor=actor, resources=tuple(resources), auto_attacks=tuple(attacks),
        actions=tuple(actions), unsupported_semantics=unsupported,
        source_facts=tuple(ir.source_facts) + (fact,))

from __future__ import annotations

"""Project rich legacy decision rows into backend-neutral gameplay collections.

This module is an adapter at the legacy boundary, not a simulation authority.
It translates facts already present in a legacy row into the generic product
vocabulary (Actor / Resource / Action / Policy / Mode) without inventing
runtime values that the legacy publication did not expose.

G02 starts with Druid because its current rows already exercise multiple combat
modes and resource families.  Future adapters may be added here while legacy is
kept as an oracle; the generic runtime itself must never depend on this module.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("→", " to ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "action"


def _rotation_steps(raw: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    steps = raw.get("rotation_steps")
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        out = []
        for step in steps:
            if isinstance(step, Mapping):
                out.append(dict(step))
            elif step:
                out.append({"label": str(step)})
        if out:
            return out
    label = raw.get("rotation") or raw.get("policy")
    if label:
        parts = [p.strip() for p in str(label).split("→") if p.strip()]
        return [{"label": p} for p in parts] or [{"label": str(label)}]
    return []


def _druid_resources(level: int, profile: str) -> tuple[dict[str, Any], ...]:
    """Resources explicitly evidenced by the selected legacy gameplay profile."""
    if profile == "cat":
        return (
            {
                "id": "energy", "kind": "resource", "scope": "actor", "active": True,
                "roles": ["action_cost", "regenerating_combat_resource"],
                "value_status": "not_published_by_legacy_row", "projection": "legacy_semantic",
            },
            {
                "id": "combo_points", "kind": "resource", "scope": "target", "active": True,
                "roles": ["builder_finisher_state"],
                "value_status": "not_published_by_legacy_row", "projection": "legacy_semantic",
            },
        )
    if profile == "bear":
        return ({
            "id": "rage", "kind": "resource", "scope": "actor", "active": True,
            "roles": ["action_cost", "event_generated_combat_resource"],
            "value_status": "not_published_by_legacy_row", "projection": "legacy_semantic",
        },)
    return ({
        "id": "mana", "kind": "resource", "scope": "actor", "active": True,
        "roles": ["spell_cost", "healing", "recovery"],
        "value_status": "not_published_by_legacy_row", "projection": "legacy_semantic",
    },)


def _druid_modes(level: int, profile: str) -> tuple[dict[str, Any], ...]:
    mode_id = profile if profile in {"cat", "bear"} else "caster"
    return ({
        "id": mode_id,
        "kind": "combat_mode",
        "active": True,
        "projection": "legacy_selected_profile",
    },)

def _generic_actions(raw: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for index, step in enumerate(_rotation_steps(raw)):
        label = str(step.get("label") or f"Action {index + 1}")
        base = _slug(label)
        used[base] = used.get(base, 0) + 1
        action_id = base if used[base] == 1 else f"{base}_{used[base]}"
        record = {
            "id": action_id,
            "kind": "policy_action",
            "label": label,
            "projection": "legacy_rotation_step",
        }
        if isinstance(step.get("icon"), Mapping):
            record["icon"] = dict(step["icon"])
        out.append(record)
    return tuple(out)


def _policy(raw: Mapping[str, Any], actions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    label = raw.get("policy") or raw.get("rotation")
    return {
        "kind": "priority_policy",
        "label": label,
        "priority": [
            {
                "order": index + 1,
                "action_id": str(action.get("id")),
                "condition": "legacy_policy_condition_not_structured",
            }
            for index, action in enumerate(actions)
        ],
        "structure_status": "projected_from_legacy_rotation",
    }


@dataclass(frozen=True)
class LegacyGameplayProjection:
    actors: tuple[Mapping[str, Any], ...] = ()
    resources: tuple[Mapping[str, Any], ...] = ()
    actions: tuple[Mapping[str, Any], ...] = ()
    policy: Mapping[str, Any] | None = None
    modes: tuple[Mapping[str, Any], ...] = ()


def project_legacy_gameplay(
    *,
    class_name: str,
    row: Mapping[str, Any],
) -> LegacyGameplayProjection:
    """Return backend-neutral collections already knowable from a legacy row.

    This adapter is deliberately fail-closed.  Classes not yet migrated return
    empty collections rather than class-shaped guesses.
    """
    class_key = str(class_name).strip().lower()
    if class_key != "druid":
        return LegacyGameplayProjection(policy={
            "kind": "priority_policy",
            "label": row.get("policy") or row.get("rotation"),
            "priority": [],
            "structure_status": "not_projected",
        })

    level = int(row.get("level", 0) or 0)
    profile = str(row.get("combat_profile") or row.get("profile") or "caster").strip().lower()
    actions = _generic_actions(row)
    resources = _druid_resources(level, profile)
    modes = _druid_modes(level, profile)
    active_mode = next((str(mode["id"]) for mode in modes if mode.get("active")), None)
    gear_stats = dict(row.get("gear_stats") or {})
    actor = {
        "id": "player",
        "kind": "player",
        "class_name": "druid",
        "level": level,
        "active_mode": active_mode,
        "resource_ids": [str(r["id"]) for r in resources],
        "action_ids": [str(a["id"]) for a in actions],
        "stats": {
            key: gear_stats.get(key)
            for key in (
                "strength", "agility", "stamina", "intellect", "spirit",
                "spell_power", "healing", "armor", "attack_power", "mp5",
                "weapon_dps", "weapon_speed",
            )
            if gear_stats.get(key) is not None
        },
        "projection": "legacy_route_row",
    }
    return LegacyGameplayProjection(
        actors=(actor,),
        resources=resources,
        actions=actions,
        policy=_policy(row, actions),
        modes=modes,
    )

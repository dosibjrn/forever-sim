from __future__ import annotations

"""Forever source facts normalized into generic direct-spell Game IR."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.game.model.ir import (
    ActionDefinition,
    ActorDefinition,
    DamageEffect,
    GameIRSlice,
    ResourceCost,
    ResourceDefinition,
)
from src.game.model.overlay import FieldOverlay, apply_numeric_field_overlays


# Shared WoW spell GCD semantic used by the current Forever models.  G04 keeps
# this as a ruleset semantic separate from spell tooltip facts; G06 will make
# tuning/provenance overlays richer without changing the generic Action shape.
DEFAULT_FOREVER_SPELL_GCD_S = 1.5


@dataclass(frozen=True)
class DirectSpellSourceFact:
    family_key: str
    name: str
    source_id: int
    required_level: int
    resource_id: str
    resource_cost: float
    cast_time_s: float
    damage_min: float
    damage_max: float
    spell_power_coefficient: float
    school: str
    source_url: str
    provenance: Mapping[str, Any]


def normalize_direct_spell_slice(
    *,
    ruleset: str,
    class_key: str,
    fact: DirectSpellSourceFact,
    actor: ActorDefinition | None = None,
    resource: ResourceDefinition | None = None,
    overlays: Sequence[FieldOverlay] = (),
) -> GameIRSlice:
    """Normalize one source fact without introducing class-shaped mechanics.

    G05 may supply source-backed actor/resource starting state.  Without it the
    normalizer remains usable for definition-only slices.
    """
    actor = actor or ActorDefinition(
        id="player",
        actor_type="player",
        metadata={"class_key": str(class_key)},
    )
    resource = resource or ResourceDefinition(
        id=fact.resource_id,
        name=fact.resource_id.replace("_", " ").title(),
        owner_actor_id=actor.id,
        scope="actor",
        state_status="definition_only_until_resource_ir_authority",
    )
    if resource.id != fact.resource_id:
        raise ValueError(f"direct spell resource mismatch: {resource.id!r} != {fact.resource_id!r}")
    if resource.owner_actor_id != actor.id:
        raise ValueError("direct spell actor/resource owner mismatch")
    source = {
        "provider": "wowhead",
        "entity_kind": "spell",
        "entity_id": int(fact.source_id),
        "url": str(fact.source_url),
        **dict(fact.provenance),
    }
    raw_source_fact = {
        "fact_kind": "direct_spell_tooltip",
        "family_key": fact.family_key,
        "name": fact.name,
        "source_id": int(fact.source_id),
        "required_level": int(fact.required_level),
        "resource_id": fact.resource_id,
        "resource_cost": float(fact.resource_cost),
        "cast_time_s": float(fact.cast_time_s),
        "damage_min": float(fact.damage_min),
        "damage_max": float(fact.damage_max),
        "spell_power_coefficient": float(fact.spell_power_coefficient),
        "school": str(fact.school).lower(),
        "source": dict(source),
    }
    numeric_fields, field_trace = apply_numeric_field_overlays(
        {
            "effects.0.base_min": float(fact.damage_min),
            "effects.0.base_max": float(fact.damage_max),
            "effects.0.spell_power_coefficient": float(fact.spell_power_coefficient),
            "cast_time_s": float(fact.cast_time_s),
            "costs.0.amount": float(fact.resource_cost),
        },
        tuple(overlays),
    )
    field_trace = {
        path: tuple(
            ({**dict(row), "provenance": [dict(source)]} if row.get("stage") == "raw_source" else dict(row))
            for row in rows
        )
        for path, rows in field_trace.items()
    }
    unsupported = tuple(
        marker
        for overlay in overlays
        for marker in overlay.unsupported_semantics
    )
    damage_trace = {
        key.split("effects.0.", 1)[1]: trace
        for key, trace in field_trace.items()
        if key.startswith("effects.0.")
    }
    action = ActionDefinition(
        id=f"{fact.family_key}:{fact.source_id}",
        family_key=fact.family_key,
        name=fact.name,
        owner_actor_id=actor.id,
        requirements=(
            {"kind": "minimum_level", "value": int(fact.required_level)},
        ),
        costs=(ResourceCost(resource_id=fact.resource_id, amount=numeric_fields["costs.0.amount"]),),
        cast_time_s=numeric_fields["cast_time_s"],
        gcd_s=DEFAULT_FOREVER_SPELL_GCD_S,
        cooldown_s=0.0,
        effects=(
            DamageEffect(
                effect_type="damage",
                school=str(fact.school).lower(),
                target="enemy",
                base_min=numeric_fields["effects.0.base_min"],
                base_max=numeric_fields["effects.0.base_max"],
                spell_power_coefficient=numeric_fields["effects.0.spell_power_coefficient"],
                field_provenance=damage_trace,
                unsupported_semantics=unsupported,
            ),
        ),
        provenance=(source,),
        metadata={
            "source_fact_status": "source_backed_raw_tooltip",
            "gcd_semantic": "forever_shared_spell_gcd",
            "cooldown_semantic": "no_cooldown_in_source_fact",
            "tuning_status": ("raw_plus_dated_overlays" if overlays else "raw_source_fact_no_active_overlay"),
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in field_trace.items()},
            "unsupported_semantics": [dict(x) for x in unsupported],
        },
    )
    return GameIRSlice(
        id=f"{ruleset}:{class_key}:{fact.family_key}:rank@{fact.required_level}",
        ruleset=str(ruleset),
        actor=actor,
        resources=(resource,),
        actions=(action,),
        source_facts=(raw_source_fact,),
        overlays=tuple(x.as_dict() for x in overlays),
        unsupported_semantics=unsupported,
        provenance={
            "source_backed": True,
            "normalizer": "generic_direct_spell",
            "class_key": str(class_key),
            "source_family": fact.family_key,
        },
    )

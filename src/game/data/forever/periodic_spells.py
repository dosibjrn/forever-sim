from __future__ import annotations

"""Forever source facts normalized into generic direct+periodic Actions."""

from dataclasses import dataclass
from typing import Any, Mapping

from src.game.model.ir import (
    ActionDefinition,
    ActorDefinition,
    DamageEffect,
    PeriodicEffect,
    ResourceCost,
    ResourceDefinition,
)
from .direct_spells import DEFAULT_FOREVER_SPELL_GCD_S


@dataclass(frozen=True)
class DirectPeriodicSpellSourceFact:
    family_key: str
    name: str
    source_id: int
    required_level: int
    resource_id: str
    resource_cost: float
    direct_min: float
    direct_max: float
    direct_spell_power_coefficient: float
    periodic_total: float
    periodic_duration_s: float
    tick_interval_s: float
    periodic_spell_power_coefficient_per_tick: float
    school: str
    source_url: str
    provenance: Mapping[str, Any]
    refresh_rule: str = "replace"


def normalize_direct_periodic_action(
    *,
    fact: DirectPeriodicSpellSourceFact,
    actor: ActorDefinition,
    resource: ResourceDefinition,
) -> tuple[ActionDefinition, dict[str, Any]]:
    """Normalize one source-backed instant direct+periodic spell.

    Refresh is data on the periodic effect. The generic runtime interprets the
    rule; this source adapter never implements class-specific ticking logic.
    """
    if resource.id != fact.resource_id:
        raise ValueError(f"periodic spell resource mismatch: {resource.id!r} != {fact.resource_id!r}")
    source = {
        "provider": "wowhead",
        "entity_kind": "spell",
        "entity_id": int(fact.source_id),
        "url": str(fact.source_url),
        **dict(fact.provenance),
    }
    raw = {
        "fact_kind": "direct_periodic_spell_tooltip",
        "family_key": fact.family_key,
        "name": fact.name,
        "source_id": int(fact.source_id),
        "required_level": int(fact.required_level),
        "resource_id": fact.resource_id,
        "resource_cost": float(fact.resource_cost),
        "direct_min": float(fact.direct_min),
        "direct_max": float(fact.direct_max),
        "direct_spell_power_coefficient": float(fact.direct_spell_power_coefficient),
        "periodic_total": float(fact.periodic_total),
        "periodic_duration_s": float(fact.periodic_duration_s),
        "tick_interval_s": float(fact.tick_interval_s),
        "periodic_spell_power_coefficient_per_tick": float(fact.periodic_spell_power_coefficient_per_tick),
        "school": str(fact.school).lower(),
        "refresh_rule": fact.refresh_rule,
        "source": dict(source),
    }
    aura_id = f"{fact.family_key}:{fact.source_id}:aura"
    action = ActionDefinition(
        id=f"{fact.family_key}:{fact.source_id}",
        family_key=fact.family_key,
        name=fact.name,
        owner_actor_id=actor.id,
        requirements=({"kind": "minimum_level", "value": int(fact.required_level)},),
        costs=(ResourceCost(resource_id=fact.resource_id, amount=float(fact.resource_cost)),),
        cast_time_s=0.0,
        gcd_s=DEFAULT_FOREVER_SPELL_GCD_S,
        cooldown_s=0.0,
        effects=(
            DamageEffect(
                effect_type="damage",
                school=str(fact.school).lower(),
                target="enemy",
                base_min=float(fact.direct_min),
                base_max=float(fact.direct_max),
                spell_power_coefficient=float(fact.direct_spell_power_coefficient),
                field_provenance={"source": (dict(source),)},
            ),
            PeriodicEffect(
                effect_type="periodic_damage",
                school=str(fact.school).lower(),
                target="enemy",
                aura_id=aura_id,
                total_base_damage=float(fact.periodic_total),
                duration_s=float(fact.periodic_duration_s),
                tick_interval_s=float(fact.tick_interval_s),
                spell_power_coefficient_per_tick=float(fact.periodic_spell_power_coefficient_per_tick),
                refresh_rule=str(fact.refresh_rule),
                field_provenance={"source": (dict(source),)},
            ),
        ),
        provenance=(source,),
        metadata={
            "source_fact_status": "source_backed_raw_tooltip",
            "gcd_semantic": "forever_shared_spell_gcd",
            "cooldown_semantic": "no_cooldown_in_source_fact",
            "periodic_semantic": "source_backed_duration_tick_interval_and_total",
            "refresh_semantic": str(fact.refresh_rule),
        },
    )
    return action, raw

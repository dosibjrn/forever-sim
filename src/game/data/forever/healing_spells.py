from __future__ import annotations

"""Forever source facts normalized into reusable self-healing Game IR Actions."""

from dataclasses import dataclass
from typing import Any, Mapping

from src.game.model.ir import (
    ActionDefinition,
    ActorDefinition,
    HealEffect,
    PeriodicHealEffect,
    ResourceCost,
    ResourceDefinition,
)
from .direct_spells import DEFAULT_FOREVER_SPELL_GCD_S


@dataclass(frozen=True)
class DirectHealSourceFact:
    family_key: str
    name: str
    rank_level: int
    resource_id: str
    resource_cost: float
    cast_time_s: float
    heal_min: float
    heal_max: float
    spell_power_coefficient: float
    source_url: str
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class PeriodicHealSourceFact:
    family_key: str
    name: str
    rank_level: int
    resource_id: str
    resource_cost: float
    total_heal: float
    duration_s: float
    tick_interval_s: float
    spell_power_coefficient_per_tick: float
    source_url: str
    provenance: Mapping[str, Any]
    refresh_rule: str = "replace"


def _source(family_key: str, rank_level: int, source_url: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": "wowhead",
        "entity_kind": "spell_rank_family",
        "family_key": str(family_key),
        "rank_level": int(rank_level),
        "url": str(source_url),
        **dict(provenance),
    }


def normalize_direct_heal_action(
    *, fact: DirectHealSourceFact, actor: ActorDefinition, mana_resource: ResourceDefinition,
    health_resource: ResourceDefinition,
) -> tuple[ActionDefinition, dict[str, Any]]:
    if mana_resource.id != fact.resource_id:
        raise ValueError("direct heal resource mismatch")
    if health_resource.owner_actor_id != actor.id:
        raise ValueError("direct heal health owner mismatch")
    source = _source(fact.family_key, fact.rank_level, fact.source_url, fact.provenance)
    raw = {
        "fact_kind": "direct_heal_tooltip",
        "family_key": fact.family_key,
        "name": fact.name,
        "rank_level": int(fact.rank_level),
        "resource_id": fact.resource_id,
        "resource_cost": float(fact.resource_cost),
        "cast_time_s": float(fact.cast_time_s),
        "heal_min": float(fact.heal_min),
        "heal_max": float(fact.heal_max),
        "spell_power_coefficient": float(fact.spell_power_coefficient),
        "source": dict(source),
    }
    action = ActionDefinition(
        id=f"{fact.family_key}:rank@{int(fact.rank_level)}",
        family_key=fact.family_key,
        name=fact.name,
        owner_actor_id=actor.id,
        requirements=({"kind": "minimum_level", "value": int(fact.rank_level)},),
        costs=(ResourceCost(resource_id=fact.resource_id, amount=float(fact.resource_cost)),),
        cast_time_s=float(fact.cast_time_s),
        gcd_s=DEFAULT_FOREVER_SPELL_GCD_S,
        cooldown_s=0.0,
        effects=(HealEffect(
            effect_type="heal",
            target="self",
            resource_id=health_resource.id,
            base_min=float(fact.heal_min),
            base_max=float(fact.heal_max),
            spell_power_coefficient=float(fact.spell_power_coefficient),
            field_provenance={"source": (dict(source),)},
        ),),
        provenance=(dict(source),),
        metadata={
            "source_fact_status": "source_backed_rank_family",
            "gcd_semantic": "forever_shared_spell_gcd",
            "recovery_family": True,
        },
    )
    return action, raw


def normalize_periodic_heal_action(
    *, fact: PeriodicHealSourceFact, actor: ActorDefinition, mana_resource: ResourceDefinition,
    health_resource: ResourceDefinition,
) -> tuple[ActionDefinition, dict[str, Any]]:
    if mana_resource.id != fact.resource_id:
        raise ValueError("periodic heal resource mismatch")
    source = _source(fact.family_key, fact.rank_level, fact.source_url, fact.provenance)
    raw = {
        "fact_kind": "periodic_heal_tooltip",
        "family_key": fact.family_key,
        "name": fact.name,
        "rank_level": int(fact.rank_level),
        "resource_id": fact.resource_id,
        "resource_cost": float(fact.resource_cost),
        "total_heal": float(fact.total_heal),
        "duration_s": float(fact.duration_s),
        "tick_interval_s": float(fact.tick_interval_s),
        "spell_power_coefficient_per_tick": float(fact.spell_power_coefficient_per_tick),
        "refresh_rule": fact.refresh_rule,
        "source": dict(source),
    }
    action = ActionDefinition(
        id=f"{fact.family_key}:rank@{int(fact.rank_level)}",
        family_key=fact.family_key,
        name=fact.name,
        owner_actor_id=actor.id,
        requirements=({"kind": "minimum_level", "value": int(fact.rank_level)},),
        costs=(ResourceCost(resource_id=fact.resource_id, amount=float(fact.resource_cost)),),
        cast_time_s=0.0,
        gcd_s=DEFAULT_FOREVER_SPELL_GCD_S,
        cooldown_s=0.0,
        effects=(PeriodicHealEffect(
            effect_type="periodic_heal",
            target="self",
            resource_id=health_resource.id,
            aura_id=f"{fact.family_key}:rank@{int(fact.rank_level)}:aura",
            total_base_heal=float(fact.total_heal),
            duration_s=float(fact.duration_s),
            tick_interval_s=float(fact.tick_interval_s),
            spell_power_coefficient_per_tick=float(fact.spell_power_coefficient_per_tick),
            refresh_rule=fact.refresh_rule,
            field_provenance={"source": (dict(source),)},
        ),),
        provenance=(dict(source),),
        metadata={
            "source_fact_status": "source_backed_rank_family",
            "gcd_semantic": "forever_shared_spell_gcd",
            "recovery_family": True,
        },
    )
    return action, raw

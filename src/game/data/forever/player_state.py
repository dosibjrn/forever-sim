from __future__ import annotations

"""Generic normalization of source-backed player starting state.

The source/provider layer may know race/class identity.  The resulting IR only
contains reusable Actor/Resource semantics.  No combat scoring lives here.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from src.game.model.ir import ActorDefinition, ResourceDefinition


@dataclass(frozen=True)
class PlayerStartingStateSourceFact:
    class_key: str
    race_key: str
    level: int
    base_stats: Mapping[str, float]
    base_mana: float
    stat_provenance: Mapping[str, Any]
    mana_provenance: Mapping[str, Any]
    health_capacity: float | None = None
    health_provenance: Mapping[str, Any] | None = None


def classic_mana_bonus_from_intellect(intellect: float) -> float:
    """Classic/Forever inherited max-mana contribution from total Intellect.

    The first 20 Intellect contribute 1 mana each; Intellect above 20 contributes
    15 mana each.  This is the same generic player-state semantic used by the
    inherited classic ruleset and is kept outside any class provider.
    """
    value = max(0.0, float(intellect))
    base = min(20.0, value)
    return base + max(0.0, value - 20.0) * 15.0


def normalize_player_starting_state(
    fact: PlayerStartingStateSourceFact,
    *,
    actor_id: str = "player",
    resource_id: str = "mana",
) -> tuple[ActorDefinition, ...]:
    stats = {str(k): float(v) for k, v in dict(fact.base_stats).items()}
    intellect = float(stats.get("intellect", 0.0))
    intellect_mana = classic_mana_bonus_from_intellect(intellect)
    capacity = float(fact.base_mana) + intellect_mana

    actor = ActorDefinition(
        id=str(actor_id),
        actor_type="player",
        base_stats=stats,
        state_status="source_backed_starting_state",
        provenance=(dict(fact.stat_provenance),),
        metadata={
            "class_key": str(fact.class_key),
            "race_key": str(fact.race_key),
            "level": int(fact.level),
        },
    )
    mana = ResourceDefinition(
        id=str(resource_id),
        name="Mana",
        owner_actor_id=actor.id,
        scope="actor",
        state_status="source_backed_starting_state",
        initial_amount=capacity,
        capacity=capacity,
        provenance=(dict(fact.mana_provenance),),
        metadata={
            "base_mana": float(fact.base_mana),
            "base_intellect": intellect,
            "intellect_mana_bonus": intellect_mana,
            "capacity_formula": "base_mana + classic_mana_bonus_from_intellect(base_intellect)",
            "gear_included": False,
            "talents_included": False,
        },
    )
    resources = [mana]
    if fact.health_capacity is not None:
        health = max(1.0, float(fact.health_capacity))
        resources.append(ResourceDefinition(
            id="health",
            name="Health",
            owner_actor_id=actor.id,
            scope="actor",
            state_status="qualified_proxy_starting_state",
            initial_amount=health,
            capacity=health,
            provenance=((dict(fact.health_provenance) if fact.health_provenance is not None else {}),),
            metadata={
                "capacity_formula": "shared representative_player_hp proxy",
                "gear_included": False,
                "talents_included": False,
                "fidelity": "qualified_classic_proxy_until_player_health_authority",
            },
        ))
    return (actor, *resources)

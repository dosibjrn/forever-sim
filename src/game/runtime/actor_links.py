from __future__ import annotations

"""Generic cross-actor stat inheritance and active-companion modifiers."""

from collections.abc import Mapping
from src.game.model import ActorLinkModifier
from .state import ActorState


def apply_actor_link_modifiers(actors: Mapping[str, ActorState], modifiers: tuple[ActorLinkModifier, ...]) -> tuple[dict, ...]:
    """Resolve immutable source-stat snapshots onto target ActorStates at spawn.

    Supports any owner/companion pair, without importing ruleset-specific code.
    This is spawn-time transfer, not a dynamic aura or summon/despawn system (G36).
    """
    starting_stats = {key: dict(actor.stats) for key, actor in actors.items()}
    applied: list[dict] = []
    for mod in modifiers:
        if mod.source_actor_id not in actors or mod.target_actor_id not in actors:
            raise ValueError(f"actor link has unknown owner: {mod.id}")
        if mod.requires_actor_id is not None and mod.requires_actor_id not in actors:
            continue
        source = starting_stats[mod.source_actor_id]
        if not mod.source_stat_ids or any(key not in source for key in mod.source_stat_ids):
            raise ValueError(f"actor link missing source stat: {mod.id}")
        sampled = max(float(source[key]) for key in mod.source_stat_ids)
        target = actors[mod.target_actor_id]
        before = float(target.stats.get(mod.target_stat_id, 0.0))
        delta = sampled * float(mod.coefficient)
        if mod.operation == "add_scaled":
            after = before + delta
        elif mod.operation == "set_scaled":
            after = delta
        else:
            raise ValueError(f"unsupported actor link operation: {mod.operation}")
        target.stats[mod.target_stat_id] = after
        applied.append({"id": mod.id, "source_actor_id": mod.source_actor_id,
                        "target_actor_id": mod.target_actor_id, "target_stat_id": mod.target_stat_id,
                        "before": before, "after": after, "source_value": sampled,
                        "coefficient": float(mod.coefficient), "operation": mod.operation})
    return tuple(applied)

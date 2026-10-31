"""Shared executable Game-IR effect capabilities (engine semantics, not game facts).

This is the single type→executor-kind contract used by the action executor,
source-button discovery, policy search and coverage audit.  No class, spell,
item, level or damage number belongs here. Unknown types fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.game.model.ir import (
    QueuedSwingEffect, ControlEffect, SpatialChargeEffect, DamageEffect, HealEffect, ModeChangeEffect,
    PeriodicEffect, PeriodicHealEffect, ActivePeriodicFullHealEffect, PeriodicResourceEffect,
    ResourceChangeEffect, ResourceScaledDirectDamageEffect,
    ResourceScaledPeriodicEffect, SummonEffect, WeaponDamageEffect, TargetStatDebuffEffect, StatusAuraEffect, EventEmitEffect,
)


@dataclass(frozen=True)
class EffectCapability:
    execution_kind: str
    role: str


# Runtime ActionCompleted dispatch MUST use execution_kind; a new effect
# cannot be made searchable merely by adding a type to a discovery whitelist.
_EFFECT_CAPABILITIES = {
    QueuedSwingEffect: EffectCapability('queued_swing', 'direct_damage'),
    DamageEffect: EffectCapability('direct_damage', 'direct_damage'),
    WeaponDamageEffect: EffectCapability('weapon_damage', 'direct_damage'),
    ResourceScaledDirectDamageEffect: EffectCapability('resource_scaled_direct_damage', 'direct_damage'),
    PeriodicEffect: EffectCapability('periodic_damage', 'periodic_damage'),
    ResourceScaledPeriodicEffect: EffectCapability('resource_scaled_periodic_damage', 'periodic_damage'),
    ResourceChangeEffect: EffectCapability('resource_change', 'resource'),
    PeriodicResourceEffect: EffectCapability('periodic_resource', 'resource'),
    HealEffect: EffectCapability('direct_heal', 'healing'),
    PeriodicHealEffect: EffectCapability('periodic_heal', 'healing'),
    ActivePeriodicFullHealEffect: EffectCapability('active_periodic_full_heal','healing'),
    ControlEffect: EffectCapability('control', 'control'),
    SpatialChargeEffect: EffectCapability('spatial_charge','movement'),
    TargetStatDebuffEffect: EffectCapability('target_stat_debuff', 'target_debuff'),
    SummonEffect: EffectCapability('summon', 'summon'),
    ModeChangeEffect: EffectCapability('mode_change', 'mode_change'),
    StatusAuraEffect: EffectCapability('status_aura', 'combat_enabler'),
    EventEmitEffect: EffectCapability('event_emit', 'combat_enabler'),
}


def effect_capability(effect: object) -> EffectCapability | None:
    """Return exact registered IR type, never subclass/inferred support."""
    return _EFFECT_CAPABILITIES.get(type(effect))


def effect_role(effect: object) -> str | None:
    capability = effect_capability(effect)
    return capability.role if capability is not None else None


def effect_execution_kind(effect: object) -> str:
    capability = effect_capability(effect)
    if capability is None:
        raise NotImplementedError(f'unsupported effect type: {type(effect).__name__}')
    return capability.execution_kind


def registered_effect_types() -> frozenset[type]:
    """For registry↔runtime contract tests, not an optimizer filter."""
    return frozenset(_EFFECT_CAPABILITIES)

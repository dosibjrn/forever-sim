from __future__ import annotations

from hashlib import sha256

"""Generic event runtime for executable Game IR Actions.

G07 introduced ActionStarted/ActionCompleted/Damage/TargetDied. G08 added
resource spending and readiness. G09 makes the queue persistent across actions
and adds backend-neutral Aura + PeriodicEffect execution, including replace
refresh semantics and target-death cancellation. No class or spell dispatch is
allowed here.
"""

from dataclasses import dataclass, replace
from math import hypot, isfinite
from contextlib import contextmanager
from typing import Any, Iterable, Mapping, Sequence

from src.game.model.ir import (
    QueuedSwingEffect, ActionDefinition, ArmorMitigationDefinition, AutoAttackDefinition, ControlEffect, SpatialChargeEffect, DamageEffect, HealEffect, IncomingAttackDefinition,
    TimedSummonDefinition, SummonEffect, ModeChangeEffect, PeriodicEffect, PeriodicHealEffect, ActivePeriodicFullHealEffect, PeriodicResourceEffect, ResourceChangeEffect, ResourceScaledPeriodicEffect, ResourceScaledDirectDamageEffect, TriggerDefinition, WeaponDamageEffect, TargetStatDebuffEffect, TargetSchoolPowerEffect, StatusAuraEffect, EventEmitEffect,
)
from .effect_capabilities import effect_execution_kind
from .events import CombatEvent, EventQueue
from .state import ActorState, TargetState


def _control_damage_break_roll(*, target_id: str, control_id: str,
                               event: CombatEvent, ordinal: int,
                               chance: float) -> tuple[float | None, bool]:
    """Stable, event-scoped source-probability roll without global RNG state."""
    if chance in (0., 1.):
        return None, chance == 1.
    key=(f'{target_id}|{control_id}|{event.action_id}|'
         f'{float(event.time_s):.9f}|{ordinal}|'
         f'{event.payload.get("effect_index",-1)}')
    roll=int.from_bytes(sha256(key.encode('utf-8')).digest()[:8],'big')/2**64
    return roll, roll < chance


@dataclass(frozen=True)
class ActionEligibility:
    eligible: bool
    reason: str | None
    at_time_s: float
    next_ready_s: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": bool(self.eligible),
            "reason": self.reason,
            "at_time_s": float(self.at_time_s),
            "next_ready_s": float(self.next_ready_s),
        }


class ActionNotEligibleError(ValueError):
    def __init__(self, eligibility: ActionEligibility) -> None:
        self.eligibility = eligibility
        super().__init__(eligibility.reason or "action is not eligible")


@dataclass(frozen=True)
class ActionExecutionResult:
    action_id: str
    start_time_s: float
    end_time_s: float
    elapsed_s: float
    total_damage: float
    target_start_health: float
    target_end_health: float
    target_defeated: bool
    target_death_s: float | None
    resources_before: dict[str, float]
    resources_after: dict[str, float]
    gcd_ready_s: float
    cooldown_ready_s: float
    events: tuple[CombatEvent, ...]
    damage_resolution: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "start_time_s": float(self.start_time_s),
            "end_time_s": float(self.end_time_s),
            "elapsed_s": float(self.elapsed_s),
            "total_damage": float(self.total_damage),
            "target_start_health": float(self.target_start_health),
            "target_end_health": float(self.target_end_health),
            "target_defeated": bool(self.target_defeated),
            "target_death_s": None if self.target_death_s is None else float(self.target_death_s),
            "resources_before": {str(k): float(v) for k, v in self.resources_before.items()},
            "resources_after": {str(k): float(v) for k, v in self.resources_after.items()},
            "gcd_ready_s": float(self.gcd_ready_s),
            "cooldown_ready_s": float(self.cooldown_ready_s),
            "damage_resolution": self.damage_resolution,
            "events": [event.as_dict() for event in self.events],
        }


@dataclass(frozen=True)
class ActionSequenceResult:
    action_id: str
    requested_casts: int
    completed_casts: int
    start_time_s: float
    end_time_s: float
    resources_before: dict[str, float]
    resources_after: dict[str, float]
    executions: tuple[ActionExecutionResult, ...]
    stopped_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "requested_casts": int(self.requested_casts),
            "completed_casts": int(self.completed_casts),
            "start_time_s": float(self.start_time_s),
            "end_time_s": float(self.end_time_s),
            "resources_before": {str(k): float(v) for k, v in self.resources_before.items()},
            "resources_after": {str(k): float(v) for k, v in self.resources_after.items()},
            "stopped_reason": self.stopped_reason,
            "executions": [x.as_dict() for x in self.executions],
        }


@dataclass(frozen=True)
class CombatTimelineResult:
    start_time_s: float
    end_time_s: float
    total_damage: float
    direct_damage: float
    periodic_damage: float
    auto_attack_damage: float
    target_start_health: float
    target_end_health: float
    target_defeated: bool
    target_death_s: float | None
    resources_before: dict[str, float]
    resources_after: dict[str, float]
    events: tuple[CombatEvent, ...]
    damage_by_actor: dict[str, float]
    damage_by_role: dict[str, float]
    actor_roles: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "damage_by_actor": dict(self.damage_by_actor),
            "damage_by_role": dict(self.damage_by_role),
            "actor_roles": dict(self.actor_roles),
            "start_time_s": float(self.start_time_s),
            "end_time_s": float(self.end_time_s),
            "total_damage": float(self.total_damage),
            "direct_damage": float(self.direct_damage),
            "periodic_damage": float(self.periodic_damage),
            "auto_attack_damage": float(self.auto_attack_damage),
            "auto_attack_swing_count": sum(x.kind == "AutoAttackSwing" for x in self.events),
            "target_start_health": float(self.target_start_health),
            "target_end_health": float(self.target_end_health),
            "target_defeated": bool(self.target_defeated),
            "target_death_s": None if self.target_death_s is None else float(self.target_death_s),
            "resources_before": {str(k): float(v) for k, v in self.resources_before.items()},
            "resources_after": {str(k): float(v) for k, v in self.resources_after.items()},
            "aura_applied_count": sum(x.kind == "AuraApplied" for x in self.events),
            "aura_replaced_count": sum(x.kind == "AuraReplaced" for x in self.events),
            "periodic_tick_count": sum(
                x.kind == "Damage" and bool(x.payload.get("periodic")) for x in self.events
            ),
            "events": [event.as_dict() for event in self.events],
        }


def expected_direct_damage(effect: DamageEffect, *, spell_power: float = 0.0) -> float:
    """Deterministic expected direct damage for the current generic slice."""
    return (
        (float(effect.base_min) + float(effect.base_max)) / 2.0
        + float(spell_power) * float(effect.spell_power_coefficient)
    )


def _direct_damage_crit_probability(effect: DamageEffect, actor_stats: Mapping[str, float]) -> float:
    """Resolve explicit crit channels first; unified spell crit only for magic.

    Item chance scope comes from the canonical Forever source adapter and
    damage school comes from GameIR. Periodic/weapon/physical resolution keeps
    its own semantics, so no implicit crit is added to those effect types.
    """
    chance = float(effect.crit_chance_bonus)
    if effect.crit_chance_stat_id is not None:
        chance += float(actor_stats.get(effect.crit_chance_stat_id, 0.0))
    elif str(effect.school).lower() == 'physical':
        chance += float(actor_stats.get('melee_crit_chance', 0.0))
    elif str(effect.school).lower() not in ('bleed', ''):
        chance += float(actor_stats.get('spell_crit_chance', 0.0))
    return max(0.0, min(1.0, chance))


def expected_direct_heal(effect: HealEffect, *, healing_power: float = 0.0,
                         spell_crit_chance: float = 0.0) -> float:
    base=((float(effect.base_min)+float(effect.base_max))/2.0
          +float(healing_power)*float(effect.spell_power_coefficient))
    chance=max(0.,min(1.,float(spell_crit_chance)+float(effect.crit_chance_bonus)))
    multiplier=float(effect.crit_multiplier)
    if not 1. <= multiplier <= 3.:
        raise ValueError('INVALID_SOURCED_HEAL_CRIT_MULTIPLIER')
    if chance > 0. and multiplier > 1.:
        facts=effect.field_provenance.get('crit_multiplier', ())
        if not any(str(f.get('source_url','')).startswith('https://') for f in facts):
            raise ValueError('HEAL_CRIT_MULTIPLIER_UNSOURCED')
    return base*(1.+chance*(multiplier-1.))


def expected_periodic_tick_heal(effect: PeriodicHealEffect, *, healing_power: float = 0.0) -> float:
    ticks = _periodic_tick_count(effect)
    return float(effect.total_base_heal) / float(ticks) + float(healing_power) * float(
        effect.spell_power_coefficient_per_tick
    )


def expected_periodic_tick_damage(effect: PeriodicEffect, *, spell_power: float = 0.0) -> float:
    ticks = _periodic_tick_count(effect)
    return float(effect.total_base_damage) / float(ticks) + float(spell_power) * float(
        effect.spell_power_coefficient_per_tick
    )


def expected_auto_attack_swing(attack: AutoAttackDefinition, *, actor: ActorState, swing_time_s: float | None = None) -> dict[str, Any]:
    """Resolve one generic auto-attack swing as deterministic outcome weights.

    G24 intentionally keeps the attack table explicit and data-driven.  The
    runtime computes expected damage from declared hit/crit probabilities; later
    fidelity work can feed canonical derived hit/crit without changing the swing
    timer/event machinery.
    """
    swing = float(attack.swing_time_s if swing_time_s is None else swing_time_s)
    if swing <= 0.0:
        raise ValueError("auto attack swing_time_s must be positive")
    source = attack.damage_source
    dps = max(0.0, float(source.flat_dps))
    if source.dps_stat_id is not None:
        dps += max(0.0, float(actor.stats.get(str(source.dps_stat_id), 0.0)))
    if source.attack_power_stat_id is not None:
        divisor = float(source.attack_power_per_dps)
        if divisor <= 0.0:
            raise ValueError("auto attack attack_power_per_dps must be positive")
        dps += max(0.0, float(actor.stats.get(str(source.attack_power_stat_id), 0.0))) / divisor
    raw_hit = max(0.0, dps * swing * max(0.0, float(source.damage_multiplier)))
    landed = max(0.0, min(1.0, float(attack.hit_chance)))
    # Mode talents contribute to the same actor-owned melee crit stat for
    # both auto-attacks and weapon-damage actions. Do not double-count if an
    # attack explicitly references that stat already.
    extra_crit = float(actor.stats.get('melee_crit_chance', 0.0))
    if attack.crit_chance_stat_id and str(attack.crit_chance_stat_id) != 'melee_crit_chance':
        extra_crit += float(actor.stats.get(str(attack.crit_chance_stat_id), 0.0))
    crit_conditional = max(0.0, min(1.0, float(attack.crit_chance_on_landed_hit) + extra_crit))
    crit_weight = landed * crit_conditional
    hit_weight = landed * (1.0 - crit_conditional)
    miss_weight = 1.0 - landed
    expected = raw_hit * (hit_weight + crit_weight * max(1.0, float(attack.crit_multiplier)))
    return {
        "raw_hit": float(raw_hit),
        "expected_damage": float(expected),
        "resolution": "expected_value_attack_outcomes",
        "outcome_weights": {
            "miss": float(miss_weight),
            "hit": float(hit_weight),
            "crit": float(crit_weight),
        },
        "hit_chance": float(landed),
        "crit_chance_on_landed_hit": float(crit_conditional),
        "crit_multiplier": float(max(1.0, float(attack.crit_multiplier))),
    }


def expected_weapon_damage(effect: WeaponDamageEffect, *, actor: ActorState) -> dict[str, Any]:
    source = effect.damage_source
    dps = max(0.0, float(source.flat_dps))
    if source.dps_stat_id is not None:
        dps += max(0.0, float(actor.stats.get(str(source.dps_stat_id), 0.0)))
    if source.attack_power_stat_id is not None:
        divisor = float(source.attack_power_per_dps)
        if divisor <= 0.0:
            raise ValueError("weapon damage attack_power_per_dps must be positive")
        dps += max(0.0, float(actor.stats.get(str(source.attack_power_stat_id), 0.0))) / divisor
    base_weapon = dps * max(0.0, float(effect.weapon_damage_time_s)) * max(0.0, float(source.damage_multiplier))
    raw_hit = base_weapon * max(0.0, float(effect.weapon_damage_multiplier)) + float(effect.flat_damage)
    landed = max(0.0, min(1.0, float(effect.hit_chance)))
    crit_conditional = max(0.0, min(1.0, float(effect.crit_chance_on_landed_hit)
                                    + float(actor.stats.get('melee_crit_chance', 0.0))))
    crit_weight = landed * crit_conditional
    hit_weight = landed * (1.0 - crit_conditional)
    miss_weight = 1.0 - landed
    expected = raw_hit * (hit_weight + crit_weight * max(1.0, float(effect.crit_multiplier)))
    return {
        "raw_hit": float(raw_hit), "expected_damage": float(expected),
        "resolution": "expected_value_weapon_action_outcomes",
        "outcome_weights": {"miss": float(miss_weight), "hit": float(hit_weight), "crit": float(crit_weight)},
        "hit_chance": float(landed), "crit_chance_on_landed_hit": float(crit_conditional),
        "crit_multiplier": float(max(1.0, float(effect.crit_multiplier))),
    }


def sourced_magic_resistance_reduction(resistance: float, *, level: int) -> float:
    """Classic expected magical-resistance proxy; never invents target R.

    Only called for explicit resistance values (the ordinary melee scenario
    does not declare enemy spell resistance). This is qualified Classic
    mechanics, not a claim of Forever-binary parity.
    """
    r=float(resistance)
    if not isfinite(r) or r<0 or not 1<=int(level)<=60:
        raise ValueError('INVALID_SOURCED_MAGIC_RESISTANCE_CONTEXT')
    return min(.75,.75*r/max(100.,5.*int(level)))


def expected_incoming_attack(
    attack: IncomingAttackDefinition, *, actor: ActorState,
    mitigation_rules: Sequence[ArmorMitigationDefinition] = (),
) -> dict[str, Any]:
    """Resolve one expected incoming hit without class/ruleset branches."""
    raw = max(0.0, float(attack.raw_damage))
    source_hit_chance = max(0.0, min(1.0, float(attack.hit_chance)))
    # Avoidance reduces expected physical contact *before* armor mitigation.
    # Non-physical attacks do not inherit melee Dodge.
    dodge = (max(0.0, min(1.0, float(actor.stats.get('dodge_chance', 0.0))))
             if (str(attack.school).lower() == 'physical' and
                 not bool(attack.metadata.get('hit_chance_includes_actor_dodge', False))) else 0.0)
    # Rating/sourced effects can reduce the chance of *incoming* physical
    # contact independently from Dodge. This consumes probabilities only;
    # rating-to-chance coefficients live in source/ruleset data, not here.
    miss_bonus = (max(0.0,min(1.0,float(actor.stats.get('incoming_miss_chance_bonus',0.0))))
                  if str(attack.school).lower() == 'physical' else 0.0)
    hit_chance = source_hit_chance * max(0.0,1.0 - dodge - miss_bonus)
    expected_dodge_count=(source_hit_chance*dodge
        if str(attack.school).lower()=='physical' else 0.0)
    landed_raw = raw * hit_chance
    reduction = 0.0
    armor = 0.0
    mitigation_id = attack.mitigation_rule_id
    if mitigation_id is not None:
        # ArmorMitigationDefinition describes a *physical* armor curve only.
        # Fail closed on miswired source IR instead of quietly applying armor
        # to Frost/Fire/Nature/etc. Magic defenses live in resistance rules.
        if str(attack.school).lower() != 'physical':
            raise ValueError('ARMOR_MITIGATION_ON_NONPHYSICAL_DAMAGE')
        rule = next((x for x in mitigation_rules if str(x.id) == str(mitigation_id)), None)
        if rule is None:
            raise ValueError(f"incoming attack mitigation rule {mitigation_id!r} is unavailable")
        if str(rule.school).lower() != str(attack.school).lower():
            raise ValueError("incoming attack mitigation rule school mismatch")
        stat_id = str(rule.armor_stat_id)
        if stat_id not in actor.stats:
            raise ValueError(f"incoming mitigation requires actor stat {stat_id!r}")
        armor = max(0.0, float(actor.stats[stat_id]))
        constant = max(1e-12, float(rule.armor_constant))
        cap = max(0.0, min(1.0, float(rule.reduction_cap)))
        reduction = max(0.0, min(cap, armor / (armor + constant)))
    # An equipment-sourced all-resistance bonus is only material for a
    # magical incoming attack. No fictitious magic swings are created in
    # the qualified ordinary-melee scenario.
    magic_resistance=0.0
    if str(attack.school).lower() not in ('physical',''):
        magic_resistance=max(0.,float(actor.stats.get('resistance_all',0.))+
            float(actor.stats.get('resistance_'+str(attack.school).lower(),0.)))
        if magic_resistance>0:
            level=int(actor.metadata.get('level',0))
            reduction=1.-(1.-reduction)*(1.-sourced_magic_resistance_reduction(
                magic_resistance,level=level))
    post = landed_raw * (1.0 - reduction)
    return {
        "raw_damage": float(raw), "hit_chance": float(hit_chance),
        "source_hit_chance": float(source_hit_chance), "actor_dodge_chance": float(dodge),
        "expected_dodge_count":float(expected_dodge_count),
        "dodge_probability":float(expected_dodge_count),
        "actor_incoming_miss_bonus": float(miss_bonus),
        "landed_raw_damage": float(landed_raw), "armor": float(armor),
        "armor_reduction": float(reduction),
        "actor_magic_resistance":float(magic_resistance),
        "magic_resistance_model":"qualified_classic_expected" if magic_resistance else "not_applicable",
        "post_mitigation_damage": float(post),
        "mitigation_rule_id": mitigation_id, "resolution": "expected_value_incoming_attack",
    }


def _periodic_tick_count(effect: PeriodicEffect | PeriodicHealEffect | PeriodicResourceEffect | ResourceScaledPeriodicEffect) -> int:
    interval = float(effect.tick_interval_s)
    duration = float(effect.duration_s)
    if interval <= 0.0 or duration <= 0.0:
        raise ValueError("periodic duration/tick interval must be positive")
    ratio = duration / interval
    rounded = int(round(ratio))
    if rounded <= 0 or abs(ratio - rounded) > 1e-9:
        raise NotImplementedError("fractional terminal periodic tick semantics are unsupported")
    return rounded


def _resource_host(actor: ActorState, target: TargetState | None, resource_id: str):
    definition = actor.resource_definitions.get(str(resource_id))
    scope = None if definition is None else str(definition.scope or "actor")
    if scope == "target":
        return target
    return actor


def _resource_amount(actor: ActorState, target: TargetState | None, resource_id: str) -> float | None:
    host = _resource_host(actor, target, resource_id)
    if host is None:
        return None
    return host.resource_amount(resource_id)


def _resource_can_spend(actor: ActorState, target: TargetState | None, resource_id: str, amount: float) -> bool:
    host = _resource_host(actor, target, resource_id)
    if host is None:
        return False
    return host.can_spend(resource_id, amount)


def action_eligibility(
    *, action: ActionDefinition, actor: ActorState, target: TargetState | None = None, at_time_s: float | None = None,
) -> ActionEligibility:
    """Return fail-closed generic eligibility for an Action at one timestamp."""
    now = float(actor.current_time_s if at_time_s is None else at_time_s)
    if action.owner_actor_id != actor.id:
        return ActionEligibility(False, f"action owner {action.owner_actor_id!r} != actor {actor.id!r}", now, now)

    if actor.current_mode_id is not None:
        mode = actor.mode_definitions.get(str(actor.current_mode_id))
        if mode is None:
            return ActionEligibility(False, f"active mode {actor.current_mode_id!r} is undefined", now, now)
        if mode.enabled_action_ids is not None and str(action.id) not in set(mode.enabled_action_ids):
            return ActionEligibility(False, f"action disabled by active mode {actor.current_mode_id!r}", now, now)

    for requirement in action.requirements:
        kind = str(requirement.get("kind") or "")
        if kind == "minimum_level":
            actor_level = actor.metadata.get("level")
            if actor_level is None:
                return ActionEligibility(False, "actor level is unavailable for minimum_level requirement", now, now)
            required = int(requirement.get("value", 0))
            if int(actor_level) < required:
                return ActionEligibility(False, f"minimum level {required} not met", now, now)
            continue
        if kind == 'out_of_combat':
            if actor.metadata.get('in_combat'):
                return ActionEligibility(False, 'requires out of combat', now, now)
            continue
        if kind == 'aura_missing':
            aura_id = str(requirement.get('aura_id') or '')
            aura = actor.active_auras.get(aura_id)
            if not aura_id or (aura and aura.expires_at_s > now + 1e-12):
                return ActionEligibility(False, 'requires missing actor aura ' + aura_id, now, now)
            continue
        if kind == "mode_is":
            required_mode = str(requirement.get("value") or "")
            if str(actor.current_mode_id or "") != required_mode:
                return ActionEligibility(False, f"requires mode {required_mode!r}", now, now)
            continue
        if kind == "relative_position_is":
            # Position is encounter state, not a class/ability-specific shortcut.
            # Unknown position must never make a rear-only strike legal.
            actual = None if target is None else target.metadata.get('attacker_relative_position')
            expected = str(requirement.get('value') or '')
            if actual is None or str(actual) != expected:
                return ActionEligibility(False, f"requires relative position {expected!r}; have {actual!r}", now, now)
            continue
        if kind == 'aura_any_present':
            ids = requirement.get('aura_ids')
            scope = str(requirement.get('scope') or 'actor')
            if not isinstance(ids, (list,tuple)) or not ids or not all(isinstance(i,str) and i for i in ids) or scope not in ('actor','target'):
                return ActionEligibility(False, 'invalid aura_any_present requirement', now, now)
            host = actor if scope == 'actor' else target
            if host is None or not any(i in host.active_auras and host.active_auras[i].expires_at_s > now + 1e-12 for i in ids):
                return ActionEligibility(False, 'requires one active sourced aura', now, now)
            continue
        if kind == 'aura_present':
            aura_id = str(requirement.get('aura_id') or '')
            scope = str(requirement.get('scope') or 'actor')
            if not aura_id or scope not in ('actor', 'target'):
                return ActionEligibility(False, 'invalid aura requirement', now, now)
            host = actor if scope == 'actor' else target
            aura = None if host is None else host.active_auras.get(aura_id)
            if aura is None or float(aura.expires_at_s) <= now + 1e-12:
                return ActionEligibility(False, f'requires active aura {aura_id}', now, now)
            continue
        if kind == 'resource_below_capacity':
            resource_id=str(requirement.get('resource_id') or '')
            host=_resource_host(actor,target,resource_id)
            amount=None if host is None else host.resource_amount(resource_id)
            capacity=None if host is None else host.resource_capacity.get(resource_id)
            if (amount is None or capacity is None or
                    not (amount < capacity - 1e-12)):
                return ActionEligibility(False, f'requires room in {resource_id}', now, now)
            continue
        if kind == "resource_min":
            resource_id = str(requirement.get("resource_id") or "")
            required = max(0.0, float(requirement.get("value", 0.0)))
            current = _resource_amount(actor, target, resource_id)
            if current is None or current + 1e-12 < required:
                return ActionEligibility(False, f"requires {required:g} {resource_id}; have {current}", now, now)
            continue
        return ActionEligibility(False, f"unsupported action requirement: {kind or 'unknown'}", now, now)

    next_ready = max(0. if action.metadata.get('ignores_global_cooldown') else float(actor.gcd_ready_s),
                     float(actor.cooldown_ready_s.get(action.id, 0.0)))
    if now + 1e-12 < next_ready:
        return ActionEligibility(False, "action not ready: gcd/cooldown", now, next_ready)

    for cost in action.costs:
        if not _resource_can_spend(actor, target, cost.resource_id, cost.amount):
            current = _resource_amount(actor, target, cost.resource_id)
            definition = actor.resource_definitions.get(str(cost.resource_id))
            scope = None if definition is None else str(definition.scope or "actor")
            # Regeneration cannot make a cost payable above the sourced
            # resource capacity. Otherwise the policy waits forever at cap.
            capacity = actor.resource_capacity.get(str(cost.resource_id))
            if (current is not None and scope == "actor"
                    and actor.resource_is_active(cost.resource_id)
                    and capacity is not None
                    and float(cost.amount) <= float(capacity) + 1e-12):
                rate = max(0.0, float(actor.resource_regeneration_per_s.get(str(cost.resource_id), 0.0)))
                missing = max(0.0, float(cost.amount) - float(current))
                if rate > 0.0 and missing > 1e-12:
                    ready = now + missing / rate
                    return ActionEligibility(False, f"action not ready: resource {cost.resource_id}", now, ready)
            reason = (
                f"required resource {cost.resource_id!r} is unavailable"
                if current is None
                else f"insufficient {cost.resource_id}: have {current}, need {float(cost.amount)}"
            )
            return ActionEligibility(False, reason, now, now)
    return ActionEligibility(True, None, now, now)


class EventTransitionBudgetExceeded(RuntimeError):
    """A real executor event cap, raised before consuming the next event."""
    def __init__(self, processed: int):
        self.events_processed = int(processed)
        super().__init__('BUDGET_EVENT_TRANSITIONS')


class ComputeDeadlineExceeded(RuntimeError):
    """Executor interrupted at an event boundary by a CPU/wall deadline."""
    def __init__(self, processed: int, kind: str):
        self.events_processed = int(processed)
        self.kind = str(kind)
        super().__init__(f'BUDGET_{kind}_DEADLINE')


class CombatRuntime:
    """Persistent backend-neutral combat queue shared by multiple Actions."""

    def __init__(
        self, *, actor: ActorState, target: TargetState, spell_power: float = 0.0,
        auto_attacks: Sequence[AutoAttackDefinition] = (), triggers: Sequence[TriggerDefinition] = (),
        companions: Sequence[ActorState] = (), actor_links: Sequence[ActorLinkModifier] = (),
        timed_summons: Sequence[TimedSummonDefinition] = (),
        incoming_attacks: Sequence[IncomingAttackDefinition] = (),
        mitigation_rules: Sequence[ArmorMitigationDefinition] = (),
        enable_casting_regen: bool = True,
        allow_source_partial_l1: bool = False,
        other_targets: Sequence[TargetState] = (),
        spatial_positions_yards: Mapping[str, tuple[float, float]] | None = None,
        enemy_move_speed_yards_s: float = 7.0,
        melee_radius_yards: float = 5.0,
        aggro_radius_yards: float = 10.0,
        sampling_seed: int = 0,
    ) -> None:
        if type(sampling_seed) is not int or sampling_seed < 0:
            raise ValueError('COMBAT_SAMPLING_SEED_MUST_BE_NONNEGATIVE_INTEGER')
        self.sampling_seed = sampling_seed
        # Explicit L1 diagnostics opt-in. Production L2/L3 controllers use the
        # default strict gate and cannot execute source-incomplete fragments.
        self.allow_source_partial_l1 = bool(allow_source_partial_l1)
        if (actor.metadata.get('L1_NOT_SOURCE_VALIDATED_ACTOR_AT_LEVEL')
                and not self.allow_source_partial_l1):
            raise ValueError('SOURCE_L1_BOUNDED_ACTOR_FORBIDDEN_IN_PRODUCTION_RUNTIME')
        self.actor = actor
        self.actors = {actor.id: actor}
        for companion in companions:
            if companion.id in self.actors:
                raise ValueError(f"duplicate combat actor id: {companion.id}")
            if abs(float(companion.current_time_s) - float(actor.current_time_s)) > 1e-12:
                raise ValueError("all combat actors must share an initial encounter clock")
            self.actors[companion.id] = companion
        self.timed_summons: dict[str, TimedSummonDefinition] = {}
        self.summon_actor_ids: set[str] = set()
        for definition in timed_summons:
            if str(definition.id) in self.timed_summons:
                raise ValueError(f"duplicate summon definition: {definition.id}")
            if definition.owner_actor_id not in self.actors or definition.summoned_actor_id not in self.actors:
                raise ValueError("summon owner and summoned actor must be registered")
            if definition.owner_actor_id == definition.summoned_actor_id or definition.summoned_actor_id == actor.id:
                raise ValueError("summon actor must be distinct from owner and primary actor")
            if definition.summoned_actor_id in self.summon_actor_ids:
                raise ValueError("summoned actor may have only one timed lifecycle definition")
            if not 0 < float(definition.duration_s) < float("inf"):
                raise ValueError("summon duration must be finite and positive")
            self.timed_summons[str(definition.id)] = definition
            self.summon_actor_ids.add(str(definition.summoned_actor_id))
        if any((x.source_actor_id in self.summon_actor_ids
                or x.target_actor_id in self.summon_actor_ids
                or x.requires_actor_id in self.summon_actor_ids) for x in actor_links):
            raise ValueError("timed summon actor links require dynamic spawn/despawn modifier semantics")
        self.actor_active = {actor_id: actor_id not in self.summon_actor_ids for actor_id in self.actors}
        self.summon_generation: dict[str, int] = {summon_id: 0 for summon_id in self.timed_summons}
        self.summon_pending: set[str] = set()
        self.summon_expiry: dict[str, float] = {}
        self.actor_roles = {actor_id: ("player" if actor_id == actor.id else
                          "summon" if actor_id in self.summon_actor_ids else
                          "pet") for actor_id in self.actors}
        import copy
        self.summon_initial_actor_states = {
            actor_id: copy.deepcopy(self.actors[actor_id]) for actor_id in self.summon_actor_ids
        }
        from .actor_links import apply_actor_link_modifiers
        self.applied_actor_links = apply_actor_link_modifiers(self.actors, tuple(actor_links))
        self.primary_actor_id = actor.id
        self.target = target
        self.targets = {t.id: t for t in (target, *other_targets)}
        # Target-specific control behavior is sourced from ControlEffect flags.
        self._control_behaviors: dict[tuple[str, str], dict[str, bool | float | None]] = {}
        self._source_control_owners: dict[tuple[str,str],tuple[str,str,float]] = {}
        if len(self.targets) != 1 + len(other_targets):
            raise ValueError('duplicate encounter target id')
        self.multi_target = bool(other_targets)
        self._pack_positions = dict(spatial_positions_yards or {})
        self.enemy_positions_yards = dict(self._pack_positions)
        if self.multi_target:
            if set(self._pack_positions) != set(self.targets):
                raise ValueError('2D pack requires positions for every registered target')
            if not isfinite(float(enemy_move_speed_yards_s)) or float(enemy_move_speed_yards_s) <= 0:
                raise ValueError('invalid enemy movement speed')
            if not isfinite(float(melee_radius_yards)) or float(melee_radius_yards) <= 0:
                raise ValueError('invalid 2D melee radius')
            if any(len(xy) != 2 or not all(isfinite(float(v)) for v in xy)
                   for xy in self._pack_positions.values()):
                raise ValueError('invalid 2D enemy coordinate')
        self.enemy_move_speed_yards_s = float(enemy_move_speed_yards_s)
        self.melee_radius_yards = float(melee_radius_yards)
        if not isfinite(float(aggro_radius_yards)) or float(aggro_radius_yards) <= 0:
            raise ValueError('invalid 2D aggro radius')
        self.aggro_radius_yards = float(aggro_radius_yards)
        self.player_position_yards = (0., 0.)
        self._player_move_generation = 0
        self.player_route_speed_yards_s = 7.0
        self._player_route_end_s = float(actor.current_time_s)
        self._player_pause_until_s = float(actor.current_time_s)
        self._engaged_targets: set[str] = set()
        self.actor.metadata['in_combat'] = False
        # Default conservative 2D detection distance is a scenario proxy, not
        # an asserted Forever stealth-vs-level formula. Tunable per encounter.
        self.stealth_detection_radius_yards = self.melee_radius_yards
        self._approaching_targets: set[str] = set()
        # Segment start/end coordinates and times for lazily advanced 2D enemies.
        # A source-declared root freezes their true position, not their spawn point.
        self._enemy_motion: dict[str, tuple[float, float, tuple[float, float], tuple[float, float]]] = {}
        self._enemy_motion_generation: dict[str, int] = {}
        self._melee_targets: set[str] = set()
        self._pack_target_death_times: dict[str, float] = {}
        target_resource_owners: dict[str, str] = {}
        for a in self.actors.values():
            for r in a.resource_definitions.values():
                if str(r.scope or "actor") != "target":
                    continue
                existing_owner = target_resource_owners.setdefault(str(r.id), str(a.id))
                if existing_owner != str(a.id):
                    raise ValueError(f"target resource id {r.id!r} has multiple owners; namespace it in IR")
        for one_target in self.targets.values():
            one_target.bind_resource_definitions(tuple(r for a in self.actors.values() for r in a.resource_definitions.values()))
        self.spell_power = float(spell_power)
        self.actor_spell_power = {a.id: float(a.stats.get("spell_power", 0.0)) for a in self.actors.values()}
        self.actor_spell_power[actor.id] = float(spell_power)
        self.queue = EventQueue()
        self.trace: list[CombatEvent] = []
        self.event_transitions = 0  # processed queue events, not merely emitted trace entries
        self.event_budget_cap: int | None = None
        self.event_budget_start = 0
        self.cpu_deadline_ns: int | None = None
        self.wall_deadline_ns: int | None = None
        self.actions: dict[str, ActionDefinition] = {}
        # A new encounter (or recovery window) consumes the preceding runtime's
        # actor-owned HoT/resource ticks. Enemy-targeted DoTs must never leak
        # onto a fresh enemy. Validate source actions and aura generations.
        carried_events = tuple(actor.pending_actor_periodic_events)
        carried_actions = dict(actor.pending_actor_periodic_actions)
        for carried in carried_events:
            if carried.kind not in ('PeriodicTick', 'AuraExpired') or carried.payload.get('aura_scope') != 'actor':
                raise ValueError('invalid persisted actor periodic event')
            if carried.actor_id != actor.id or carried.action_id not in carried_actions:
                raise ValueError('persisted periodic event has no matching source action')
            aura = actor.active_auras.get(str(carried.payload.get('aura_id')))
            if aura is None or aura.generation != int(carried.payload.get('generation', -1)):
                raise ValueError('persisted periodic event has no matching active aura generation')
            if float(carried.time_s) <= float(actor.current_time_s) + 1e-9:
                raise ValueError('persisted periodic event is not in the future')
            self.queue.push(carried)
        self.actions.update(carried_actions)
        actor.pending_actor_periodic_events = ()
        actor.pending_actor_periodic_actions.clear()
        self.auto_attacks: dict[str, AutoAttackDefinition] = {str(x.id): x for x in auto_attacks}
        self.triggers: dict[str, TriggerDefinition] = {str(x.id): x for x in triggers}
        if len(self.auto_attacks) != len(auto_attacks) or len(self.triggers) != len(triggers):
            raise ValueError("auto attack and trigger ids must be unique within an encounter")
        if any(str(a.owner_actor_id) not in self.actors for a in auto_attacks):
            raise ValueError("auto attack owner must be a registered combat actor")
        if any(str(t.owner_actor_id) not in self.actors for t in triggers):
            raise ValueError("trigger owner must be a registered combat actor")
        self.auto_attack_generation: dict[str, int] = {}
        self.auto_attack_active_generation: dict[str, int] = {}
        self.actor_cast_busy_until: dict[str, float] = {}
        # Owner-scoped cast identity; incoming hit and completion share the
        # SAME event queue. No speculative timers or offline DPS proxy.
        self._active_cast_action: dict[str, str] = {}
        self.pending_queued_swing: dict[str, tuple[str, QueuedSwingEffect]] = {}
        self.enable_casting_regen = bool(enable_casting_regen)
        # Recovery may advance ActorState without a combat event queue. Expire
        # elapsed actor status auras before any new swing/talent calculation.
        for active_actor in self.actors.values():
            active_actor.expire_elapsed_auras(float(active_actor.current_time_s))
        self.start_time_s = float(actor.current_time_s)
        self.target_start_health = float(target.health)
        self.resources_before = {str(k): float(v) for k, v in actor.resources.items()}
        self.total_damage = 0.0
        self.direct_damage = 0.0
        self.periodic_damage = 0.0
        self.auto_attack_damage = 0.0
        self.target_death_s: float | None = None
        self.last_event_time_s = float(actor.current_time_s)
        self._sync_auto_attacks(float(actor.current_time_s))
        # The same event clock owns ordinary enemy swings, outgoing Actions,
        # triggered effects and post-combat ActorState. No class dispatch.
        self.scheduled_incoming_attacks: dict[str, IncomingAttackDefinition] = {}
        self.scheduled_mitigation_rules = tuple(mitigation_rules)
        mitigation_ids = {str(rule.id) for rule in mitigation_rules}
        if len(mitigation_ids) != len(mitigation_rules):
            raise ValueError("duplicate incoming mitigation rule id")
        for attack in incoming_attacks:
            if str(attack.id) in self.scheduled_incoming_attacks:
                raise ValueError(f"duplicate incoming attack id: {attack.id}")
            if str(attack.target_actor_id) != str(self.primary_actor_id):
                raise ValueError(f"incoming attack targets unknown primary actor: {attack.id}")
            if attack.mitigation_rule_id is not None and str(attack.mitigation_rule_id) not in mitigation_ids:
                raise ValueError(f"missing mitigation rule for incoming attack: {attack.id}")
            cadence = attack.metadata.get("representative_swing_s")
            if cadence is None or not isfinite(float(cadence)) or float(cadence) <= 0:
                raise ValueError(f"incoming attack missing positive sourced cadence: {attack.id}")
            if not attack.provenance or not 0 < float(attack.hit_chance) <= 1 or not isfinite(float(attack.raw_damage)) or float(attack.raw_damage) <= 0:
                raise ValueError(f"incoming attack has unsupported source/outcome: {attack.id}")
            if not actor.resource_positive(str(attack.health_resource_id)):
                raise ValueError(f"incoming attack requires positive actor health: {attack.id}")
            self.scheduled_incoming_attacks[str(attack.id)] = attack
            if not self.multi_target:
                self._schedule_enemy_swing(attack)
            elif str(attack.source_actor_id) not in self.targets:
                raise ValueError('2D incoming attack requires registered enemy source')
        if self.multi_target:
            for enemy_id, xy in self._pack_positions.items():
                if hypot(xy[0] - self.player_position_yards[0], xy[1] - self.player_position_yards[1]) <= self.aggro_radius_yards + 1e-9:
                    self.engage_target(enemy_id)

    def _noninstant_cast_active(self) -> bool:
        """A cast has committed its clock even before ActionStarted is dequeued."""
        return (float(self.actor_cast_busy_until.get(self.primary_actor_id, 0.)) >
                float(self.actor.current_time_s) + 1e-9)

    def _player_is_moving(self) -> bool:
        """The route remains active between spatial movement step events."""
        return (self.multi_target and float(self.actor.current_time_s) <
                self._player_route_end_s - 1e-9 and
                float(self.actor.current_time_s) >= self._player_pause_until_s - 1e-9)

    def pause_player_route_for_cast(self, duration_s: float) -> None:
        """Hold pending 2D movement steps during a real stationary cast.

        No teleport or free route cancellation: the same waypoints resume after
        the committed cast. The generic APL invokes this only for an eligible
        non-instant action, never for an arbitrary source class/spell.
        """
        duration = float(duration_s)
        if duration <= 0. or not self._player_is_moving():
            return
        if not isfinite(duration):
            raise ValueError('INVALID_CAST_DURATION')
        gen = self._player_move_generation
        steps = [event for _, _, event in self.queue._heap
                 if event.kind == 'SpatialPlayerMoveStep' and
                 event.payload.get('move_generation') == gen]
        if not steps:
            raise ValueError('MOVING_ROUTE_HAS_NO_FUTURE_STEPS')
        self.queue.discard_where(lambda event: event.kind == 'SpatialPlayerMoveStep'
             and event.payload.get('move_generation') == gen)
        for step in steps:
            self.queue.push(replace(step, time_s=float(step.time_s)+duration))
        self._player_route_end_s += duration
        self._player_pause_until_s = float(self.actor.current_time_s) + duration

    def begin_target_chase(self) -> bool:
        """Schedule real 2D pursuit of the selected surviving enemy, if idle."""
        if (not self.multi_target or not self.target.alive
                or self._player_is_moving()
                or self._enemy_distance(self.target.id) <= self.melee_radius_yards + 1e-9):
            return False
        return self.begin_player_move(self.enemy_positions_yards[self.target.id],
            speed_yards_s=self.player_route_speed_yards_s) > 0.0

    def begin_player_move(self, destination: tuple[float, float], *,
                          speed_yards_s: float = 7.0,
                          step_yards: float = 2.0) -> float:
        """Schedule one non-blocking leg of the generic 2D player route."""
        return self.begin_player_route((destination,), speed_yards_s=speed_yards_s,
                                       step_yards=step_yards)

    def begin_player_route(self, waypoints, *, speed_yards_s: float = 7.0,
                           step_yards: float = 2.0) -> float:
        """Queue a finite 2D route while allowing the APL to fight mid-travel.

        An unbounded square *field* is generated on demand; this finite route
        only schedules movement to explicitly selected points, not enemy tags.
        """
        if (not isfinite(float(speed_yards_s)) or float(speed_yards_s) <= 0
                or not isfinite(float(step_yards)) or float(step_yards) <= 0):
            raise ValueError('INVALID_PLAYER_MOVEMENT')
        if not self.multi_target:
            raise ValueError('route requires 2D encounter context')
        if self._noninstant_cast_active():
            raise ValueError('MOVEMENT_INTERRUPTS_NONINSTANT_CAST')
        from math import ceil
        stealth = self._active_stealth()
        if stealth:
            speed_yards_s *= float(stealth[1].movement_speed_multiplier)
        if not isfinite(speed_yards_s) or speed_yards_s <= 0:
            raise ValueError('INVALID_STEALTH_MOVEMENT_SPEED')
        self.player_route_speed_yards_s = float(speed_yards_s)
        self._player_move_generation += 1
        gen=self._player_move_generation
        xy = self.player_position_yards
        elapsed=0.
        for destination in waypoints:
            if len(destination)!=2 or not all(isfinite(float(v)) for v in destination):
                raise ValueError('INVALID_PLAYER_MOVEMENT')
            dest=tuple(float(v) for v in destination)
            distance=hypot(dest[0]-xy[0],dest[1]-xy[1])
            if distance <= 1e-12:
                xy=dest
                continue
            for i in range(1,int(ceil(distance/float(step_yards)))+1):
                frac=min(1.,i*float(step_yards)/distance)
                pos=(xy[0]+(dest[0]-xy[0])*frac,xy[1]+(dest[1]-xy[1])*frac)
                self.queue.push(CombatEvent(
                    time_s=float(self.actor.current_time_s)+elapsed+distance*frac/float(speed_yards_s),
                    kind='SpatialPlayerMoveStep',actor_id=self.primary_actor_id,
                    target_id=self.primary_actor_id,
                    payload={'xy':pos,'move_generation':gen}))
            elapsed += distance/float(speed_yards_s)
            xy=dest
        self._player_route_end_s = float(self.actor.current_time_s) + elapsed
        return self._player_route_end_s

    def _active_stealth(self) -> tuple[str, StatusAuraEffect] | None:
        for aura in self.actor.active_auras.values():
            if aura.expires_at_s <= self.actor.current_time_s + 1e-12:
                continue
            action = self.actions.get(aura.source_action_id)
            if action is None:
                # The actor state survives consecutive pulls. The source aura
                # traits must survive too, even if the casting action is not
                # in the next encounter's ActionCompleted event registry.
                saved = self.actor.metadata.get('active_stealth_aura_traits', {}).get(aura.id)
                if saved is not None:
                    return (aura.id, StatusAuraEffect('status_aura',aura.id,'actor',1.,
                        stealth=True,indefinite=True,
                        movement_speed_multiplier=float(saved['movement_speed_multiplier'])))
                continue
            for effect in action.effects:
                if (isinstance(effect, StatusAuraEffect) and effect.stealth
                        and effect.aura_id == aura.id):
                    return (aura.id, effect)
        return None

    def _break_stealth(self, *, action_id: str, reason: str) -> None:
        active = self._active_stealth()
        if active is None:
            return
        aura_id, _ = active
        removed = self.actor.remove_aura(aura_id)
        if removed is not None:
            details=self.actor.metadata.get('active_stealth_aura_traits', {}).pop(aura_id, {})
            cooldown=float(details.get('fade_cooldown_s',0.))
            source_action=str(details.get('source_action_id') or removed.source_action_id)
            if cooldown:
                self.actor.cooldown_ready_s[source_action] = max(
                    self.actor.cooldown_ready_s.get(source_action, 0.),
                    float(self.actor.current_time_s)+cooldown)
            self.trace.append(CombatEvent(time_s=float(self.actor.current_time_s),
                kind='StealthBroken', actor_id=self.actor.id, target_id=self.actor.id,
                action_id=action_id, payload={'aura_id':aura_id,'reason':reason}))
            self._sync_auto_attacks(float(self.actor.current_time_s))

    def _proximity_aggro(self) -> None:
        stealth = self._active_stealth()
        if stealth and any(self.targets[e].alive and e not in self._engaged_targets
                           and self._enemy_distance(e)<=self.stealth_detection_radius_yards+1e-9
                           for e in self.targets):
            self._break_stealth(action_id=stealth[0], reason='detected_by_enemy')
        radius = self.aggro_radius_yards if self._active_stealth() is None else self.stealth_detection_radius_yards
        for enemy_id in sorted(self.targets):
            if (self.targets[enemy_id].alive and enemy_id not in self._engaged_targets
                    and self._enemy_distance(enemy_id) <= radius+1e-9):
                self.engage_target(enemy_id)

    def _enemy_position_at(self, enemy_id: str, time_s: float | None = None) -> tuple[float, float]:
        """Real linear 2D position while approaching; stationary under immobilization."""
        motion = self._enemy_motion.get(enemy_id)
        if motion is None:
            return self.enemy_positions_yards[enemy_id]
        started, ends, start_xy, destination = motion
        now = float(self.actor.current_time_s if time_s is None else time_s)
        fraction = max(0.0, min(1.0, (now-started)/(ends-started)))
        return tuple(a+(b-a)*fraction for a,b in zip(start_xy,destination))

    def _enemy_distance(self, enemy_id: str) -> float:
        xy = self._enemy_position_at(enemy_id)
        return hypot(xy[0]-self.player_position_yards[0], xy[1]-self.player_position_yards[1])

    @property
    def spatial_context(self) -> dict:
        if not self.multi_target:
            return {'simultaneous_2d': False}
        live_engaged = self._engaged_targets & {t.id for t in self.targets.values() if t.alive}
        in_melee = live_engaged & {key for key in live_engaged
                                 if self._enemy_distance(key) <= self.melee_radius_yards + 1e-9}
        return {'simultaneous_2d': True, 'enemy_count_engaged': len(live_engaged),
                'enemy_count_in_range': len(in_melee),
                'target_distance_yards': float(self._enemy_distance(self.target.id))}

    def _schedule_enemy_swing(self, attack: IncomingAttackDefinition) -> None:
        cadence = float(attack.metadata['representative_swing_s'])
        enemy_id = str(attack.source_actor_id) if self.multi_target else self.primary_actor_id
        self.queue.push(CombatEvent(
            time_s=float(self.actor.current_time_s) + cadence, kind='ScheduledIncomingAttack',
            actor_id=self.primary_actor_id, target_id=enemy_id, action_id=str(attack.id),
            payload={'swing_index': 1, 'cadence_s':cadence}))

    def _enemy_is_immobilized(self, target_id: str, at_time_s: float) -> bool:
        # Generic control vocabulary from ControlEffect, never spell/class IDs.
        target=self.targets[target_id]
        return any(expiry > at_time_s + 1e-12 and (
            cid == 'root' or self._control_behaviors.get((target_id,cid),{}).get('prevents_enemy_actions'))
            for cid,expiry in target.active_controls.items())

    def _begin_enemy_approach(self, target_id: str) -> None:
        """Resume an engaged, alive mobile enemy from its actual frozen position."""
        if (not self.multi_target or target_id not in self._engaged_targets
                or not self.targets[target_id].alive or target_id in self._melee_targets):
            return
        now = float(self.actor.current_time_s)
        if self._enemy_is_immobilized(target_id, now):
            return
        pos = self._enemy_position_at(target_id, now)
        self.enemy_positions_yards[target_id] = pos
        distance = hypot(pos[0]-self.player_position_yards[0],pos[1]-self.player_position_yards[1])
        travel = max(0.0, distance-self.melee_radius_yards)/self.enemy_move_speed_yards_s
        self._enemy_motion.pop(target_id, None)
        generation = self._enemy_motion_generation.get(target_id, 0)+1
        self._enemy_motion_generation[target_id] = generation
        if travel <= 1e-12:
            self._enemy_arrived(target_id)
            return
        px,py=self.player_position_yards
        factor = self.melee_radius_yards / distance
        destination=(px+(pos[0]-px)*factor, py+(pos[1]-py)*factor)
        self._enemy_motion[target_id] = (now,now+travel,pos,destination)
        self._approaching_targets.add(target_id)
        self.queue.push(CombatEvent(time_s=now+travel,kind='SpatialEnemyArrived',
            actor_id=self.primary_actor_id,target_id=target_id,
            payload={'travel_s': travel, 'motion_generation': generation}))

    def _freeze_enemy_approach(self, target_id: str) -> None:
        """Invalidate previously queued arrival without losing distance travelled."""
        if target_id not in self._enemy_motion:
            return
        self.enemy_positions_yards[target_id] = self._enemy_position_at(target_id)
        self._enemy_motion.pop(target_id, None)
        self._approaching_targets.discard(target_id)
        self._enemy_motion_generation[target_id] = self._enemy_motion_generation.get(target_id,0)+1

    def engage_target(self, target_id: str) -> None:
        """Tag one 2D enemy; start sourced-speed approach unless immobilized."""
        if not self.multi_target:
            raise ValueError('engage_target requires a 2D multi-target encounter')
        if target_id not in self.targets or not self.targets[target_id].alive:
            raise ValueError('unknown or defeated pack target')
        if target_id in self._engaged_targets:
            return
        self._engaged_targets.add(target_id)
        self.actor.metadata['in_combat'] = True
        self._begin_enemy_approach(target_id)

    def _enemy_arrived(self, target_id: str) -> None:
        if target_id in self._enemy_motion:
            self.enemy_positions_yards[target_id] = self._enemy_position_at(target_id)
            self._enemy_motion.pop(target_id, None)
        self._approaching_targets.discard(target_id)
        old_pos = self.enemy_positions_yards[target_id]
        px, py = self.player_position_yards
        distance = hypot(old_pos[0]-px, old_pos[1]-py)
        if distance > self.melee_radius_yards:
            factor = self.melee_radius_yards / distance
            self.enemy_positions_yards[target_id] = (px+(old_pos[0]-px)*factor,
                                                      py+(old_pos[1]-py)*factor)
        self._melee_targets.add(target_id)
        if self.multi_target and self.target.id == target_id:
            self._sync_auto_attacks(float(self.actor.current_time_s))
        for attack in self.scheduled_incoming_attacks.values():
            if str(attack.source_actor_id) == target_id:
                self._schedule_enemy_swing(attack)

    def select_target(self, target_id: str) -> None:
        if target_id not in self.targets or not self.targets[target_id].alive:
            raise ValueError('unknown or defeated target')
        if target_id != self.target.id:
            self.target = self.targets[target_id]
            if self.multi_target:
                # A queued melee swing may not hit the previous target after
                # a target swap, nor hit the new target before approaching.
                self._restart_auto_swings(float(self.actor.current_time_s))

    def _next_engaged_target(self) -> str | None:
        """Prefer engaged victims; otherwise select a visible idle mob for pull.

        Selection does not tag an idle mob. The APL must use a sourced
        ranged action or close the distance before a melee strike can land.
        """
        live=(t.id for t in self.targets.values() if t.alive)
        return next(iter(sorted(live, key=lambda tid: (
            tid not in self._engaged_targets,
            self._enemy_distance(tid) > self.melee_radius_yards+1e-9,
            self._enemy_distance(tid), tid))), None)

    def _sourced_hostile_action_range(self, action: ActionDefinition) -> float | None:
        # A sourced caster-centered area has no selected-enemy range gate.
        # Its own radius is enforced independently on each live 2D victim.
        if action.metadata.get('aoe_center') == 'actor':
            return None
        if not any(str(getattr(effect, 'target', '')) == 'enemy'
                   for effect in action.effects):
            return None
        source_range = action.metadata.get('range_yards')
        if source_range is None:
            return self.melee_radius_yards
        distance = float(source_range)
        if not isfinite(distance) or distance <= 0:
            raise ValueError('INVALID_SOURCED_ACTION_RANGE')
        return distance

    def select_reachable_target(self, action: ActionDefinition) -> bool:
        """Retarget only to an already reachable live enemy, without free travel.

        A moving multi-target encounter may carry the player away from the
        original victim during a sourced mode-change opening. Never commit a
        melee strike against that now-distant victim or assume instant aggro.
        """
        if self.spatial_action_in_range(action):
            return True
        if not self.multi_target:
            return False
        limit = self._sourced_hostile_action_range(action)
        if limit is None:
            return True
        charge_effects=tuple(e for e in action.effects if isinstance(e,SpatialChargeEffect))
        min_range=max((e.minimum_range_yards for e in charge_effects),default=0.)
        reachable = sorted((self._enemy_distance(tid), tid)
            for tid, target in self.targets.items()
            if target.alive and tid != self.target.id
            and min_range-1e-9 <= self._enemy_distance(tid) <= limit + 1e-9)
        if not reachable:
            return False
        self.select_target(reachable[0][1])
        return self.spatial_action_in_range(action)

    def spatial_action_in_range(self, action: ActionDefinition) -> bool:
        """Check sourced target reach for both optimizer and runtime executor."""
        if not self.multi_target:
            return True
        max_range = self._sourced_hostile_action_range(action)
        if max_range is None:
            return True
        min_range=max((e.minimum_range_yards for e in action.effects
                       if isinstance(e,SpatialChargeEffect)),default=0.)
        return bool(self.target.alive and
                    min_range-1e-9 <= self._enemy_distance(self.target.id) <= max_range + 1e-9)

    @staticmethod
    def _source_actor_area_radius(action: ActionDefinition) -> float:
        radius = action.metadata.get('aoe_radius_yards')
        if radius is None:
            raise ValueError('AOE_SOURCE_RADIUS_UNAVAILABLE')
        radius = float(radius)
        if not isfinite(radius) or radius <= 0:
            raise ValueError('INVALID_SOURCE_AOE_RADIUS')
        return radius

    def _aoe_victims(self, action: ActionDefinition, effect: DamageEffect | ControlEffect | TargetStatDebuffEffect) -> tuple[str, ...]:
        """Source-bounded hostile targets at the actual event time, not spawn time."""
        declared = action.metadata.get('max_targets')
        center = action.metadata.get('aoe_center')
        if center == 'actor' and effect.target == 'enemies':
            radius = self._source_actor_area_radius(action)
            if declared is not None and (isinstance(declared, bool) or
                    not isinstance(declared, int) or declared < 1):
                raise ValueError('AOE_SOURCE_TARGET_CAP_UNAVAILABLE')
            if not self.multi_target:
                # The single-mob runtime has no 2D position. The 2D path
                # below is authoritative for simultaneous spatial pulls.
                return (self.target.id,) if self.target.alive else ()
            candidates = sorted((self._enemy_distance(key), key)
                for key, target in self.targets.items() if target.alive
                and self._enemy_distance(key) <= radius + 1e-9)
            victims = tuple(key for _, key in candidates[:declared])
            # An actual AoE hit/control is an aggro event, even when the mob
            # was outside passive proximity aggro. Tag at effect application,
            # not at cast start, so root suspends the real paid approach.
            for victim_id in victims:
                if victim_id not in self._engaged_targets:
                    self.engage_target(victim_id)
            return victims
        if declared is None and effect.target != 'enemies':
            return (self.target.id,)
        if not self.multi_target:
            return (self.target.id,)
        if isinstance(declared, bool) or not isinstance(declared, int) or declared < 1:
            raise ValueError('AOE_SOURCE_TARGET_CAP_UNAVAILABLE')
        radius = float(action.metadata.get('aoe_radius_yards', self.melee_radius_yards))
        if not isfinite(radius) or radius <= 0:
            raise ValueError('INVALID_SOURCE_AOE_RADIUS')
        candidates = []
        for key in sorted(self._engaged_targets & self._melee_targets):
            if not self.targets[key].alive:
                continue
            distance = self._enemy_distance(key)
            if distance <= radius + 1e-9:
                candidates.append((distance, key))
        return tuple(key for _, key in sorted(candidates)[:declared])

    def _enforce_source_control_target_cap(self, event: CombatEvent,
                                           action: ActionDefinition, control_id: str,
                                           spec: Mapping[str, Any]) -> None:
        """Replace oldest same-owner/same-family control at its sourced cap.

        A reapplication on the same target refreshes its slot. The old
        expiration event is harmless because expiry checks target state.
        """
        cap=spec.get('max_targets')
        if (type(cap) is not int or not 1<=cap<=16 or
                not str(spec.get('base_source_url','')).startswith('https://')):
            raise ValueError('INVALID_SOURCE_CONTROL_TARGET_CAP')
        family=action.family_key
        owned=sorted((started,target_id) for (target_id,cid),
            (owner,group,started) in self._source_control_owners.items()
            if cid==control_id and owner==self.actor.id and group==family
            and target_id!=self.target.id and self.targets[target_id].alive
            and self.targets[target_id].active_controls.get(cid,0.)>event.time_s+1e-12)
        while len(owned)>=cap:
            _,evicted=owned.pop(0)
            victim=self.targets[evicted]
            victim.active_controls.pop(control_id,None)
            self._control_behaviors.pop((evicted,control_id),None)
            self._source_control_owners.pop((evicted,control_id),None)
            if self.multi_target:
                self._begin_enemy_approach(evicted)
            self.queue.push(CombatEvent(time_s=event.time_s,kind='ControlTargetCapEvicted',
                actor_id=self.actor.id,target_id=evicted,action_id=event.action_id,
                payload={'control_id':control_id,'replacement_target_id':self.target.id,
                         'max_targets':cap,'source_url':spec['base_source_url']}))
        self._source_control_owners[(self.target.id,control_id)]=(
            self.actor.id,family,float(event.time_s))

    def pack_summary(self) -> dict:
        return {'all_defeated': all(not target.alive for target in self.targets.values()),
                'target_health': {key:float(target.health) for key,target in self.targets.items()},
                'target_death_s':dict(self._pack_target_death_times),
                'engaged_targets':sorted(self._engaged_targets),
                'player_health':self.actors[self.primary_actor_id].resource_amount('health'),
                'shared_runtime_events':self.event_transitions}

    @contextmanager
    def _actor_context(self, actor_id: str):
        """Scope one event/action to its owner without a separate pet simulator."""
        selected = self.actors.get(str(actor_id))
        if selected is None:
            raise ValueError(f"unknown combat actor: {actor_id}")
        previous = self.actor
        previous_power = self.spell_power
        self.actor = selected
        self.spell_power = self.actor_spell_power[selected.id]
        try:
            yield
        finally:
            self.actor = previous
            self.spell_power = previous_power

    def actor_state(self, actor_id: str) -> ActorState:
        """Read independent readiness/resources for any registered actor."""
        return self.actors[str(actor_id)]

    def enqueue_summon(self, summon_id: str, *, at_time_s: float | None = None) -> float:
        """Schedule source-declared spawn and expiry on the same combat clock."""
        definition = self.timed_summons[str(summon_id)]
        now = float(self.actors[self.primary_actor_id].current_time_s)
        when = now if at_time_s is None else float(at_time_s)
        if when + 1e-12 < now:
            raise ValueError("cannot spawn summon in the past")
        if summon_id in self.summon_pending or self.actor_active[definition.summoned_actor_id]:
            raise ValueError("summon already active or spawn pending")
        generation = self.summon_generation[summon_id] + 1
        self.summon_generation[summon_id] = generation
        self.summon_pending.add(summon_id)
        self.queue.push(CombatEvent(time_s=when, kind="SummonSpawn",
            actor_id=definition.summoned_actor_id, target_id=definition.owner_actor_id,
            action_id=summon_id, payload={"generation": generation,
                "duration_s": float(definition.duration_s), "summon_id": summon_id}))
        return when

    def actor_is_active(self, actor_id: str) -> bool:
        return bool(self.actor_active[str(actor_id)])

    def _effective_auto_swing_s(self, attack: AutoAttackDefinition) -> float:
        # The aura facts supply the multiplier; the runtime does not know any
        # spell names. A 1.4 attack-rate multiplier yields 1/1.4 swing time.
        rate = 1.0
        if attack.attack_type == 'melee':
            for value in self.actor.aura_attack_speed_multipliers.values():
                rate *= float(value)
        if not isfinite(rate) or rate <= 0:
            raise ValueError('invalid sourced aura auto-attack speed')
        return float(attack.swing_time_s) / rate

    def _restart_auto_swings(self, at_time_s: float) -> None:
        # Invalidate pending swings on an attack-speed transition. The next
        # swing is scheduled from this transition, not at the stale cadence.
        for attack_id in tuple(self.auto_attack_active_generation):
            self.auto_attack_active_generation.pop(attack_id, None)
        self._sync_auto_attacks(at_time_s)

    def _remove_actor_aura_modifiers(self, aura_id: str) -> bool:
        old = self.actor.aura_stat_deltas.pop(aura_id, {})
        for stat, value in old.items():
            self.actor.stats[stat] = float(self.actor.stats.get(stat, 0.0)) - float(value)
        capacities=self.actor.aura_resource_capacity_deltas.pop(aura_id,{})
        for resource,value in capacities.items():
            before=float(self.actor.resource_capacity[resource])
            after=before-float(value)
            if after <= 0:
                raise ValueError('invalid sourced aura capacity removal')
            if resource in self.actor.resources:
                self.actor.resources[resource]=float(self.actor.resources[resource])*after/before
            self.actor.resource_capacity[resource]=after
        speed_changed = self.actor.aura_attack_speed_multipliers.pop(aura_id, None) is not None
        # A shield belongs to its aura generation. Expiry, exclusive removal
        # and refresh must not leave invisible absorb capacity behind.
        self.actor.absorb_shields.pop(aura_id, None)
        return speed_changed

    def _auto_attack_eligible(self, attack: AutoAttackDefinition) -> bool:
        if self._active_stealth():
            return False
        if (str(attack.owner_actor_id) != str(self.actor.id) or not self.target.alive
                or not self.actor_active.get(self.actor.id, False)):
            return False
        if (self.multi_target and attack.attack_type == 'melee'
                and attack.owner_actor_id == self.primary_actor_id
                and self._enemy_distance(self.target.id) > self.melee_radius_yards + 1e-9):
            return False
        if attack.required_mode_id is not None and str(self.actor.current_mode_id or "") != str(attack.required_mode_id):
            return False
        if attack.exclusive_with_casts and str(self.actor.id) in self.actor_cast_busy_until:
            return False
        if any(not self.actor.resource_positive(str(incoming.health_resource_id))
               for incoming in getattr(self, "scheduled_incoming_attacks", {}).values()
               if str(incoming.target_actor_id) == str(self.actor.id)):
            return False
        return expected_auto_attack_swing(attack, actor=self.actor)["expected_damage"] > 0.0

    def _sync_auto_attacks(self, time_s: float) -> None:
        now = float(time_s)
        for attack_id, attack in self.auto_attacks.items():
            with self._actor_context(str(attack.owner_actor_id)):
                self._sync_one_auto_attack(now, attack_id, attack)

    def _sync_one_auto_attack(self, now: float, attack_id: str, attack: AutoAttackDefinition) -> None:
        active_generation = self.auto_attack_active_generation.get(attack_id)
        eligible = self._auto_attack_eligible(attack)
        if eligible and active_generation is None:
            generation = int(self.auto_attack_generation.get(attack_id, 0)) + 1
            self.auto_attack_generation[attack_id] = generation
            self.auto_attack_active_generation[attack_id] = generation
            self.queue.push(CombatEvent(
                time_s=now, kind="AutoAttackStarted", actor_id=self.actor.id,
                target_id=self.target.id, action_id=attack_id,
                payload={
                    "auto_attack_id": attack_id, "generation": generation,
                    "swing_time_s": self._effective_auto_swing_s(attack),
                    "required_mode_id": attack.required_mode_id,
                },
            ))
            self.queue.push(CombatEvent(
                time_s=now + self._effective_auto_swing_s(attack), kind="AutoAttackSwing",
                actor_id=self.actor.id, target_id=self.target.id, action_id=attack_id,
                payload={"auto_attack_id": attack_id, "generation": generation},
            ))
        elif not eligible and active_generation is not None:
            pending = self.pending_queued_swing.pop(attack_id, None)
            if pending is not None:
                self.queue.push(CombatEvent(time_s=now, kind='QueuedSwingCancelled',
                    actor_id=self.actor.id,target_id=self.target.id,action_id=pending[0],
                    payload={'auto_attack_id':attack_id,'reason':'auto_attack_ineligible'}))
            self.auto_attack_active_generation.pop(attack_id, None)
            self.queue.push(CombatEvent(
                time_s=now, kind="AutoAttackStopped", actor_id=self.actor.id,
                target_id=self.target.id, action_id=attack_id,
                payload={
                    "auto_attack_id": attack_id, "generation": int(active_generation),
                    "reason": "target_dead_or_requirements_not_met",
                },
            ))

    def resource_amount(self, resource_id: str) -> float | None:
        return _resource_amount(self.actor, self.target, resource_id)

    def _spend_resource(self, resource_id: str, amount: float) -> tuple[float, float]:
        host = _resource_host(self.actor, self.target, resource_id)
        if host is None:
            raise ValueError(f"resource {resource_id!r} requires a target host")
        return host.spend(resource_id, amount)

    def _change_resource(self, resource_id: str, *, operation: str, amount: float) -> tuple[float, float]:
        host = _resource_host(self.actor, self.target, resource_id)
        if host is None:
            raise ValueError(f"resource {resource_id!r} requires a target host")
        if host is self.actor:
            if operation == "add":
                return self.actor.restore(resource_id, amount)[:2]
            if operation == "set":
                before = self.actor.resource_amount(resource_id)
                if before is None:
                    raise ValueError(f"resource {resource_id!r} unavailable")
                cap = self.actor.resource_capacity.get(str(resource_id))
                after = max(0.0, float(amount))
                if cap is not None:
                    after = min(float(cap), after)
                self.actor.resources[str(resource_id)] = after
                return float(before), float(after)
            raise ValueError(f"unsupported resource change operation: {operation}")
        return self.target.change_resource(resource_id, operation=operation, amount=amount)

    def _generated_resource_ids(self, action_id: str | None) -> tuple[str, ...]:
        source_action=self.actions.get(str(action_id))
        return tuple(sorted({effect.resource_id for effect in
            (source_action.effects if source_action else ())
            if isinstance(effect,ResourceChangeEffect) and
            effect.operation=='add' and effect.amount>0}))

    def _source_joint_draw(self, time_s: float, action_id: str | None,
                           target_id: str | None, purpose: str) -> float:
        # One stable event-scoped uniform variate. Seed is scenario data, not
        # class/spell behavior. The trace ordinal distinguishes simultaneous
        # events with identical actor, action, target and timestamp.
        from hashlib import sha256
        key = (f'{self.sampling_seed}|{self.actor.id}|{target_id}|{action_id}|'
               f'{float(time_s):.9f}|{len(self.trace)}|{purpose}')
        return int.from_bytes(sha256(key.encode()).digest()[:8], 'big') / 2**64

    def _sample_joint_melee_critical(self, event: CombatEvent) -> None:
        # Opt in only if an ACTIVE resource rule needs discrete critical hits.
        # Unrelated classes and old expected-value evaluations are untouched.
        if event.payload.get('periodic') or str(event.payload.get('school','')).lower()!='physical':
            return
        generated = self._generated_resource_ids(event.action_id)
        applicable = False
        for definition in self.actor.resource_definitions.values():
            if not self.actor.resource_is_active(str(definition.id)):
                continue
            for rule in definition.event_gain_rules:
                if (rule.event_kind!='nonperiodic_melee_critical' or
                        rule.metadata.get('resolution')!='sampled_joint_critical' or
                        (rule.required_mode_id is not None and
                         rule.required_mode_id!=self.actor.current_mode_id)):
                    continue
                required=rule.filters.get('required_generated_resource')
                if required is None or str(required) in generated:
                    applicable=True;break
            if applicable:break
        if not applicable:return
        weights=event.payload.get('outcome_weights')
        if not isinstance(weights,dict):
            raise ValueError('JOINT_CRITICAL_PROC_REQUIRES_ATTACK_OUTCOME_WEIGHTS')
        miss,hit,crit=(float(weights.get(k,0.)) for k in ('miss','hit','crit'))
        if (any(not isfinite(v) or v<0. or v>1. for v in (miss,hit,crit)) or
                abs(miss+hit+crit-1.)>1e-8):
            raise ValueError('INVALID_JOINT_CRITICAL_OUTCOME_WEIGHTS')
        multiplier=float(event.payload.get('crit_multiplier',1.))
        expected_factor=hit+crit*multiplier
        if not 1. <= multiplier <= 10. or expected_factor<=0.:
            raise ValueError('INVALID_JOINT_CRITICAL_DAMAGE_FACTORS')
        self._apply_joint_critical_outcome(event, miss=miss, hit=hit, crit=crit,
            multiplier=multiplier, expected_factor=expected_factor,
            purpose='hit_crit', resolution='sampled_damage_and_proc')

    def _is_source_spell_crit_haste_event(self, event: CombatEvent) -> bool:
        """Only direct cast-spell damage, not wand, reactive or melee attacks."""
        rule = self.actor.metadata.get('source_timed_spell_crit_haste')
        return bool(rule and rule.get('event_kind') == 'nonperiodic_spell_crit'
            and str(event.action_id) in self.actions
            and not event.payload.get('auto_attack')
            and not event.payload.get('queued_swing_replacement')
            and not event.payload.get('periodic')
            and str(event.payload.get('school', '')).lower() not in ('physical', '', 'bleed')
            and not event.payload.get('triggered'))

    def _sample_joint_spell_critical(self, event: CombatEvent) -> None:
        """Source-activated direct spell crit: damage and haste share one draw."""
        if not self._is_source_spell_crit_haste_event(event):
            return
        weights = event.payload.get('outcome_weights')
        if not isinstance(weights, dict):
            raise ValueError('JOINT_SPELL_CRIT_REQUIRES_OUTCOME_WEIGHTS')
        miss, hit, crit = (float(weights.get(k, 0.)) for k in ('miss', 'hit', 'crit'))
        if (any(not isfinite(v) or not 0. <= v <= 1. for v in (miss, hit, crit))
                or abs(miss + hit + crit - 1.) > 1e-8):
            raise ValueError('INVALID_JOINT_SPELL_CRIT_WEIGHTS')
        multiplier = float(event.payload.get('crit_multiplier', 1.))
        expected_factor = hit + crit * multiplier
        if not 1. <= multiplier <= 10. or expected_factor <= 0.:
            raise ValueError('INVALID_JOINT_SPELL_CRIT_DAMAGE_FACTOR')
        self._apply_joint_critical_outcome(event, miss=miss, hit=hit, crit=crit,
            multiplier=multiplier, expected_factor=expected_factor,
            purpose='spell_hit_crit', resolution='sampled_spell_damage_and_haste')

    def _apply_joint_critical_outcome(self, event: CombatEvent, *, miss: float,
                                      hit: float, crit: float, multiplier: float,
                                      expected_factor: float, purpose: str,
                                      resolution: str) -> None:
        """One seeded event draw drives both damage and source event procs."""
        raw = float(event.payload['amount']) / expected_factor
        draw = self._source_joint_draw(event.time_s, event.action_id,
                                       event.target_id, purpose)
        outcome = 'miss' if draw < miss else 'hit' if draw < miss + hit else 'crit'
        event.payload.update({'amount': raw * {'miss': 0., 'hit': 1., 'crit': multiplier}[outcome],
            'sampled_outcome': outcome, 'sampled_critical_count': int(outcome == 'crit'),
            'sampled_hit_crit_roll': draw, 'joint_critical_resolution': resolution})

    def _queue_resource_event_gains(
        self, *, event_kind: str, time_s: float, source_action_id: str | None, payload: Mapping[str, Any],
        target_id: str | None = None,
    ) -> int:
        """Queue data-driven Resource gains, including target-scoped resources."""
        queued = 0
        kind = str(event_kind)
        for definition in self.actor.resource_definitions.values():
            resource_id = str(definition.id)
            recipient = self.targets.get(str(target_id), self.target) if target_id is not None else self.target
            host = _resource_host(self.actor, recipient, resource_id)
            if host is None or not bool(host.resource_active.get(resource_id, False)):
                continue
            for rule in tuple(getattr(definition, "event_gain_rules", ()) or ()):
                if str(rule.event_kind) != kind:
                    continue
                if rule.required_mode_id is not None and str(self.actor.current_mode_id or "") != str(rule.required_mode_id):
                    continue
                filters = dict(rule.filters or {})
                required_generated=filters.pop('required_generated_resource',None)
                if required_generated is not None and str(required_generated) not in (
                        payload.get('generated_resource_ids') or ()):
                    continue
                if any(payload.get(str(k)) != v for k, v in filters.items()):
                    continue
                value = float(payload.get(str(rule.event_value_field), 0.0) or 0.0)
                resolution = str(rule.metadata.get('resolution',''))
                if resolution in ('sampled_joint_critical','sampled_joint_dodge'):
                    required_kind = ('nonperiodic_melee_critical' if resolution == 'sampled_joint_critical'
                                     else 'incoming_physical_dodge')
                    if kind != required_kind or value not in (0.,1.):
                        raise ValueError('JOINT_PROC_REQUIRES_DISCRETE_MATCHING_EVENT')
                    chance = rule.metadata.get('proc_probability')
                    if type(chance) not in (int,float) or not 0. <= float(chance) <= 1.:
                        raise ValueError('INVALID_SOURCED_JOINT_PROC_PROBABILITY')
                    if value and self._source_joint_draw(time_s, source_action_id,
                            target_id, 'proc:'+str(rule.id)) >= float(chance):
                        continue
                requested = max(0.0, float(rule.flat_amount) + value * float(rule.multiplier))
                if requested <= 1e-12:
                    continue
                self.queue.push(CombatEvent(
                    time_s=float(time_s), kind="ResourceEventGain", actor_id=self.actor.id, target_id=host.id,
                    action_id=source_action_id, payload={
                        "resource_id": resource_id, "rule_id": str(rule.id), "event_kind": kind,
                        "event_value_field": str(rule.event_value_field), "event_value": value,
                        "requested_gain": requested, "source_payload": dict(payload),
                    },
                ))
                queued += 1
        return queued

    def _queue_event_triggers(
        self, *, event_kind: str, time_s: float, source_action_id: str | None, payload: Mapping[str, Any],
    ) -> int:
        """Queue active data-driven event triggers for one generic combat event."""
        queued = 0
        kind = str(event_kind)
        for trigger in self.triggers.values():
            if not bool(trigger.active_by_default) or str(trigger.owner_actor_id) != str(self.actor.id):
                continue
            if str(trigger.event_kind) != kind:
                continue
            if trigger.required_mode_id is not None and str(self.actor.current_mode_id or "") != str(trigger.required_mode_id):
                continue
            if trigger.required_aura_id is not None:
                aura = self.actor.active_auras.get(str(trigger.required_aura_id))
                if aura is None or float(aura.expires_at_s) <= float(time_s) + 1e-12:
                    continue
            if any(payload.get(str(k)) != v for k, v in dict(trigger.filters).items()):
                continue
            probability = 1.0
            if trigger.event_probability_field is not None:
                probability = max(0.0, min(1.0, float(payload.get(str(trigger.event_probability_field), 0.0))))
            if probability <= 0.0:
                continue
            scale = 1.0
            if trigger.event_scale_field is not None:
                ref = trigger.event_scale_reference
                if ref is None or not isfinite(float(ref)) or float(ref) <= 0:
                    raise ValueError('trigger missing positive sourced event scale reference')
                if trigger.event_scale_field not in payload:
                    raise ValueError('trigger event scale field absent from source event')
                scale = float(payload[trigger.event_scale_field]) / float(ref)
                if not isfinite(scale) or scale < 0:
                    raise ValueError('invalid trigger event scale')
            self.queue.push(CombatEvent(
                time_s=float(time_s), kind="TriggerFired", actor_id=self.actor.id, target_id=self.target.id,
                action_id=str(trigger.id), payload={
                    "trigger_id": str(trigger.id), "source_event_kind": kind,
                    "source_action_id": source_action_id, "event_probability": float(probability),
                    "effect_count": len(trigger.effects), "source_payload": dict(payload),
                    "event_scale": float(scale),
                },
            ))
            queued += 1
        return queued

    def emit_resource_event(
        self, event_kind: str, *, at_time_s: float | None = None, source_action_id: str | None = None, **payload: Any,
    ) -> int:
        """Public generic hook for combat events not yet owned by this runtime.

        G27 uses automatic ``damage_dealt`` dispatch. G28 can feed
        ``damage_taken`` here after its incoming-attack/mitigation primitive
        resolves the correct Rage input basis.
        """
        when = float(self.actor.current_time_s if at_time_s is None else at_time_s)
        if when + 1e-12 < float(self.actor.current_time_s):
            raise ValueError("cannot emit a resource event in the past")
        self.advance_to(when)
        queued = self._queue_resource_event_gains(
            event_kind=str(event_kind), time_s=when, source_action_id=source_action_id, payload=payload,
        )
        self.advance_to(when)
        return queued

    def _sample_joint_incoming_dodge(self, attack: IncomingAttackDefinition,
                                     when: float, resolution: dict[str, Any]) -> None:
        """Sample only sourced discrete dodge rules; leave all other attacks expected."""
        # A source-declared discrete dodge proc must consume the same actual
        # avoidance outcome as incoming damage, never an independent fractional
        # expected-dodge event. Other rules preserve the legacy expectation.
        discrete_dodge = any(
            self.actor.resource_is_active(str(resource.id)) and
            any(rule.event_kind == 'incoming_physical_dodge' and
                rule.metadata.get('resolution') == 'sampled_joint_dodge' and
                (rule.required_mode_id is None or
                 rule.required_mode_id == self.actor.current_mode_id)
                for rule in resource.event_gain_rules)
            for resource in self.actor.resource_definitions.values())
        if discrete_dodge and str(attack.school).lower() == 'physical':
            landed=float(resolution['source_hit_chance'])
            dodge=float(resolution['actor_dodge_chance'])
            miss_bonus=float(resolution['actor_incoming_miss_bonus'])
            miss=1.-landed
            dodge_weight=landed*dodge
            bonus_miss=landed*min(miss_bonus,max(0.,1.-dodge))
            hit=landed*max(0.,1.-dodge-miss_bonus)
            draw=self._source_joint_draw(when,str(attack.id),str(attack.source_actor_id),
                'incoming_hit_dodge')
            outcome=('miss' if draw<miss else 'dodge' if draw<miss+dodge_weight
                     else 'miss' if draw<miss+dodge_weight+bonus_miss else 'hit')
            resolution.update({
                'expected_hit_chance':float(resolution['hit_chance']),
                'hit_chance':float(outcome=='hit'),
                'landed_raw_damage':float(attack.raw_damage) if outcome=='hit' else 0.,
                'post_mitigation_damage':(
                    float(attack.raw_damage)*(1.-float(resolution['armor_reduction']))
                    if outcome=='hit' else 0.),
                'sampled_incoming_outcome':outcome,
                'sampled_dodge_count':int(outcome=='dodge'),
                'sampled_incoming_roll':draw,
                'resolution':'sampled_joint_incoming_damage_dodge_proc',
            })

    def resolve_incoming_attack(
        self, attack: IncomingAttackDefinition, *,
        mitigation_rules: Sequence[ArmorMitigationDefinition] = (),
        at_time_s: float | None = None,
    ) -> dict[str, Any]:
        """Resolve one generic incoming attack against actor Health.

        Enemy scheduling/multi-Actor AI is intentionally separate. G28 owns the
        reusable outcome -> mitigation -> survivability -> projected-event path.
        """
        when = float(self.actor.current_time_s if at_time_s is None else at_time_s)
        if when + 1e-12 < float(self.actor.current_time_s):
            raise ValueError("cannot resolve an incoming attack in the past")
        self.advance_to(when)
        if str(attack.target_actor_id) != str(self.actor.id):
            raise ValueError(f"incoming attack target {attack.target_actor_id!r} != actor {self.actor.id!r}")
        # Sourced stuns disable enemy attack execution, including ordinary
        # scheduled swings and direct incoming-attack calls. Root remains a
        # movement-only control. The existing source-declared cadence still
        # advances; an interrupted swing never yields Health damage, on-hit
        # events or damage-taken Rage. This is general event semantics, not a
        # Bash- or class-specific conditional.
        source_target = self.targets.get(str(attack.source_actor_id), self.target)
        # Damage-independent incapacitation and stun both disable attack actions.
        # Roots only prevent movement: they never suppress enemy melee swings.
        preventing_control = next((control_id for control_id, expiry in source_target.active_controls.items()
            if expiry > when + 1e-12 and (control_id == 'stun' or
            self._control_behaviors.get((source_target.id, control_id), {}).get('prevents_enemy_actions'))), None)
        if preventing_control is not None:
            health=float(self.actor.resource_amount(str(attack.health_resource_id)) or 0.0)
            suppressed={
                'incoming_attack_id':str(attack.id), 'school':str(attack.school),
                'suppressed_by_control':preventing_control,'health_resource_id':str(attack.health_resource_id),
                'health_before':health,'health_after':health,
                'health_damage_applied':0.0,'absorbed_damage':0.0,
                'actor_alive':bool(health>1e-12),
            }
            self.trace.append(CombatEvent(
                time_s=when,kind='IncomingAttackSuppressed',
                actor_id=str(attack.source_actor_id),target_id=self.actor.id,
                action_id=str(attack.id),payload=dict(suppressed)))
            return suppressed
        # A source-valued target hit-chance debuff modifies only attacks
        # from the afflicted enemy. Other target debuffs (e.g. Armor) do not
        # change incoming hit probability. Timed aura generations expire.
        source_hit_delta=sum(float(delta) for stat,delta,generation in
            source_target.active_stat_modifiers.values() if stat=='hit_chance')
        adjusted_attack=(replace(attack,hit_chance=max(0.,min(1.,
            float(attack.hit_chance)+source_hit_delta)))
            if source_hit_delta else attack)
        enemy_ap_delta=sum(float(delta) for stat,delta,generation in
            source_target.active_stat_modifiers.values() if stat=='melee_attack_power')
        if enemy_ap_delta and attack.school=='physical':
            swing=float(attack.metadata.get('representative_swing_s',0.))
            ap_per_dps=float(attack.metadata.get('melee_ap_per_dps',0.))
            if not (isfinite(swing) and swing>0 and isfinite(ap_per_dps) and ap_per_dps>0):
                raise ValueError('SOURCE_INCOMING_MELEE_AP_CONVERSION_MISSING')
            adjusted_attack=replace(adjusted_attack,raw_damage=max(0.,
                float(adjusted_attack.raw_damage)+enemy_ap_delta*swing/ap_per_dps))
        resolution = expected_incoming_attack(adjusted_attack, actor=self.actor, mitigation_rules=mitigation_rules)
        if enemy_ap_delta and attack.school=='physical':
            resolution['source_enemy_melee_ap_debuff_delta']=enemy_ap_delta
            resolution['incoming_raw_damage_after_melee_ap_debuff']=float(adjusted_attack.raw_damage)
        if source_hit_delta:
            resolution['source_target_hit_debuff_delta']=float(source_hit_delta)
        self._sample_joint_incoming_dodge(adjusted_attack,when,resolution)
        health_id = str(attack.health_resource_id)
        damage = float(resolution["post_mitigation_damage"])
        absorbed = 0.0
        for shield_id in tuple(sorted(self.actor.absorb_shields)):
            available = max(0.0, float(self.actor.absorb_shields[shield_id]))
            used = min(damage, available)
            damage -= used; absorbed += used
            remaining = available - used
            if remaining <= 1e-12:
                self.actor.absorb_shields.pop(shield_id, None)
            else:
                self.actor.absorb_shields[shield_id] = remaining
            if damage <= 1e-12:break
        # Validate optional source semantics before altering Health or a cast.
        # A talent's avoidance percentage alone cannot establish a server
        # pushback duration, and source-less values must fail atomically.
        pushback=float(attack.metadata.get('cast_pushback_on_hit_s',0.))
        if not isfinite(pushback) or pushback < 0.:
            raise ValueError('INVALID_SOURCE_CAST_PUSHBACK_VALUE')
        if pushback > 0. and not str(attack.metadata.get('cast_pushback_source_url','')).startswith('https://'):
            raise ValueError('CAST_PUSHBACK_REQUIRES_SOURCE_PROVENANCE')
        before, after, applied = self.actor.deplete(health_id, damage)
        if applied > 1e-12 and pushback > 0.:
            cast_id=self._active_cast_action.get(self.actor.id)
            busy=float(self.actor_cast_busy_until.get(self.actor.id,0.))
            if cast_id and busy > when + 1e-12:
                cast=self.actions[cast_id]
                avoidance=float(cast.metadata.get('cast_pushback_avoidance_chance',0.))
                if not isfinite(avoidance) or not 0. <= avoidance <= 1.:
                    raise ValueError('INVALID_SOURCE_CAST_PUSHBACK_AVOIDANCE')
                # Incoming swings are expected-value outcomes. Multiply by
                # their real hit probability; fractional expected Health loss
                # is not a guaranteed cast interruption.
                delay=pushback*float(resolution['hit_chance'])*(1.-avoidance)
                if delay > 1e-12:
                    new_busy=busy+delay
                    self.actor_cast_busy_until[self.actor.id]=new_busy
                    self.trace.append(CombatEvent(time_s=when,kind='CastPushbackApplied',
                        actor_id=self.actor.id,target_id=self.actor.id,action_id=cast_id,
                        payload={'incoming_attack_id':str(attack.id),
                            'delay_s':delay,'original_cast_end_s':busy,
                            'new_cast_end_s':new_busy,'avoidance_chance':avoidance,
                            'source_url':attack.metadata['cast_pushback_source_url']}))
        payload = {
            **resolution, "incoming_attack_id": str(attack.id), "school": str(attack.school),
            "health_resource_id": health_id, "health_before": float(before), "health_after": float(after),
            "health_damage_applied": float(applied), "absorbed_damage":float(absorbed), "actor_alive": bool(after > 1e-12),
        }
        self.trace.append(CombatEvent(
            time_s=when, kind="IncomingAttackResolved", actor_id=str(attack.source_actor_id),
            target_id=self.actor.id, action_id=str(attack.id), payload=dict(payload),
        ))
        # A dodge is an incoming physical avoidance event, not damage-taken.
        # Emit it even when the attack did zero damage. The expected-value
        # engine preserves the sourced proc chance explicitly in the rule.
        dodge_count=float(payload.get('sampled_dodge_count',
                                      payload.get('expected_dodge_count',0.)))
        if dodge_count > 1e-12:
            self._queue_resource_event_gains(
                event_kind='incoming_physical_dodge',time_s=when,
                source_action_id=str(attack.id),payload=dict(payload))
        # Backwards-compatible generic source operator from concurrent WF442.
        # Event scopes differ, so a single resource rule never gains twice.
        if dodge_count > 1e-12:
            self._queue_resource_event_gains(event_kind='incoming_dodge',
                time_s=when,source_action_id=str(attack.id),payload=payload)
        damage_taken_payload = {**dict(payload), "amount": float(applied),
                                "source_enemy_id":str(attack.source_actor_id),
                                "attack_delivery":str(attack.metadata.get('attack_delivery') or
                                    ('melee' if 'melee_ap_per_dps' in attack.metadata else 'unspecified'))}
        self.trace.append(CombatEvent(
            time_s=when, kind="DamageTaken", actor_id=str(attack.source_actor_id),
            target_id=self.actor.id, action_id=str(attack.id), payload=dict(damage_taken_payload),
        ))
        self._queue_event_triggers(
            event_kind="damage_taken", time_s=when, source_action_id=str(attack.id), payload=damage_taken_payload,
        )
        self._queue_resource_event_gains(
            event_kind="damage_taken", time_s=when, source_action_id=str(attack.id),
            payload={**dict(payload), "amount": float(applied)},
        )
        projection_values = dict(payload)
        for projection in attack.event_projections:
            field = str(projection.source_value_field)
            if field not in projection_values:
                raise ValueError(f"incoming event projection source field {field!r} is unavailable")
            source_value = float(projection_values[field])
            projected_value = max(0.0, float(projection.flat_amount) + source_value * float(projection.multiplier))
            projected_payload = {
                **dict(payload), str(projection.event_value_field): float(projected_value),
                "projection_id": str(projection.id), "projection_source_field": field,
                "projection_source_value": float(source_value),
            }
            self.trace.append(CombatEvent(
                time_s=when, kind="IncomingEventProjected", actor_id=str(attack.source_actor_id),
                target_id=self.actor.id, action_id=str(attack.id),
                payload={"event_kind": str(projection.event_kind), **projected_payload},
            ))
            self._queue_resource_event_gains(
                event_kind=str(projection.event_kind), time_s=when, source_action_id=str(attack.id),
                payload=projected_payload,
            )
        if after <= 1e-12:
            self.trace.append(CombatEvent(
                time_s=when, kind="ActorDied", actor_id=self.actor.id, target_id=self.actor.id,
                action_id=str(attack.id), payload={"health_resource_id": health_id, "health": float(after)},
            ))
        self.advance_to(when)
        return payload

    def schedule_action(self, action: ActionDefinition, *, at_time_s: float | None = None) -> float:
        """Schedule a player or companion action on its own clock and readiness."""
        with self._actor_context(str(action.owner_actor_id)):
            return self._schedule_owned_action(action, at_time_s=at_time_s)

    def enqueue_action(self, action: ActionDefinition, *, at_time_s: float | None = None) -> float:
        """Queue an action without blocking its cast: other actors can start concurrently.

        Returns expected completion time; an ordinary schedule_action retains
        the original synchronous API and advances the shared timeline.  Costs,
        GCD and cooldown are committed at enqueue/start time, never twice.
        """
        with self._actor_context(str(action.owner_actor_id)):
            return self._enqueue_owned_action(action, at_time_s=at_time_s)

    def _schedule_owned_action(self, action: ActionDefinition, *, at_time_s: float | None = None) -> float:
        completion = self._enqueue_owned_action(action, at_time_s=at_time_s)
        # A sourced channeled resource tick may fill its capacity before the
        # channel's maximum duration. Advance on the SAME event queue only to
        # the first full-capacity tick; the tick handler interrupts the channel.
        for effect in action.effects:
            if (isinstance(effect, PeriodicResourceEffect) and
                    effect.metadata.get('stop_channel_on_full') and
                    str(effect.target) in ('actor','self')):
                missing = max(0., float(self.actor.resource_capacity.get(effect.resource_id, 0.)) -
                              float(self.actor.resource_amount(effect.resource_id) or 0.))
                rate = self._periodic_resource_gain(effect)
                if rate > 0 and missing > 0:
                    from math import ceil
                    ticks = ceil((missing - 1e-9)/rate)
                    if ticks * float(effect.tick_interval_s) < float(action.cast_time_s):
                        completion = min(completion, self.actor.current_time_s +
                                         ticks * float(effect.tick_interval_s))
        self.advance_to(completion)
        # A real incoming hit may have extended this cast while processing the
        # original completion event. Synchronous callers must pay the delay.
        if self._active_cast_action.get(self.actor.id) == str(action.id):
            extended=float(self.actor_cast_busy_until.get(self.actor.id,completion))
            if extended > completion + 1e-12:
                self.advance_to(extended)
        return float(self.actor.current_time_s)

    def _periodic_resource_gain(self, effect: PeriodicResourceEffect) -> float:
        """Resolve source-declared per-tick scaling at the actual actor stats."""
        metadata = effect.metadata
        if metadata.get('resource_gain_model') != 'stat_linear_tick':
            return float(effect.amount_per_tick)
        stat = float(self.actor.stats.get(str(metadata['stat_id']), 0.))
        amount = (float(metadata['base_per_tick']) +
                  float(metadata['stat_per_tick']) * stat) * float(metadata['multiplier'])
        if not isfinite(amount) or amount < 0.:
            raise ValueError('INVALID_SOURCE_PERIODIC_RESOURCE_GAIN')
        return amount

    def _source_timed_crit_haste_fraction(self, at_time_s: float) -> tuple[float,float]:
        rule=self.actor.metadata.get('source_timed_spell_crit_haste')
        if not rule or float(self.actor.source_timed_spell_crit_haste_until_s)<=at_time_s+1e-12:
            return 0.,0.
        if (rule.get('event_kind')!='nonperiodic_spell_crit' or
                not 0 < float(rule.get('cast_speed_fraction',0)) < 1 or
                not 0 < float(rule.get('gcd_reduction_fraction',0)) < 1 or
                not 0 < float(rule.get('duration_s',0)) <=60):
            raise ValueError('INVALID_SOURCE_TIMED_CRIT_HASTE_RULE')
        return float(rule['cast_speed_fraction']),float(rule['gcd_reduction_fraction'])

    def _source_next_instant_school(self, action: ActionDefinition) -> str | None:
        """IR-backed school only; never blanket-convert all spell casts to Nature.

        Healing-only actions require explicit school metadata; otherwise their
        school coverage stays outside this particular diagnostic bridge.
        """
        school=str(action.metadata.get('source_spell_school') or '').lower()
        if school:
            return school
        schools={str(e.school).lower() for e in action.effects
                 if isinstance(e,(DamageEffect,PeriodicEffect))}
        return next(iter(schools)) if len(schools)==1 else None

    def effective_source_cast_time(self, action: ActionDefinition) -> float:
        """Actual paid cast duration after a source-attested, expiring charge.

        Read-only: failed eligibility checks and movement pauses never spend a
        charge. The charge is consumed only when the cast is committed.
        """
        base=float(action.cast_time_s)
        school=self._source_next_instant_school(action)
        if (base>0 and school and
                self.actor.source_next_cast_instant_charges.get(school,0)>0 and
                not action.metadata.get('channel')):
            return 0.
        spec=action.metadata.get('source_cast_charge_consumer')
        if not spec:
            return base
        bank=str(spec.get('bank_id',''))
        reduction=float(spec.get('reduction_s',0.))
        if (not bank or not isfinite(reduction) or reduction<=0.
                or not str(spec.get('source_url','')).startswith('https://')
                or action.metadata.get('channel')):
            raise ValueError('INVALID_SOURCE_CAST_CHARGE_CONSUMER')
        return (max(0.,base-reduction) if self.actor.source_cast_charge_count(bank)>0
                else base)

    def _enqueue_owned_action(self, action: ActionDefinition, *, at_time_s: float | None = None) -> float:
        if (action.metadata.get('never_l2_legal') or
                action.metadata.get('execution_tier') == 'L1_PARTIAL_ONLY') and not self.allow_source_partial_l1:
            raise ValueError('SOURCE_PARTIAL_L1_ACTION_FORBIDDEN_IN_PRODUCTION_RUNTIME')
        # Validate every effect *before* changing the clock, spending resources,
        # or committing a cooldown. Channel dispatch must not bypass this gate.
        if action.metadata.get('aoe_center') == 'actor':
            self._source_actor_area_radius(action)
            if not any(getattr(e, 'target', None) == 'enemies' for e in action.effects):
                raise ValueError('SOURCE_AREA_HAS_NO_HOSTILE_EFFECTS')
        elif any(isinstance(e, (ControlEffect, TargetStatDebuffEffect)) and e.target == 'enemies'
                 for e in action.effects):
            raise ValueError('AOE_CONTROL_CENTER_UNAVAILABLE')
        for effect in action.effects:
            if isinstance(effect,ControlEffect) and (
                not isfinite(float(effect.proc_chance)) or
                not 0. <= float(effect.proc_chance) <= 1. or
                not isfinite(float(effect.duration_s)) or float(effect.duration_s) <= 0.):
                raise ValueError('INVALID_SOURCE_CONTROL_PROC_DECLARATION')
        charge_effects=[e for e in action.effects if isinstance(e,SpatialChargeEffect)]
        if charge_effects:
            if len(charge_effects)!=1 or not self.multi_target:
                raise ValueError('SOURCE_SPATIAL_CHARGE_REQUIRES_2D_TARGET')
            charged=charge_effects[0]
            distance=self._enemy_distance(self.target.id)
            if (charged.target!='enemy' or not 0 <= charged.minimum_range_yards <=
                    charged.maximum_range_yards <= 100 or not 0 <= charged.arrival_distance_yards <= self.melee_radius_yards
                    or charged.arrival_position_kind not in ('target_contact','behind_target')
                    or distance < charged.minimum_range_yards-1e-9 or
                    distance > charged.maximum_range_yards+1e-9):
                raise ValueError('SOURCE_SPATIAL_CHARGE_OUT_OF_RANGE_OR_UNVERIFIED')
        effect_kinds = tuple(effect_execution_kind(effect) for effect in action.effects)
        queued_effects = [e for e in action.effects if isinstance(e, QueuedSwingEffect)]
        if queued_effects:
            if (len(queued_effects)!=1 or len(action.effects)!=1 or action.cast_time_s!=0
                    or queued_effects[0].target!='enemy' or not isfinite(queued_effects[0].bonus_damage)
                    or queued_effects[0].bonus_damage < 0):
                raise ValueError('INVALID_QUEUED_SWING_DECLARATION')
            qe=queued_effects[0]
            attack=self.auto_attacks.get(qe.auto_attack_id)
            if attack is None or attack.attack_type!='melee' or attack.owner_actor_id!=action.owner_actor_id:
                raise ValueError('QUEUED_SWING_AUTO_ATTACK_NOT_SOURCE_DEFINED')
        if action.metadata.get('channel') and any(
            kind not in ('periodic_damage', 'periodic_heal', 'periodic_resource')
            for kind in effect_kinds
        ):
            raise ValueError('channel effects must be periodic')
        if at_time_s is not None:
            requested = float(at_time_s)
            if requested + 1e-12 < float(self.actor.current_time_s):
                raise ValueError("cannot schedule an action in the past")
            self.advance_to(requested)
        if float(action.cast_time_s) > 1e-12 and self._player_is_moving():
            raise ValueError('MOVING_CAST_REQUIRES_STATIONARY')
        if not self.actor_active.get(self.actor.id, False):
            raise ActionNotEligibleError(ActionEligibility(False, "actor inactive: summon not spawned or expired",
                float(self.actor.current_time_s), float(self.actor.current_time_s)))
        requires_live_enemy = any(
            str(getattr(effect, "target", "")) == "enemy"
            for effect in action.effects
        )
        if requires_live_enemy and not self.target.alive:
            raise ValueError("cannot execute enemy-targeted action against dead target")
        # Source range is checked *before* spending Rage, mana or a GCD.
        should_spatially_tag = False
        if self.multi_target and requires_live_enemy:
            if not self.spatial_action_in_range(action):
                raise ValueError('SOURCE_ACTION_OUT_OF_RANGE')
            should_spatially_tag = self.target.id not in self._engaged_targets
        prior = self.actions.get(str(action.id))
        if prior is not None and prior != action:
            raise ValueError(f"source action {action.id!r} changed while periodic events are pending")
        eligibility = action_eligibility(action=action, actor=self.actor, target=self.target)
        if queued_effects:
            qe=queued_effects[0]
            if qe.auto_attack_id in self.pending_queued_swing:
                raise ActionNotEligibleError(ActionEligibility(False, 'queued swing already pending',
                    float(self.actor.current_time_s),float(self.actor.current_time_s)))
            if not self._auto_attack_eligible(self.auto_attacks[qe.auto_attack_id]):
                raise ActionNotEligibleError(ActionEligibility(False, 'queued swing auto attack unavailable',
                    float(self.actor.current_time_s),float(self.actor.current_time_s)))
        if not eligibility.eligible:
            raise ActionNotEligibleError(eligibility)
        if any(req.get('kind') == 'out_of_combat' for req in action.requirements):
            if self._engaged_targets:
                raise ActionNotEligibleError(ActionEligibility(False,
                    'requires out of combat', float(self.actor.current_time_s),
                    float(self.actor.current_time_s)))
        # A channel occupies the actor for its whole duration, even after GCD.
        busy_until = float(self.actor_cast_busy_until.get(self.actor.id, 0.0))
        if float(self.actor.current_time_s) + 1e-12 < busy_until:
            raise ActionNotEligibleError(ActionEligibility(False, 'actor is channeling/casting',
                float(self.actor.current_time_s), busy_until))

        start = float(self.actor.current_time_s)
        if requires_live_enemy:
            if self._active_stealth():
                self._break_stealth(action_id=action.id, reason='hostile_action')
            self.actor.metadata['in_combat']=True
        effective_cast_s=self.effective_source_cast_time(action)
        haste_cast,haste_gcd=self._source_timed_crit_haste_fraction(start)
        # Source spell haste is not a faster Claw/Bash/auto swing or form swap.
        spell_action=(any((isinstance(e,(DamageEffect,PeriodicEffect)) and
                            str(e.school).lower()!='physical') or
                           isinstance(e,(HealEffect,PeriodicHealEffect))
                          for e in action.effects)
                      and not any(isinstance(e,ModeChangeEffect) for e in action.effects))
        if not spell_action:
            haste_cast,haste_gcd=0.,0.
        # Apply to *subsequent* owned spells, not the crit-triggering spell.
        # Haste speed is multiplicative on cast rate; GCD reduction is direct.
        if haste_cast and float(action.cast_time_s)>0:
            effective_cast_s /= 1. + haste_cast
        effective_gcd_s=max(0.,float(action.gcd_s)*(1.-haste_gcd))
        charge_spec=action.metadata.get('source_cast_charge_consumer') or {}
        charge_bank=str(charge_spec.get('bank_id',''))
        consumed_charge=(bool(charge_bank) and effective_cast_s < float(action.cast_time_s)-1e-12)
        spent: list[dict[str, float | str]] = []
        for cost in action.costs:
            before, after = self._spend_resource(cost.resource_id, cost.amount)
            spent.append({
                "resource_id": str(cost.resource_id), "amount": float(cost.amount),
                "before": float(before), "after": float(after),
            })
        self.actor.gcd_ready_s = max(float(self.actor.gcd_ready_s), start + effective_gcd_s)
        self.actor.cooldown_ready_s[action.id] = max(
            float(self.actor.cooldown_ready_s.get(action.id, 0.0)),
            start + max(0.0, float(action.cooldown_s)),
        )
        self.actions[action.id] = action
        if consumed_charge:
            remaining=self.actor.consume_source_cast_charge(charge_bank,at_time_s=start)
            self.queue.push(CombatEvent(time_s=start,kind='CastChargeConsumed',
                actor_id=self.actor.id,target_id=self.actor.id,action_id=action.id,
                payload={'bank_id':charge_bank,'charges_after':remaining,
                    'cast_time_saved_s':float(action.cast_time_s)-effective_cast_s}))
        # Both a self-granted next-cast buff and its consumption are committed
        # only after eligibility, actor-busy gate and resource spend succeed.
        grant=action.metadata.get('source_next_cast_instant_grant')
        if grant:
            school=str(grant.get('school','')).lower()
            count=grant.get('count')
            if (not school or type(count) is not int or count!=1 or
                    not str(grant.get('source_url','')).startswith('https://')):
                raise ValueError('INVALID_SOURCE_NEXT_INSTANT_GRANT')
            self.actor.source_next_cast_instant_charges[school]=count
            self.queue.push(CombatEvent(time_s=start,kind='NextCastInstantGranted',
                actor_id=self.actor.id,target_id=self.actor.id,action_id=action.id,
                payload={'school':school,'charges':count}))
        elif (effective_cast_s < float(action.cast_time_s)-1e-12 and
                self._source_next_instant_school(action) and
                self.actor.source_next_cast_instant_charges.get(
                    self._source_next_instant_school(action),0)>0):
            school=self._source_next_instant_school(action)
            self.actor.source_next_cast_instant_charges[school]-=1
            self.queue.push(CombatEvent(time_s=start,kind='NextCastInstantConsumed',
                actor_id=self.actor.id,target_id=self.actor.id,action_id=action.id,
                payload={'school':school,'charges_after':
                    self.actor.source_next_cast_instant_charges[school],
                    'saved_cast_s':float(action.cast_time_s)}))
        if effective_cast_s > 1e-12:
            self.actor_cast_busy_until[self.actor.id] = start + effective_cast_s
        if should_spatially_tag:
            self.engage_target(self.target.id)
        self.queue.push(CombatEvent(
            time_s=start, kind="ActionStarted", actor_id=self.actor.id,
            target_id=self.target.id, action_id=action.id,
            payload={
                "cast_time_s": effective_cast_s,
                "source_timed_crit_haste_cast_fraction":haste_cast,
                "source_timed_crit_haste_gcd_fraction":haste_gcd,
                "declared_costs": [x.as_dict() for x in action.costs],
                "costs_applied": True,
                "resource_spend": spent,
                "gcd_ready_s": float(self.actor.gcd_ready_s),
                "cooldown_ready_s": float(self.actor.cooldown_ready_s[action.id]),
                "summon_generation": (self.summon_generation[next(
                    k for k, definition in self.timed_summons.items()
                    if definition.summoned_actor_id == self.actor.id)]
                    if self.actor.id in self.summon_actor_ids else None),
            },
        ))
        return start + effective_cast_s

    def _advance_actor_clock(self, time_s: float) -> None:
        """Advance every actor in lockstep; regeneration remains actor-owned."""
        target = float(time_s)
        for actor in self.actors.values():
            current = float(actor.current_time_s)
            if target + 1e-12 < current:
                raise ValueError("cannot move runtime backwards")
            changes = actor.regenerate_for(target - current) if self.actor_active[actor.id] else ()
            if self.enable_casting_regen and self.actor_active[actor.id]:
                fraction=float(actor.stats.get('casting_mana_regen_fraction',0.0))
                if not 0.0 <= fraction <= 1.0:
                    raise ValueError('invalid sourced casting mana regeneration fraction')
                cast_until=float(self.actor_cast_busy_until.get(actor.id,current))
                cast_elapsed=max(0.0,min(target,cast_until)-current)
                if fraction and cast_elapsed and actor.resource_is_active('mana'):
                    from src.game.recovery import forever_classic_mana_regen_per_s
                    rate=forever_classic_mana_regen_per_s(actor)*fraction
                    before,after,gained=actor.restore('mana',rate*cast_elapsed)
                    if gained > 1e-12:
                        self.trace.append(CombatEvent(time_s=target,kind='ResourceRegenerated',
                            actor_id=actor.id,target_id=actor.id,payload={
                            'resource_id':'mana','before':before,'after':after,'gained':gained,
                            'elapsed_s':cast_elapsed,'regeneration_per_s':rate,
                            'source':'casting_mana_regeneration_talent'}))
            actor.current_time_s = max(current, target)
            for row in changes:
                self.trace.append(CombatEvent(
                    time_s=target, kind="ResourceRegenerated", actor_id=actor.id, target_id=actor.id,
                    payload=dict(row),
                ))

    def _scheduled_encounter_terminal(self) -> bool:
        incoming = getattr(self, "scheduled_incoming_attacks", {})
        return bool(incoming) and (
            (all(not t.alive for t in self.targets.values()) if self.multi_target else not self.target.alive) or any(
                not self.actors[str(attack.target_actor_id)].resource_positive(str(attack.health_resource_id))
                for attack in incoming.values()
            )
        )

    def advance_to(self, time_s: float) -> None:
        limit = float(time_s)
        if any(limit + 1e-12 < float(actor.current_time_s) for actor in self.actors.values()):
            raise ValueError("cannot move runtime backwards")
        while self.queue and self.queue.peek_time() <= limit + 1e-12:
            # Finish same-timestamp death/trigger events, never advance the
            # post-combat actor clock into a future pending enemy swing/aura.
            if self._scheduled_encounter_terminal() and self.queue.peek_time() > self.actor.current_time_s + 1e-12:
                return
            if (self.event_budget_cap is not None and
                    self.event_transitions - self.event_budget_start >= self.event_budget_cap):
                raise EventTransitionBudgetExceeded(self.event_transitions - self.event_budget_start)
            if self.cpu_deadline_ns is not None:
                from time import process_time_ns
                if process_time_ns() >= self.cpu_deadline_ns:
                    raise ComputeDeadlineExceeded(self.event_transitions - self.event_budget_start, 'CPU')
            if self.wall_deadline_ns is not None:
                from time import monotonic_ns
                if monotonic_ns() >= self.wall_deadline_ns:
                    raise ComputeDeadlineExceeded(self.event_transitions - self.event_budget_start, 'WALL')
            event = self.queue.pop()
            self.event_transitions += 1
            self._advance_actor_clock(float(event.time_s))
            self.last_event_time_s = max(self.last_event_time_s, float(event.time_s))
            previous_target = self.target
            if self.multi_target and event.target_id in self.targets:
                self.target = self.targets[event.target_id]
            try:
                with self._actor_context(str(event.actor_id)):
                    self._handle(event)
            finally:
                self.target = previous_target
                if self.multi_target and not self.target.alive:
                    next_target = next((t for t in self.targets.values() if t.alive), self.target)
                    if next_target.id != self.target.id:
                        self.target = next_target
                        self._restart_auto_swings(float(self.actor.current_time_s))
        if not self._scheduled_encounter_terminal():
            self._advance_actor_clock(limit)

    def persist_actor_periodics(self) -> tuple[CombatEvent, ...]:
        """Transfer still-live actor aura events into the shared ActorState.

        Call at an encounter/recovery boundary, after advancing the clock to
        the desired boundary. This is a MOVE: the old queue is no longer the
        authority for these events. No enemy effects or ordinary swings cross.
        """
        now = float(self.actors[self.primary_actor_id].current_time_s)
        selected = []
        for _, _, event in sorted(self.queue._heap):
            if event.kind not in ('PeriodicTick', 'AuraExpired') or event.payload.get('aura_scope') != 'actor':
                continue
            if event.actor_id != self.primary_actor_id:
                continue
            aura = self.actors[self.primary_actor_id].active_auras.get(str(event.payload.get('aura_id')))
            if aura is None or int(event.payload.get('generation', -1)) != aura.generation:
                continue  # stale event from a replaced aura
            if float(event.time_s) <= now + 1e-9:
                raise ValueError('actor periodic event not processed at boundary')
            # Snapshot source power at transfer, not the new encounter's gear.
            # A second transfer retains the original snapshot.
            payload = dict(event.payload)
            payload.setdefault('carried_spell_power', float(self.actor_spell_power[event.actor_id]))
            selected.append(CombatEvent(
                time_s=event.time_s, kind=event.kind, actor_id=event.actor_id,
                target_id=event.target_id, action_id=event.action_id, payload=payload,
            ))
        source = {str(e.action_id): self.actions[str(e.action_id)] for e in selected}
        self.actor.pending_actor_periodic_events = tuple(selected)
        self.actor.pending_actor_periodic_actions = source
        self.queue.discard_where(lambda event: event.kind in ('PeriodicTick', 'AuraExpired')
            and event.payload.get('aura_scope') == 'actor'
            and event.actor_id == self.primary_actor_id)
        return tuple(selected)

    def run_until_idle(self, *, preserve_actor_periodics: bool = False) -> None:
        while self.queue:
            if self._scheduled_encounter_terminal() or (preserve_actor_periodics and all(not t.alive for t in self.targets.values())):
                self.persist_actor_periodics()
                now = float(self.actors[self.primary_actor_id].current_time_s)
                self.queue.discard_where(lambda event: float(event.time_s) > now + 1e-12)
                if not self.queue:
                    break
            self.advance_to(self.queue.peek_time())

    def _source_outgoing_hit_components(self, base_hit: float, action_id: str | None,
                                        *, weapon_hit: bool) -> tuple[float, float, float]:
        """Common sourced expected-hit adjustment for damage and debuffs."""
        action=self.actions.get(str(action_id)) if action_id is not None else None
        action_bonus=float(action.metadata.get('outgoing_hit_bonus',0.0)) if action else 0.0
        if not 0.0 <= action_bonus <= 1.0:
            raise ValueError('invalid sourced action hit bonus')
        channel='melee_hit_bonus' if weapon_hit else 'spell_hit_bonus'
        actor_bonus=max(0.0,float(self.actor.stats.get(channel,0.0)))
        return action_bonus,actor_bonus,min(1.0,base_hit+action_bonus+actor_bonus)

    def _effect(self, event: CombatEvent) -> DamageEffect | WeaponDamageEffect | PeriodicEffect | PeriodicResourceEffect | ResourceScaledPeriodicEffect | ResourceScaledDirectDamageEffect | ResourceChangeEffect | HealEffect | PeriodicHealEffect | ModeChangeEffect:
        source = self.actions.get(str(event.action_id)) or self.triggers.get(str(event.action_id))
        if source is None:
            raise ValueError('UNKNOWN_RUNTIME_EFFECT_SOURCE:'+str(event.action_id))
        index = int(event.payload["effect_index"])
        return source.effects[index]

    def _handle(self, event: CombatEvent) -> None:
        if event.kind == 'SpatialChargeArrival':
            effect=self._effect(event)
            if not isinstance(effect,SpatialChargeEffect) or not self.multi_target or not self.target.alive:
                raise ValueError('INVALID_SPATIAL_CHARGE_ARRIVAL')
            tx,ty=self._enemy_position_at(self.target.id,float(event.time_s))
            px,py=self.player_position_yards
            dx,dy=tx-px,ty-py
            distance=hypot(dx,dy)
            offset=float(effect.arrival_distance_yards)
            # The source permits zero minimum range for contact charges. When
            # the actor already overlaps the target, there is no direction to
            # normalize and no distance to close: retain the real position.
            # A behind-target charge still requires a defined approach vector;
            # never fabricate an orientation from an arbitrary world axis.
            if distance<=1e-12:
                if effect.arrival_position_kind!='target_contact':
                    raise ValueError('SOURCE_SPATIAL_CHARGE_ZERO_VECTOR')
                new_pos=(px,py)
            else:
                # A behind-position arrival is a geometric proxy: actual target
                # facing/turning dynamics are not source-certified by this model.
                sign=(-1. if effect.arrival_position_kind=='behind_target' else 1.)
                new_pos=(tx - sign*dx/distance*offset,ty - sign*dy/distance*offset)
            self._player_move_generation+=1
            self._player_route_end_s=float(event.time_s)
            self.player_position_yards=new_pos
            self.target.metadata['attacker_relative_position']=('behind' if
                effect.arrival_position_kind=='behind_target' else 'front')
            self._engaged_targets.add(self.target.id)
            self._enemy_motion.pop(self.target.id,None)
            self._approaching_targets.discard(self.target.id)
            self._enemy_motion_generation[self.target.id]=self._enemy_motion_generation.get(self.target.id,0)+1
            self._melee_targets.add(self.target.id)
            self._sync_auto_attacks(float(event.time_s))
            event.payload.update({'player_position_yards':new_pos,
                'relative_position':self.target.metadata['attacker_relative_position'],
                'distance_before_yards':distance})
            self.trace.append(event)
            return
        if event.kind == 'SpatialPlayerMoveStep':
            if int(event.payload['move_generation']) != self._player_move_generation:
                return  # interrupted path, no teleport from superseded route
            self.player_position_yards = tuple(float(x) for x in event.payload['xy'])
            self._proximity_aggro()
            self.trace.append(event)
            return
        if event.kind == 'SpatialEnemyArrived':
            tid = str(event.target_id)
            if (tid in self._engaged_targets and self.targets[tid].alive
                    and int(event.payload.get('motion_generation',-1)) ==
                         self._enemy_motion_generation.get(tid,0)
                    and not self._enemy_is_immobilized(tid,float(event.time_s))):
                self._enemy_arrived(tid)
            return
        if event.kind == "ScheduledIncomingAttack":
            attack = self.scheduled_incoming_attacks[str(event.action_id)]
            # Encounter stops on mob death or player death. Do not apply a
            # post-kill swing while draining already-queued runtime events.
            if (not self.target.alive or not self.actor.resource_positive(str(attack.health_resource_id))
                    or (self.multi_target and self.target.id not in self._melee_targets)):
                return
            self.resolve_incoming_attack(attack, mitigation_rules=self.scheduled_mitigation_rules,
                                         at_time_s=float(event.time_s))
            if not self.actor.resource_positive(str(attack.health_resource_id)):
                self._sync_auto_attacks(float(event.time_s))
            if self.target.alive and self.actor.resource_positive(str(attack.health_resource_id)):
                index = int(event.payload["swing_index"])
                if index >= 4096:
                    raise ValueError(f"incoming swing safety budget exceeded: {attack.id}")
                self.queue.push(CombatEvent(
                    time_s=float(event.time_s) + float(event.payload["cadence_s"]),
                    kind="ScheduledIncomingAttack", actor_id=self.primary_actor_id,
                    target_id=(self.target.id if self.multi_target else self.primary_actor_id), action_id=str(attack.id),
                    payload={"swing_index": index + 1, "cadence_s": float(event.payload["cadence_s"])},
                ))
            return
        if event.kind == "SummonSpawn":
            summon_id = str(event.payload["summon_id"])
            definition = self.timed_summons[summon_id]
            generation = int(event.payload["generation"])
            self.summon_pending.discard(summon_id)
            if generation != self.summon_generation[summon_id]:
                return
            # A fresh summon life starts from its declared initial Actor state;
            # do not inherit stale Focus, cooldowns, auras or prior GCD.
            import copy
            spawned = self.actors[definition.summoned_actor_id]
            spawned.__dict__.update(copy.deepcopy(
                self.summon_initial_actor_states[definition.summoned_actor_id]
            ).__dict__)
            spawned.current_time_s = float(event.time_s)
            self.actor_active[definition.summoned_actor_id] = True
            self.summon_expiry[summon_id] = float(event.time_s) + float(definition.duration_s)
            self.trace.append(event)
            self.queue.push(CombatEvent(time_s=self.summon_expiry[summon_id],
                kind="SummonDespawn", actor_id=definition.summoned_actor_id,
                target_id=definition.owner_actor_id, action_id=summon_id,
                payload={"summon_id": summon_id, "generation": generation,
                         "reason": "duration_expired"}))
            self._sync_auto_attacks(float(event.time_s))
            return
        if event.kind == "SummonDespawn":
            summon_id = str(event.payload["summon_id"])
            definition = self.timed_summons[summon_id]
            if int(event.payload["generation"]) != self.summon_generation[summon_id]:
                return
            self.actor_active[definition.summoned_actor_id] = False
            self.trace.append(event)
            self._sync_auto_attacks(float(event.time_s))
            return
        if (event.actor_id in self.summon_actor_ids and
            event.kind in {"ActionStarted", "ActionCompleted"} and
            event.payload.get("summon_generation") != next(
                self.summon_generation[sid] for sid, d in self.timed_summons.items()
                if d.summoned_actor_id == event.actor_id)):
            self.trace.append(CombatEvent(time_s=event.time_s, kind="SummonEventSkipped",
                actor_id=event.actor_id, target_id=event.target_id, action_id=event.action_id,
                payload={"original_kind": event.kind, "reason": "stale_summon_generation"}))
            return
        if not self.actor_active.get(str(event.actor_id), True) and event.kind != "AutoAttackStopped":
            self.trace.append(CombatEvent(time_s=event.time_s, kind="SummonEventSkipped",
                actor_id=event.actor_id, target_id=event.target_id, action_id=event.action_id,
                payload={"original_kind": event.kind, "reason": "actor_inactive"}))
            return
        # A previously queued completion is stale if incoming damage pushed
        # the cast back. Never emit phantom duplicate ActionCompleted events.
        if event.kind == 'ActionCompleted':
            pending=float(self.actor_cast_busy_until.get(str(event.actor_id),0.))
            if pending > float(event.time_s) + 1e-12:
                self.trace.append(CombatEvent(time_s=event.time_s,kind='ActionCompletionDeferred',
                    actor_id=event.actor_id,target_id=event.target_id,
                    action_id=event.action_id,payload={'new_time_s':pending}))
                self.queue.push(replace(event,time_s=pending))
                return
        self.trace.append(event)
        action = self.actions.get(str(event.action_id)) if event.action_id is not None else None

        if event.kind in ('NextCastInstantGranted','NextCastInstantConsumed','CastChargeConsumed'):
            return
        if event.kind == 'CastChargeGranted':
            spec=dict(event.payload)
            bank=str(spec['bank_id'])
            cap=int(spec['capacity'])
            grant=int(spec['grant_per_cast'])
            duration=float(spec['duration_s'])
            if (not bank or not 0<grant<=cap<=16 or not 0<duration<=120
                    or not str(spec.get('source_url','')).startswith('https://')):
                raise ValueError('INVALID_SOURCE_CAST_CHARGE_GRANT')
            before,after=self.actor.grant_source_cast_charges(bank,amount=grant,
                capacity=cap,duration_s=duration,at_time_s=float(event.time_s))
            event.payload.update({'charges_before':before,'charges_after':after})
            return
        if event.kind == "ActionStarted":
            if action is None:
                raise ValueError("ActionStarted missing registered action")
            # A caster action interrupts an exclusive auto-attack (e.g. Shoot wand).
            # Other auto-attacks are unchanged. Restart occurs only after completion.
            cast_duration=float(event.payload.get('cast_time_s',action.cast_time_s))
            if not isfinite(cast_duration) or cast_duration<0.:
                raise ValueError('INVALID_EFFECTIVE_CAST_TIME')
            self.actor_cast_busy_until[self.actor.id] = float(event.time_s) + cast_duration
            if cast_duration > 0.:
                self._active_cast_action[self.actor.id]=str(action.id)
            else:
                self._active_cast_action.pop(self.actor.id,None)
            self._sync_auto_attacks(float(event.time_s))
            if action.metadata.get('channel'):
                for index, effect in enumerate(action.effects):
                    # Preflight already validated the registry kind and channel envelope.
                    self.queue.push(CombatEvent(time_s=float(event.time_s), kind='AuraApply',
                        actor_id=self.actor.id, target_id=(self.actor.id if str(effect.target) != 'enemy' else self.target.id),
                        action_id=action.id, payload={'effect_index':index, 'aura_id':effect.aura_id,
                        'aura_scope':'actor' if str(effect.target) != 'enemy' else 'target'}))
            self.queue.push(CombatEvent(
                time_s=float(event.time_s) + cast_duration,
                kind="ActionCompleted", actor_id=self.actor.id, target_id=self.target.id,
                action_id=action.id, payload={"effect_count": len(action.effects),
                     "summon_generation": event.payload.get("summon_generation")},
            ))
            return

        if event.kind == "ActionCompleted":
            if action is None:
                raise ValueError("ActionCompleted missing registered action")
            self.actor_cast_busy_until.pop(self.actor.id, None)
            self._active_cast_action.pop(self.actor.id,None)
            self._sync_auto_attacks(float(event.time_s))
            producer=action.metadata.get('source_cast_charge_producer')
            if producer:
                self.queue.push(CombatEvent(time_s=float(event.time_s),
                    kind='CastChargeGranted',actor_id=self.actor.id,target_id=self.actor.id,
                    action_id=action.id,payload=dict(producer)))
            for index, effect in enumerate(action.effects):
                if action.metadata.get('channel'):
                    continue  # ticks were scheduled at channel start
                kind = effect_execution_kind(effect)
                if kind == 'queued_swing':
                    if effect.auto_attack_id in self.pending_queued_swing:
                        raise ValueError('DUPLICATE_QUEUED_SWING')
                    self.pending_queued_swing[effect.auto_attack_id]=(action.id,effect)
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='QueuedSwingArmed',
                        actor_id=self.actor.id,target_id=self.target.id,action_id=action.id,
                        payload={'auto_attack_id':effect.auto_attack_id,
                                 'bonus_damage':effect.bonus_damage}))
                elif kind == "direct_damage":
                    amount = expected_direct_damage(effect, spell_power=self.spell_power)
                    crit = _direct_damage_crit_probability(effect, self.actor.stats)
                    amount *= 1.0 + crit * (max(1.0, float(effect.crit_multiplier)) - 1.0)
                    for victim_id in self._aoe_victims(action, effect):
                        self.queue.push(CombatEvent(
                            time_s=event.time_s, kind="Damage", actor_id=self.actor.id,
                            target_id=victim_id, action_id=action.id,
                            payload={
                                "effect_index": index, "amount": float(amount), "school": effect.school,
                                "resolution": "expected_value", "spell_power": self.spell_power,
                                "periodic": False,
                                # Direct physical damage now exposes the same
                                # expected crit outcome used by weapon hits.
                                "outcome_weights":{'crit':crit,'hit':1.-crit,'miss':0.},
                                "crit_multiplier":float(effect.crit_multiplier),
                                "spell_power_coefficient":float(effect.spell_power_coefficient),
                                "simultaneous_aoe": effect.target=='enemies',
                            },
                        ))
                elif kind == "weapon_damage":
                    resolution = expected_weapon_damage(effect, actor=self.actor)
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="Damage", actor_id=self.actor.id,
                        target_id=self.target.id, action_id=action.id,
                        payload={
                            "effect_index": index, "amount": float(resolution["expected_damage"]),
                            "school": effect.school, "periodic": False, **resolution,
                        },
                    ))
                elif kind == "resource_scaled_direct_damage":
                    snapshot = self.resource_amount(effect.resource_id)
                    if snapshot is None:
                        raise ValueError(f"resource-scaled direct effect missing resource {effect.resource_id!r}")
                    cp = int(max(0, round(float(snapshot))))
                    if (cp not in effect.base_min_by_resource_amount
                            or cp not in effect.base_max_by_resource_amount):
                        raise ValueError(f"resource-scaled direct effect has no {cp} resource value")
                    minimum = float(effect.base_min_by_resource_amount[cp])
                    maximum = float(effect.base_max_by_resource_amount[cp])
                    attack_power = float(self.actor.stats.get(effect.attack_power_stat_id, 0.0))
                    amount = (minimum + maximum) / 2.0 + (
                        attack_power * float(effect.attack_power_coefficient_per_resource) * cp
                    )
                    amount *= 1.0 + max(0.0,min(1.0,float(effect.crit_chance_bonus))) * (
                        max(1.0,float(effect.crit_multiplier))-1.0)
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="Damage", actor_id=self.actor.id,
                        target_id=self.target.id, action_id=action.id,
                        payload={"effect_index": index, "amount": amount, "school": effect.school,
                                 "periodic": False, "resolution": "expected_value_resource_snapshot",
                                 "resource_id": effect.resource_id,
                                 "resource_amount_snapshot": float(snapshot),
                                 "attack_power_coefficient_per_resource": float(effect.attack_power_coefficient_per_resource)},
                    ))
                elif kind == "resource_scaled_periodic_damage":
                    snapshot = self.resource_amount(effect.resource_id)
                    if snapshot is None:
                        raise ValueError(f"resource-scaled periodic effect missing resource {effect.resource_id!r}")
                    amount_key = int(max(0, round(float(snapshot))))
                    if amount_key not in effect.total_base_damage_by_resource_amount:
                        raise ValueError(f"resource-scaled periodic effect has no value for {amount_key} {effect.resource_id}")
                    resolved_total = float(effect.total_base_damage_by_resource_amount[amount_key])
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="AuraApply", actor_id=self.actor.id,
                        target_id=self.target.id, action_id=action.id,
                        payload={
                            "effect_index": index, "aura_id": effect.aura_id, "aura_scope": "target",
                            "resource_amount_snapshot": float(snapshot),
                            "resolved_total_base_damage": resolved_total,
                        },
                    ))
                elif kind == 'spatial_charge':
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='SpatialChargeArrival',
                        actor_id=self.actor.id,target_id=self.target.id,action_id=action.id,
                        payload={'effect_index':index}))
                elif kind == "resource_change":
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="ResourceChange", actor_id=self.actor.id,
                        target_id=(self.target.id if str(effect.target) == "enemy" else self.actor.id),
                        action_id=action.id, payload={
                            "effect_index": index, "resource_id": effect.resource_id,
                            "resource_target": effect.target, "operation": effect.operation,
                            "amount": float(effect.amount),
                        },
                    ))
                elif kind == "direct_heal":
                    healing_power = self.actor.effective_healing_power(self.spell_power)
                    spell_crit=float(self.actor.stats.get('spell_crit_chance',0.))
                    amount = expected_direct_heal(effect, healing_power=healing_power,
                                                   spell_crit_chance=spell_crit)
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="Heal", actor_id=self.actor.id,
                        target_id=self.actor.id, action_id=action.id,
                        payload={
                            "effect_index": index, "resource_id": effect.resource_id,
                            "amount": float(amount), "resolution": "expected_value",
                            "healing_power": healing_power, "periodic": False,
                            "critical_chance":max(0.,min(1.,spell_crit+effect.crit_chance_bonus)),
                            "critical_multiplier":float(effect.crit_multiplier),
                        },
                    ))
                elif kind == 'active_periodic_full_heal':
                    # Generic source-typed heal: the current qualifying periodic
                    # aura supplies ALL healing numbers, not the triggering spell.
                    # Deliberately do not remove the aura (Forever semantics).
                    if not isinstance(effect, ActivePeriodicFullHealEffect):
                        raise ValueError('INVALID_ACTIVE_PERIODIC_HEAL_EFFECT')
                    if (effect.target!='self' or effect.resource_id!='health' or
                            not effect.source_families or
                            not 0. < float(effect.multiplier) <= 10.):
                        raise ValueError('INVALID_ACTIVE_PERIODIC_HEAL_SOURCE')
                    candidates=[]
                    for aura in self.actor.active_auras.values():
                        if aura.expires_at_s<=float(event.time_s)+1e-12:continue
                        source_action=self.actions.get(aura.source_action_id)
                        if source_action is None or source_action.family_key not in effect.source_families:
                            continue
                        for hot in source_action.effects:
                            if not isinstance(hot,PeriodicHealEffect) or hot.aura_id!=aura.id:
                                continue
                            amount=(expected_periodic_tick_heal(hot,
                                healing_power=self.actor.effective_healing_power(self.spell_power))
                                    *_periodic_tick_count(hot)*float(effect.multiplier))
                            candidates.append((amount, source_action.family_key, aura.id))
                    if not candidates:
                        raise ValueError('QUALIFYING_ACTIVE_PERIODIC_HEAL_UNRESOLVED')
                    # With multiple qualifying HoTs, the source does not say
                    # which gets selected. Deterministic largest heal is a
                    # qualified model policy, NEVER silently a certified fact.
                    amount, family, aura_id = max(candidates)
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='Heal',
                        actor_id=self.actor.id,target_id=self.actor.id,action_id=action.id,
                        payload={'effect_index':index,'resource_id':effect.resource_id,
                                 'amount':amount,'resolution':'active_periodic_full_duration',
                                 'source_aura_id':aura_id,'source_family':family,
                                 'qualifying_aura_count':len(candidates),
                                 'periodic':False,'source_hot_preserved':True}))
                elif kind in ("periodic_damage", "periodic_heal", "periodic_resource"):
                    aura_scope = "actor" if isinstance(effect, (PeriodicHealEffect, PeriodicResourceEffect)) and str(getattr(effect, "target", "self")) != "enemy" else "target"
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="AuraApply", actor_id=self.actor.id,
                        target_id=(self.actor.id if aura_scope == "actor" else self.target.id), action_id=action.id,
                        payload={"effect_index": index, "aura_id": effect.aura_id, "aura_scope": aura_scope},
                    ))
                elif kind == "target_stat_debuff":
                    for victim_id in self._aoe_victims(action,effect):
                        self.queue.push(CombatEvent(
                            time_s=event.time_s, kind='TargetStatDebuffApplied',
                            actor_id=self.actor.id, target_id=victim_id, action_id=action.id,
                            payload={'effect_index':index,'aura_id':effect.aura_id}))
                elif kind == "control":
                    for victim_id in self._aoe_victims(action, effect):
                        self.queue.push(CombatEvent(
                            time_s=event.time_s, kind="ControlApplied", actor_id=self.actor.id,
                            target_id=victim_id, action_id=action.id,
                            payload={"control_id": effect.control_id, "duration_s": float(effect.duration_s),
                                     "prevents_enemy_actions": bool(effect.prevents_enemy_actions),
                                     "breaks_on_damage": bool(effect.breaks_on_damage),
                                     "break_chance_on_damage": effect.break_chance_on_damage,
                                     "effect_index": index, "proc_chance": float(effect.proc_chance)},
                        ))
                elif kind == "summon":
                    self.enqueue_summon(effect.summon_id, at_time_s=event.time_s)
                elif kind == 'status_aura':
                    if not isfinite(float(effect.duration_s)) or (float(effect.duration_s) <= 0 and not effect.indefinite):
                        raise ValueError('invalid source status aura duration')
                    if effect.stealth and (effect.target not in ('actor','self') or
                            not 0 < float(effect.movement_speed_multiplier) <= 1):
                        raise ValueError('INVALID_STEALTH_AURA_PROPERTIES')
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='AuraApply',
                        actor_id=self.actor.id,target_id=(self.actor.id if effect.target in ('actor','self') else self.target.id),
                        action_id=action.id,payload={'effect_index':index,'aura_id':effect.aura_id,
                        'aura_scope':'actor' if effect.target in ('actor','self') else 'target'}))
                elif kind == 'event_emit':
                    if effect.clears_target_exclusive_group:
                        for other in tuple(self.target.active_auras.values()):
                            if other.exclusive_group == effect.clears_target_exclusive_group:
                                self.target.remove_aura(other.id)
                                self.target.active_school_power.pop(other.id,None)
                                self.queue.push(CombatEvent(time_s=event.time_s,kind='AuraRemovedExclusive',
                                    actor_id=self.actor.id,target_id=self.target.id,action_id=action.id,
                                    payload={'aura_id':other.id,'exclusive_group':effect.clears_target_exclusive_group}))
                    probability=float(self.target.metadata.get('spell_hit',1.0))
                    self._queue_event_triggers(event_kind=effect.event_kind,
                        time_s=float(event.time_s),source_action_id=action.id,
                        payload={'landed_hit_probability':probability,
                                 'source_action_id':action.id})
                elif kind == "mode_change":
                    self.queue.push(CombatEvent(
                        time_s=event.time_s, kind="ModeChange", actor_id=self.actor.id,
                        target_id=self.actor.id, action_id=action.id,
                        payload={"effect_index": index, "target_mode_id": effect.target_mode_id},
                    ))
                else:
                    raise NotImplementedError(f"unsupported effect type: {type(effect).__name__}")
            return

        if event.kind == 'SchoolPowerDebuffApplied':
            if not self.target.alive:return
            group=str(event.payload['exclusive_group'])
            for old in tuple(self.target.active_auras.values()):
                if old.exclusive_group == group:
                    self.target.remove_aura(old.id)
                    self.target.active_school_power.pop(old.id,None)
            aura_id=str(event.payload['aura_id'])
            _,aura=self.target.apply_aura(aura_id=aura_id,source_action_id=str(event.action_id),
                applied_at_s=float(event.time_s),duration_s=float(event.payload['duration_s']),
                refresh_rule='replace',exclusive_group=group)
            self.target.active_school_power[aura_id]=(str(event.payload['school']),
                float(event.payload['bonus_spell_power']),aura.generation)
            self.queue.push(CombatEvent(time_s=aura.expires_at_s,kind='SchoolPowerDebuffExpired',
                actor_id=self.actor.id,target_id=self.target.id,action_id=event.action_id,
                payload={'aura_id':aura_id,'generation':aura.generation}))
            return
        if event.kind == 'SchoolPowerDebuffExpired':
            aura_id=str(event.payload['aura_id'])
            if self.target.remove_aura(aura_id,int(event.payload['generation'])) is not None:
                self.target.active_school_power.pop(aura_id,None)
            return

        if event.kind == 'TargetStatDebuffApplied':
            effect=self._effect(event)
            if not isinstance(effect,TargetStatDebuffEffect):
                raise ValueError('target stat debuff event referenced non-debuff effect')
            if not self.target.alive:
                event.payload['applied']=False
                return
            if effect.target_stat_id not in self.target.metadata and effect.target_stat_id not in ('hit_chance','melee_attack_power'):
                raise ValueError('target stat debuff requires sourced target stat')
            if not isfinite(float(effect.delta)) or not isfinite(float(effect.duration_s)) or float(effect.duration_s)<=0:
                raise ValueError('invalid target debuff source')
            previous,aura=self.target.apply_aura(aura_id=effect.aura_id,
                source_action_id=str(event.action_id),applied_at_s=float(event.time_s),
                duration_s=float(effect.duration_s),refresh_rule=effect.refresh_rule)
            hit=float(self.target.metadata.get('spell_hit',1.0))
            if not 0<hit<=1: raise ValueError('invalid sourced spell hit for debuff')
            _,_,hit=self._source_outgoing_hit_components(hit,event.action_id,weapon_hit=False)
            self.target.active_stat_modifiers[effect.aura_id]=(effect.target_stat_id,float(effect.delta)*hit,aura.generation)
            event.payload.update({'applied':True,'generation':aura.generation,
                'expected_hit_chance':hit,'effective_delta':float(effect.delta)*hit,
                'replaced_generation':None if previous is None else previous.generation})
            self.queue.push(CombatEvent(time_s=aura.expires_at_s,kind='TargetStatDebuffExpired',
                actor_id=self.actor.id,target_id=self.target.id,action_id=event.action_id,
                payload={'aura_id':effect.aura_id,'generation':aura.generation}))
            return
        if event.kind == 'TargetStatDebuffExpired':
            aura_id=str(event.payload['aura_id']);generation=int(event.payload['generation'])
            removed=self.target.remove_aura(aura_id,generation)
            if removed is not None:
                self.target.active_stat_modifiers.pop(aura_id,None)
            event.payload['expired']=removed is not None
            return

        if event.kind == "ControlApplied":
            # Stable event-keyed Bernoulli sampling for sourced control procs.
            # No process-global RNG or class/spell branch; replay is exact.
            chance=float(event.payload.get('proc_chance',1.0))
            if not 0. <= chance <= 1.:
                raise ValueError('INVALID_SOURCE_CONTROL_PROC_CHANCE')
            if chance in (0.,1.):
                roll=None
                triggered=(chance==1.)
            else:
                key=(f'{event.actor_id}|{event.action_id}|{event.target_id}|'
                     f'{float(event.time_s):.9f}|{event.payload.get("effect_index",-1)}')
                roll=int.from_bytes(sha256(key.encode('utf-8')).digest()[:8],'big') / 2**64
                triggered=roll < chance
            event.payload.update({'proc_chance':chance,'proc_roll':roll,
                                  'proc_triggered':triggered})
            if not triggered:
                event.payload['applied']=False
                return
            if not self.target.alive:
                event.payload['applied'] = False
                return
            event.payload['applied'] = True
            cid = str(event.payload["control_id"])
            cap_spec=(action.metadata.get('source_control_target_caps') or {}).get(cid) if action else None
            if cap_spec is not None:
                self._enforce_source_control_target_cap(event,action,cid,cap_spec)
            expiry = float(event.time_s) + float(event.payload["duration_s"])
            self.target.active_controls[cid] = max(expiry, self.target.active_controls.get(cid, 0.0))
            break_chance=event.payload.get('break_chance_on_damage')
            if break_chance is not None and (type(break_chance) not in (float,int)
                    or not isfinite(float(break_chance)) or not 0.<=break_chance<=1.):
                raise ValueError('INVALID_SOURCE_CONTROL_DAMAGE_BREAK_CHANCE')
            self._control_behaviors[(self.target.id, cid)] = {
                'prevents_enemy_actions': bool(event.payload.get('prevents_enemy_actions', False)),
                'breaks_on_damage': bool(event.payload.get('breaks_on_damage', False)),
                'break_chance_on_damage': (None if break_chance is None else float(break_chance)),
            }
            if self.multi_target and (cid == 'root' or event.payload.get('prevents_enemy_actions')):
                self._freeze_enemy_approach(self.target.id)
            self.queue.push(CombatEvent(
                time_s=expiry, kind="ControlExpired", actor_id=self.actor.id,
                target_id=self.target.id, action_id=event.action_id,
                payload={"control_id": cid, "expected_expiry_s": expiry},
            ))
            return
        if event.kind == 'ControlTargetCapEvicted':
            return
        if event.kind == "ControlExpired":
            cid = str(event.payload["control_id"])
            if self.target.active_controls.get(cid, 0.0) <= float(event.time_s) + 1e-9:
                self.target.active_controls.pop(cid, None)
                self._source_control_owners.pop((self.target.id,cid),None)
                behavior=self._control_behaviors.pop((self.target.id, cid), None) or {}
                if cid == 'root' or behavior.get('prevents_enemy_actions'):
                    self._begin_enemy_approach(self.target.id)
            return

        if event.kind == "ResourceChange":
            effect = self._effect(event)
            if not isinstance(effect, ResourceChangeEffect):
                raise ValueError("ResourceChange referenced non-resource effect")
            before, after = self._change_resource(effect.resource_id, operation=effect.operation, amount=effect.amount)
            event.payload.update({"before": float(before), "after": float(after)})
            self.queue.push(CombatEvent(
                time_s=event.time_s, kind="ResourceChanged", actor_id=self.actor.id,
                target_id=event.target_id, action_id=event.action_id, payload=dict(event.payload),
            ))
            return

        if event.kind == "ResourceChanged":
            return

        if event.kind == "ResourceEventGain":
            resource_id = str(event.payload.get("resource_id") or "")
            requested = max(0.0, float(event.payload.get("requested_gain", 0.0)))
            recipient = self.targets.get(str(event.target_id), self.target)
            host = _resource_host(self.actor, recipient, resource_id)
            if host is None:raise ValueError('EVENT_RESOURCE_HOST_UNAVAILABLE')
            if host is self.actor:
                before, after, gained = self.actor.restore(resource_id, requested)
            else:
                before, after = host.change_resource(resource_id, operation='add', amount=requested)
                gained = after - before
            event.payload.update({
                "before": float(before), "after": float(after), "gained": float(gained),
                "capped": bool(gained + 1e-12 < requested),
            })
            return

        if event.kind == "ModeChange":
            effect = self._effect(event)
            if not isinstance(effect, ModeChangeEffect):
                raise ValueError("ModeChange referenced non-mode effect")
            transition = self.actor.transition_mode(effect.target_mode_id)
            stealth = self._active_stealth()
            if stealth:
                active_aura = self.actor.active_auras.get(stealth[0])
                source_action = (self.actions.get(active_aura.source_action_id)
                                 if active_aura is not None else None)
                required = (next((str(r.get('value')) for r in source_action.requirements
                                  if r.get('kind') == 'mode_is'), None)
                            if source_action is not None else None)
                if required is not None and required != effect.target_mode_id:
                    self._break_stealth(action_id=event.action_id, reason='form_change')
            if isinstance(event.payload, dict):
                event.payload.update({"transition": transition})
            self.queue.push(CombatEvent(
                time_s=event.time_s, kind="ModeChanged", actor_id=self.actor.id,
                target_id=self.actor.id, action_id=event.action_id,
                payload={**dict(event.payload), **transition},
            ))
            return

        if event.kind == "ModeChanged":
            self._sync_auto_attacks(float(event.time_s))
            return

        if event.kind == "AutoAttackStarted" or event.kind == "AutoAttackStopped":
            return

        if event.kind == "AutoAttackSwing":
            attack_id = str(event.payload.get("auto_attack_id") or event.action_id or "")
            attack = self.auto_attacks.get(attack_id)
            generation = int(event.payload.get("generation", 0))
            if (
                attack is None
                or self.auto_attack_active_generation.get(attack_id) != generation
                or not self._auto_attack_eligible(attack)
            ):
                pending=self.pending_queued_swing.pop(attack_id,None)
                if pending is not None:
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='QueuedSwingCancelled',
                        actor_id=self.actor.id,target_id=self.target.id,action_id=pending[0],
                        payload={'auto_attack_id':attack_id,'reason':'swing_ineligible'}))
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="AutoAttackSwingSkipped", actor_id=self.actor.id,
                    target_id=self.target.id, action_id=attack_id or event.action_id,
                    payload={**dict(event.payload), "reason": "inactive_or_requirements_not_met"},
                ))
                return
            swing_s = self._effective_auto_swing_s(attack)
            resolution = expected_auto_attack_swing(attack, actor=self.actor, swing_time_s=swing_s)
            queued=self.pending_queued_swing.pop(attack_id,None)
            damage_action_id=queued[0] if queued is not None else attack_id
            if queued is not None:
                weights=resolution['outcome_weights']
                effective_bonus=queued[1].bonus_damage * (
                    weights['hit']+weights['crit']*resolution['crit_multiplier'])
                resolution['expected_damage'] += effective_bonus
            outcome_payload = {
                **dict(event.payload), **resolution,
                "school": attack.school, "attack_type": attack.attack_type,
                "auto_attack": queued is None,
                "queued_swing_replacement": queued is not None,
                "queued_action_id": damage_action_id if queued is not None else None,
            }
            self.queue.push(CombatEvent(
                time_s=event.time_s, kind="AutoAttackOutcome", actor_id=self.actor.id,
                target_id=self.target.id, action_id=attack_id, payload=outcome_payload,
            ))
            self.queue.push(CombatEvent(
                time_s=event.time_s, kind="Damage", actor_id=self.actor.id,
                target_id=self.target.id, action_id=damage_action_id,
                payload={
                    **outcome_payload, "amount": float(resolution["expected_damage"]),
                    "periodic": False, "resolution": "expected_value_attack_outcomes",
                },
            ))
            # Emit one source-declared swing event. A seal-like aura may
            # attach a separate school of damage without changing white damage.
            self._queue_event_triggers(event_kind='auto_attack_swing',
                time_s=float(event.time_s), source_action_id=attack_id,
                payload={**outcome_payload, 'swing_time_s':swing_s,
                         'landed_hit_probability':min(1.0,max(0.0,
                             float(attack.hit_chance)*min(1.0,float(self.target.metadata.get('melee_hit',1.0))
                                 + max(0.0,float(self.actor.stats.get('melee_hit_bonus',0.0))))))})
            self.queue.push(CombatEvent(
                time_s=event.time_s, kind="AutoAttackReschedule", actor_id=self.actor.id,
                target_id=self.target.id, action_id=attack_id,
                payload={"auto_attack_id": attack_id, "generation": generation},
            ))
            return

        if event.kind == "AutoAttackOutcome":
            return

        if event.kind == "AutoAttackReschedule":
            attack_id = str(event.payload.get("auto_attack_id") or event.action_id or "")
            attack = self.auto_attacks.get(attack_id)
            generation = int(event.payload.get("generation", 0))
            if (
                attack is not None
                and self.auto_attack_active_generation.get(attack_id) == generation
                and self._auto_attack_eligible(attack)
            ):
                self.queue.push(CombatEvent(
                    time_s=float(event.time_s) + self._effective_auto_swing_s(attack), kind="AutoAttackSwing",
                    actor_id=self.actor.id, target_id=self.target.id, action_id=attack_id,
                    payload={"auto_attack_id": attack_id, "generation": generation},
                ))
            else:
                self._sync_auto_attacks(float(event.time_s))
            return

        if event.kind in ('AutoAttackSwingSkipped', 'QueuedSwingArmed', 'QueuedSwingCancelled', 'ResourceRegenerated', 'AuraRemovedExclusive', 'AbsorbShieldGranted', 'TimedSpellCritHasteGranted'):
            return

        if event.kind == "TriggerFired":
            trigger = self.triggers.get(str(event.payload.get("trigger_id") or event.action_id or ""))
            if trigger is None:
                raise ValueError("TriggerFired missing registered trigger")
            probability = max(0.0, min(1.0, float(event.payload.get("event_probability", 1.0))))
            # The queued trigger can outlive its activation aura when another
            # same-timestamp hit has already spent a one-charge reactive buff.
            consumes = bool(trigger.metadata.get('consume_required_aura_on_trigger',False))
            if consumes:
                aura=self.actor.active_auras.get(str(trigger.required_aura_id or ''))
                if aura is None or aura.expires_at_s <= event.time_s + 1e-12:
                    event.payload['suppressed_spent_charge']=True
                    return
            discrete=any(isinstance(e,(ControlEffect,PeriodicEffect)) for e in trigger.effects)
            if discrete:
                key=(str(trigger.id)+'|'+str(event.time_s)+'|'+
                     str(event.payload.get('source_payload',{}).get('source_enemy_id')))
                roll=int.from_bytes(sha256(key.encode()).digest()[:8],'big')/2**64
                if roll>=probability:
                    event.payload['discrete_proc_triggered']=False
                    return
                event.payload['discrete_proc_triggered']=True
                if consumes:
                    self.actor.remove_aura(str(trigger.required_aura_id))
                    event.payload['consumed_aura_id']=str(trigger.required_aura_id)
            source_id=str(event.payload.get('source_payload',{}).get('source_enemy_id') or '')
            victim_id=(source_id if trigger.metadata.get('target_from_incoming_attacker')
                and source_id in self.targets else self.target.id)
            for index, effect in enumerate(trigger.effects):
                if isinstance(effect,ControlEffect):
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='ControlApplied',
                        actor_id=self.actor.id,target_id=victim_id,action_id=trigger.id,
                        payload={'control_id':effect.control_id,'duration_s':float(effect.duration_s),
                            'prevents_enemy_actions':bool(effect.prevents_enemy_actions),
                            'breaks_on_damage':bool(effect.breaks_on_damage),
                            'break_chance_on_damage':effect.break_chance_on_damage,
                            'proc_chance':1.,'effect_index':index,
                            'source_event_probability':probability}))
                    continue
                if isinstance(effect,PeriodicEffect):
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='AuraApply',
                        actor_id=self.actor.id,target_id=victim_id,action_id=trigger.id,
                        payload={'effect_index':index,'aura_id':effect.aura_id,
                                 'aura_scope':'target','trigger_id':trigger.id}))
                    continue
                if isinstance(effect, DamageEffect):
                    base_amount = expected_direct_damage(effect, spell_power=self.spell_power)
                elif isinstance(effect, WeaponDamageEffect):
                    base_amount = expected_weapon_damage(effect, actor=self.actor)['expected_damage']
                elif isinstance(effect, TargetSchoolPowerEffect):
                    if effect.duration_s <= 0 or effect.bonus_spell_power < 0 or not effect.exclusive_group:
                        raise ValueError('invalid source target school power effect')
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='SchoolPowerDebuffApplied',
                        actor_id=self.actor.id,target_id=self.target.id,action_id=trigger.id,
                        payload={'aura_id':effect.aura_id,'school':effect.school,
                            'bonus_spell_power':float(effect.bonus_spell_power)*probability,
                            'duration_s':effect.duration_s,'exclusive_group':effect.exclusive_group}))
                    continue
                else:
                    raise ValueError('generic Trigger effect must be executable damage or school power')
                amount = base_amount * probability * float(event.payload.get("event_scale",1.0))
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="Damage", actor_id=self.actor.id, target_id=self.target.id,
                    action_id=str(trigger.id), payload={
                        "trigger_id": str(trigger.id), "trigger_effect_index": index,
                        "amount": float(amount), "school": effect.school,
                        "resolution": "expected_value_event_trigger", "spell_power": self.spell_power,
                        "periodic": False, "triggered": True, "event_probability": probability,
                        "spell_power_coefficient":float(getattr(effect,'spell_power_coefficient',0.0)),
                        "self_absorb_fraction":float(getattr(effect,'self_absorb_fraction',0.0)),
                        "self_absorb_requires_stat":getattr(effect,'self_absorb_requires_stat',None),
                        "self_absorb_shield_id":getattr(effect,'self_absorb_shield_id',None),
                    },
                ))
            return

        if event.kind == "AuraApply":
            effect = self._effect(event)
            if not isinstance(effect, (PeriodicEffect, PeriodicHealEffect, PeriodicResourceEffect, ResourceScaledPeriodicEffect, StatusAuraEffect)):
                raise ValueError("AuraApply referenced unsupported aura effect")
            aura_scope = str(event.payload.get("aura_scope") or ("actor" if isinstance(effect, (PeriodicHealEffect, PeriodicResourceEffect)) else "target"))
            if aura_scope == "target" and not self.target.alive:
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="AuraApplySkipped", actor_id=self.actor.id,
                    target_id=self.target.id, action_id=event.action_id,
                    payload={**dict(event.payload), "reason": "target_dead"},
                ))
                return
            host = self.actor if aura_scope == "actor" else self.target
            # Mutually exclusive auras are a generic IR property. The group
            # is declared in source facts, never inferred from spell names.
            if isinstance(effect, StatusAuraEffect) and effect.exclusive_group:
                # Stored aura state survives pull boundaries. Never depend on
                # actions registered in this encounter to find old exclusives.
                for other in tuple(host.active_auras.values()):
                    if other.id != effect.aura_id and other.exclusive_group == effect.exclusive_group:
                        removed = host.remove_aura(other.id)
                        if removed is not None:
                            if aura_scope == 'actor' and self._remove_actor_aura_modifiers(other.id):
                                self._restart_auto_swings(float(event.time_s))
                            self.queue.push(CombatEvent(time_s=event.time_s,
                                kind='AuraRemovedExclusive', actor_id=self.actor.id,
                                target_id=self.actor.id if aura_scope == 'actor' else self.target.id,
                                action_id=event.action_id, payload={
                                    'aura_id': other.id, 'exclusive_group':effect.exclusive_group,
                                    'replaced_by':effect.aura_id, 'removed_generation':removed.generation}))
            if isinstance(effect,StatusAuraEffect) and aura_scope=='actor':
                self._remove_actor_aura_modifiers(effect.aura_id)
            previous, aura = host.apply_aura(
                aura_id=effect.aura_id, source_action_id=str(event.action_id),
                applied_at_s=float(event.time_s),
                duration_s=(float('inf') if isinstance(effect, StatusAuraEffect) and effect.indefinite else float(effect.duration_s)),
                refresh_rule=effect.refresh_rule,
                exclusive_group=(effect.exclusive_group if isinstance(effect, StatusAuraEffect) else None),
            )
            if isinstance(effect,StatusAuraEffect) and aura_scope=='actor':
                deltas=dict(effect.actor_stat_deltas)
                capacities=dict(effect.actor_resource_capacity_deltas)
                if effect.apply_primary_stat_conversions:
                    # One canonical source rule can now affect every matching
                    # timed buff, irrespective of spell, class or equipment.
                    # Compute against the ACTUAL geared/talented ActorState at
                    # cast time, not naked provider stats at IR-build time.
                    from src.game.stat_math import converted_stat_amount
                    for fact in self.actor.metadata.get('canonical_primary_stat_conversions', ()):
                        source_stat=str(fact['source_stat'])
                        if source_stat not in effect.actor_stat_deltas:
                            continue
                        before=float(self.actor.stats.get(source_stat,0.0))
                        change=float(effect.actor_stat_deltas[source_stat])
                        delta=(converted_stat_amount(fact,before+change)
                               -converted_stat_amount(fact,before))
                        if fact['target_type']=='stat':
                            target_stat=str(fact['target_id'])
                            deltas[target_stat]=float(deltas.get(target_stat,0.0))+delta
                        elif fact['target_type']=='resource_capacity':
                            target_resource=str(fact['target_id'])
                            if target_resource not in self.actor.resource_capacity:
                                raise ValueError('SOURCE_AURA_CONVERSION_TARGET_RESOURCE_ABSENT')
                            capacities[target_resource]=float(capacities.get(target_resource,0.0))+delta
                        else:
                            raise ValueError('UNSUPPORTED_SOURCE_AURA_CONVERSION_TARGET')
                for stat,value in deltas.items():
                    if not isfinite(float(value)):
                        raise ValueError('invalid sourced aura stat delta')
                    self.actor.stats[stat]=float(self.actor.stats.get(stat,0.0))+float(value)
                if deltas:self.actor.aura_stat_deltas[effect.aura_id]=deltas
                for resource,value in capacities.items():
                    amount=float(value)
                    if not isfinite(amount) or resource not in self.actor.resource_capacity:
                        raise ValueError('invalid sourced aura capacity delta')
                    before=float(self.actor.resource_capacity[resource])
                    after=before+amount
                    if after <= 0:
                        raise ValueError('invalid sourced aura capacity')
                    if resource in self.actor.resources:
                        self.actor.resources[resource]=float(self.actor.resources[resource])*after/before
                    self.actor.resource_capacity[resource]=after
                if capacities:self.actor.aura_resource_capacity_deltas[effect.aura_id]=capacities
                rate=float(effect.auto_attack_speed_multiplier)
                if not isfinite(rate) or rate<=0:
                    raise ValueError('invalid sourced attack rate')
                if rate!=1.0:
                    self.actor.aura_attack_speed_multipliers[effect.aura_id]=rate
                    self._restart_auto_swings(float(event.time_s))
                if effect.stealth:
                    self.actor.metadata.setdefault('active_stealth_aura_traits', {})[effect.aura_id] = {
                        'movement_speed_multiplier': float(effect.movement_speed_multiplier),
                        'fade_cooldown_s': float(self.actions[event.action_id].metadata.get('stealth_fade_cooldown_s',0.)),
                        'source_action_id': str(event.action_id),
                    }
                    self._sync_auto_attacks(float(event.time_s))
                # Coefficient is a typed source fact. Apply at the actual
                # cast event, never bake a guessed SP value into the action.
                shield=(float(effect.actor_absorb_amount) + self.spell_power *
                        float(effect.actor_absorb_spell_power_coefficient))
                if not isfinite(shield) or shield < 0:
                    raise ValueError('invalid sourced absorb shield capacity')
                if shield > 0:
                    self.actor.absorb_shields[effect.aura_id]=shield
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='AbsorbShieldGranted',
                        actor_id=self.actor.id,target_id=self.actor.id,action_id=event.action_id,
                        payload={'shield_id':effect.aura_id,'amount':shield,
                                 'generation':aura.generation,'replace':True}))
            self.queue.push(CombatEvent(
                time_s=event.time_s,
                kind="AuraReplaced" if previous is not None else "AuraApplied",
                actor_id=self.actor.id, target_id=self.target.id, action_id=event.action_id,
                payload={
                    "effect_index": int(event.payload["effect_index"]),
                    "aura_id": effect.aura_id, "generation": aura.generation,
                    "replaced_generation": None if previous is None else previous.generation,
                    "expires_at_s": aura.expires_at_s, "refresh_rule": effect.refresh_rule,
                    "aura_scope": aura_scope,
                    **({"resolved_total_base_damage": event.payload["resolved_total_base_damage"],
                        "resource_amount_snapshot": event.payload.get("resource_amount_snapshot")}
                       if "resolved_total_base_damage" in event.payload else {}),
                },
            ))
            return

        if event.kind in {"AuraApplied", "AuraReplaced"}:
            effect = self._effect(event)
            if not isinstance(effect, (PeriodicEffect, PeriodicHealEffect, PeriodicResourceEffect, ResourceScaledPeriodicEffect, StatusAuraEffect)):
                raise ValueError(f"{event.kind} referenced unsupported aura effect")
            ticks = 0 if isinstance(effect,StatusAuraEffect) else _periodic_tick_count(effect)
            generation = int(event.payload["generation"])
            for tick_index in range(1, ticks + 1):
                self.queue.push(CombatEvent(
                    time_s=float(event.time_s) + float(effect.tick_interval_s) * tick_index,
                    kind="PeriodicTick", actor_id=self.actor.id, target_id=self.target.id,
                    action_id=event.action_id,
                    payload={
                        "effect_index": int(event.payload["effect_index"]),
                        "aura_id": effect.aura_id, "generation": generation,
                        "tick_index": tick_index, "tick_count": ticks,
                        "aura_scope": event.payload.get("aura_scope", "target"),
                        **({"resolved_total_base_damage": event.payload["resolved_total_base_damage"],
                            "resource_amount_snapshot": event.payload.get("resource_amount_snapshot")}
                           if "resolved_total_base_damage" in event.payload else {}),
                    },
                ))
            if isinstance(effect, StatusAuraEffect) and effect.indefinite:
                return  # Remains until break/cancel; no fictional expiry.
            self.queue.push(CombatEvent(
                time_s=float(event.time_s) + float(effect.duration_s),
                kind="AuraExpired", actor_id=self.actor.id, target_id=self.target.id,
                action_id=event.action_id,
                payload={
                    "effect_index": int(event.payload["effect_index"]),
                    "aura_id": effect.aura_id, "generation": generation,
                    "aura_scope": event.payload.get("aura_scope", "target"),
                },
            ))
            return

        if event.kind == "PeriodicTick":
            aura_id = str(event.payload["aura_id"])
            generation = int(event.payload["generation"])
            effect = self._effect(event)
            aura_scope = str(event.payload.get("aura_scope") or ("actor" if isinstance(effect, (PeriodicHealEffect, PeriodicResourceEffect)) else "target"))
            host = self.actor if aura_scope == "actor" else self.target
            current = host.active_auras.get(aura_id)
            target_invalid = aura_scope == "target" and not self.target.alive
            if target_invalid or current is None or int(current.generation) != generation:
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="PeriodicTickSkipped", actor_id=self.actor.id,
                    target_id=(self.actor.id if aura_scope == "actor" else self.target.id), action_id=event.action_id,
                    payload={**dict(event.payload), "reason": "target_dead_or_aura_replaced"},
                ))
                return
            if isinstance(effect, (PeriodicEffect, ResourceScaledPeriodicEffect)):
                if isinstance(effect, ResourceScaledPeriodicEffect):
                    ticks = _periodic_tick_count(effect)
                    amount = float(event.payload["resolved_total_base_damage"]) / float(ticks)
                else:
                    amount = expected_periodic_tick_damage(effect, spell_power=self.spell_power)
                    tick_crit = float(effect.crit_chance_bonus)
                    if effect.crit_chance_stat_id is not None:
                        tick_crit += float(self.actor.stats.get(effect.crit_chance_stat_id, 0.0))
                    tick_crit = max(0.0, min(1.0, tick_crit))
                    amount *= 1.0 + tick_crit * (max(1.0,float(effect.crit_multiplier))-1.0)
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="Damage", actor_id=self.actor.id,
                    target_id=self.target.id, action_id=event.action_id,
                    payload={
                        "effect_index": int(event.payload["effect_index"]),
                        "amount": float(amount), "school": effect.school,
                        "resolution": "expected_value", "spell_power": self.spell_power,
                        "periodic": True, "aura_id": aura_id, "generation": generation,
                        "spell_power_coefficient":float(getattr(effect,'spell_power_coefficient_per_tick',0.0)),
                        "tick_index": int(event.payload["tick_index"]),
                    },
                ))
            elif isinstance(effect, PeriodicHealEffect):
                healing_power = self.actor.effective_healing_power(float(
                    event.payload.get('carried_spell_power', self.spell_power)))
                amount = expected_periodic_tick_heal(effect, healing_power=healing_power)
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="Heal", actor_id=self.actor.id,
                    target_id=self.actor.id, action_id=event.action_id,
                    payload={
                        "effect_index": int(event.payload["effect_index"]),
                        "resource_id": effect.resource_id, "amount": float(amount),
                        "resolution": "expected_value", "healing_power": healing_power,
                        "periodic": True, "aura_id": aura_id, "generation": generation,
                        "tick_index": int(event.payload["tick_index"]),
                    },
                ))
            elif isinstance(effect, PeriodicResourceEffect):
                if str(effect.operation) != "add":
                    raise ValueError(f"unsupported periodic resource operation: {effect.operation!r}")
                resource_id = str(effect.resource_id)
                requested = self._periodic_resource_gain(effect)
                before, after, gained = self.actor.restore(resource_id, requested)
                event.payload.update({
                    "resource_id": resource_id, "requested_gain": requested,
                    "before": float(before), "after": float(after), "gained": float(gained),
                })
                if (effect.metadata.get('stop_channel_on_full') and
                        str(effect.target) in ('self','actor') and
                        float(after) >= float(self.actor.resource_capacity.get(resource_id,float('inf'))) - 1e-9):
                    # The source channel is interrupted, not shortened in IR.
                    # Its cooldown was committed at start. Invalidate the
                    # remaining aura ticks/completion so recovery cannot pay 8s
                    # after mana actually capped at 4s.
                    self.actor.remove_aura(aura_id, generation)
                    self.actor_cast_busy_until.pop(self.actor.id, None)
                    now = float(event.time_s)
                    self.queue.discard_where(lambda pending:
                        pending.action_id == event.action_id and
                        pending.time_s > now + 1e-10 and
                        pending.kind in ('PeriodicTick','AuraExpired','ActionCompleted'))
                    self.trace.append(CombatEvent(time_s=now,kind='ChannelStopped',
                        actor_id=self.actor.id,target_id=self.actor.id,action_id=event.action_id,
                        payload={'reason':'resource_full','resource_id':resource_id,
                                 'completed_at_s':now}))
                    self._sync_auto_attacks(now)
            else:
                raise ValueError("PeriodicTick referenced non-periodic effect")
            return

        if event.kind == "AuraExpired":
            aura_scope = str(event.payload.get("aura_scope") or "target")
            host = self.actor if aura_scope == "actor" else self.target
            removed = host.remove_aura(
                str(event.payload["aura_id"]), int(event.payload["generation"])
            )
            if removed is not None and aura_scope=='actor':
                if self._remove_actor_aura_modifiers(str(event.payload['aura_id'])):
                    self._restart_auto_swings(float(event.time_s))
            if removed is None:
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="AuraExpirySkipped", actor_id=self.actor.id,
                    target_id=self.target.id, action_id=event.action_id,
                    payload={**dict(event.payload), "reason": "aura_replaced_or_removed"},
                ))
            return

        if event.kind == "Heal":
            resource_id = str(event.payload.get("resource_id") or "health")
            requested = float(event.payload.get("amount", 0.0))
            before, after, restored = self.actor.restore(resource_id, requested)
            event.payload.update({
                "before": float(before), "after": float(after),
                "restored": float(restored), "overheal": max(0.0, requested - restored),
            })
            return

        if event.kind == "Damage":
            # Damage events can already be queued for the same timestamp when an
            # earlier event kills the target.  Keep the trace, but mark those
            # events as unapplied so downstream Evaluation never counts damage
            # that the runtime itself ignored.
            if not self.target.alive:
                if isinstance(event.payload, dict):
                    event.payload.update({"applied": False, "ignored_reason": "target_dead"})
                return
            self._sample_joint_melee_critical(event)
            self._sample_joint_spell_critical(event)
            raw_amount = float(event.payload.get("amount", 0.0))
            damage_multiplier = float(self.actor.stats.get("damage_multiplier", 1.0))
            if damage_multiplier < 0:
                raise ValueError("damage_multiplier must be non-negative")
            amount = raw_amount * damage_multiplier
            coefficient=float(event.payload.get('spell_power_coefficient',0.0))
            school=str(event.payload.get('school','')).lower()
            bonus_power=sum(float(bonus) for s,bonus,_ in self.target.active_school_power.values()
                            if str(s).lower()==school)
            if coefficient>0 and bonus_power>0:
                amount += coefficient*bonus_power*damage_multiplier
                event.payload.update({'target_school_power_bonus':bonus_power,
                                      'target_school_power_applied':coefficient*bonus_power})
            # Generic source-IR conditional damage (e.g. versus a controlled
            # target). An unverified control never activates the multiplier.
            source_action = self.actions.get(str(event.action_id))
            conditional = (source_action.metadata.get('conditional_target_control_damage_multiplier')
                           if source_action else None)
            if conditional:
                cid = str(conditional['control_id'])
                multiplier = float(conditional['multiplier'])
                if not 1.0 <= multiplier <= 100.0:
                    raise ValueError('invalid sourced conditional damage multiplier')
                active = self.target.active_controls.get(cid, 0.0) > float(event.time_s)
                if active:
                    amount *= multiplier
                event.payload.update({'conditional_control_id':cid,
                    'conditional_control_active':bool(active),
                    'conditional_multiplier_applied':multiplier if active else 1.0})
            # Conditional source-ranked melee bonuses (e.g. against an
            # *already bleeding* target). Only source-tagged, active physical
            # periodic auras count, not untyped statuses, expired auras or an
            # aura applied by this same action at the same timestamp. This
            # logic is shared by every class/talent, not a class-specific case.
            if (source_action is not None and not event.payload.get('periodic')
                    and not event.payload.get('auto_attack')):
                for rule in source_action.metadata.get('conditional_target_aura_damage_multipliers',()):
                    category=str(rule['aura_category'])
                    if category != 'bleed':
                        raise ValueError('UNKNOWN_SOURCE_TARGET_AURA_CATEGORY')
                    active = False
                    for aura in self.target.active_auras.values():
                        if (not aura.id.endswith(':bleed') or
                                float(aura.applied_at_s) >= float(event.time_s)-1e-9 or
                                float(aura.expires_at_s) <= float(event.time_s)):
                            continue
                        aura_action=self.actions.get(str(aura.source_action_id))
                        if aura_action and any(
                            isinstance(e,(PeriodicEffect,ResourceScaledPeriodicEffect))
                            and e.target=='enemy' and e.school.lower()=='physical'
                            and e.aura_id==aura.id for e in aura_action.effects):
                            active=True;break
                    factor=float(rule['multiplier'])
                    if not 1.0 < factor <= 2.0:
                        raise ValueError('INVALID_SOURCE_TARGET_AURA_MULTIPLIER')
                    if active:
                        amount*=factor
                    event.payload.setdefault('conditional_aura_damage',[]).append({
                        'category':category,'active':active,
                        'multiplier_applied':factor if active else 1.0,
                        'talent_id':rule.get('talent_id')})
            # Source scenario supplies base hit and target armor. This is an
            # expected-value model: a DoT's application miss scales its full
            # tick stream, rather than independently rerolling each tick.
            # Bleeds bypass Armor; direct physical and auto swings do not.
            if 'combat_capture_id' in self.target.metadata:
                school=str(event.payload.get('school','')).lower()
                physical=school=='physical'
                weapon_hit=(physical or bool(event.payload.get('auto_attack')) or
                            str(event.payload.get('resolution','')).startswith('expected_value_weapon'))
                hit_key='melee_hit' if weapon_hit else 'spell_hit'
                base_hit=float(self.target.metadata[hit_key])
                if not 0<base_hit<=1: raise ValueError('invalid sourced outgoing hit')
                bonus,actor_hit_bonus,effective_hit=self._source_outgoing_hit_components(
                    base_hit,event.action_id,weapon_hit=weapon_hit)
                # Reactive damage (e.g. Thorns) is already conditional on an
                # incoming contact, not another spell hit roll.
                if not event.payload.get('triggered'):
                    amount *= effective_hit
                armor_before=0.0;armor_reduction=0.0
                if physical and not event.payload.get('periodic'):
                    armor_before=self.target.effective_stat('armor')
                    constant=float(self.target.metadata['armor_constant'])
                    cap=float(self.target.metadata['armor_reduction_cap'])
                    if constant<=0 or not 0<cap<=1: raise ValueError('invalid sourced armor mitigation')
                    armor_reduction=min(cap,armor_before/(armor_before+constant))
                    amount *= 1.0-armor_reduction
                # Spell penetration only reduces explicitly modeled *school*
                # resistance. The ordinary target proxy currently has no such
                # source field; that lack of data is recorded, not zero-proof.
                magic_school=school not in ('physical','', 'bleed')
                resistance_key='resistance_'+school
                magic_context='NOT_MAGICAL'
                if magic_school:
                    if resistance_key in self.target.metadata:
                        resistance_before=self.target.effective_stat(resistance_key)
                        spell_pen=max(0.,float(self.actor.stats.get('spell_penetration',0.)))
                        resistance_after=max(0.,resistance_before-spell_pen)
                        magic_reduction=sourced_magic_resistance_reduction(resistance_after,
                            level=int(self.actor.metadata.get('level',0)))
                        amount*=1.-magic_reduction
                        magic_context='EXPLICIT_TARGET_SCHOOL_RESISTANCE'
                        event.payload.update({'target_magic_resistance_before':resistance_before,
                            'spell_penetration':spell_pen,
                            'target_magic_resistance_after':resistance_after,
                            'target_magic_resistance_reduction':magic_reduction})
                    else:
                        magic_context='UNSOURCED_TARGET_SCHOOL_RESISTANCE_NOT_APPLIED'
                event.payload['magic_resistance_context']=magic_context
                event.payload.update({'source_base_hit':base_hit,'source_hit_bonus':bonus,
                    'actor_hit_bonus':actor_hit_bonus,
                    'effective_hit_chance':effective_hit,
                    'target_armor':armor_before,'target_armor_reduction':armor_reduction,
                    'target_combat_capture_id':self.target.metadata['combat_capture_id']})
            if isinstance(event.payload, dict):
                event.payload.update({"applied": True, "raw_amount": raw_amount,
                                      "amount": amount, "actor_damage_multiplier": damage_multiplier})
            remaining_health_before = float(self.target.health)
            self.target.apply_damage(amount)
            if amount > 0.:
                for cid in tuple(self.target.active_controls):
                    behavior=self._control_behaviors.get((self.target.id,cid),{})
                    chance=behavior.get('break_chance_on_damage')
                    if chance is None:
                        chance=1. if behavior.get('breaks_on_damage') else 0.
                    roll,broken=_control_damage_break_roll(
                        target_id=self.target.id,control_id=cid,event=event,
                        ordinal=len(self.trace),chance=float(chance))
                    event.payload.setdefault('control_break_rolls',[]).append({
                        'control_id':cid,'chance':float(chance),'roll':roll,'broken':broken})
                    if broken:
                        self.target.active_controls.pop(cid, None)
                        self._control_behaviors.pop((self.target.id, cid), None)
                        self._source_control_owners.pop((self.target.id,cid),None)
                        if cid == 'root':
                            self._begin_enemy_approach(self.target.id)
                        event.payload.setdefault('control_broken_by_damage', []).append(cid)
            absorb_ratio=float(event.payload.get('self_absorb_fraction',0.0))
            if absorb_ratio:
                stat=event.payload.get('self_absorb_requires_stat')
                if not 0<=absorb_ratio<=1 or not event.payload.get('self_absorb_shield_id'):
                    raise ValueError('invalid source absorb effect')
                if stat is None or float(self.actor.stats.get(str(stat),0.0))>0:
                    shield_id=str(event.payload['self_absorb_shield_id'])
                    grant=min(amount,max(0.0,remaining_health_before))*absorb_ratio
                    self.actor.absorb_shields[shield_id]=grant
                    self.queue.push(CombatEvent(time_s=event.time_s,kind='AbsorbShieldGranted',
                        actor_id=self.actor.id,target_id=self.actor.id,action_id=event.action_id,
                        payload={'shield_id':shield_id,'amount':grant,'replace':True}))
            self.total_damage += amount
            # Generic leech: heal only from damage actually applied, including
            # overkill handling, never from an independently guaranteed HoT.
            source_action = self.actions.get(str(event.action_id))
            leech = (source_action.metadata.get('leech') if source_action else None)
            if leech and bool(event.payload.get('periodic')):
                applied_amount = min(amount, max(0.0, remaining_health_before))
                self.queue.push(CombatEvent(time_s=float(event.time_s), kind='Heal',
                    actor_id=self.actor.id, target_id=self.actor.id, action_id=event.action_id,
                    payload={'resource_id':str(leech.get('resource_id','health')),
                             'amount':applied_amount*float(leech.get('ratio',1.0)),
                             'periodic':True,'source':'leech_from_applied_damage'}))
            if bool(event.payload.get("periodic")):
                self.periodic_damage += amount
            else:
                self.direct_damage += amount
                if bool(event.payload.get("auto_attack")):
                    self.auto_attack_damage += amount
            # Expected critical outcomes are explicit weighted events. Passive
            # source talents consume the landed-crit probability, never grant a
            # guaranteed proc simply because expected damage included crits.
            critical_weight=(event.payload.get('sampled_critical_count')
                if 'sampled_critical_count' in event.payload else
                (event.payload.get('outcome_weights') or {}).get('crit',0.))
            if (not event.payload.get('periodic') and
                    str(event.payload.get('school','')).lower()=='physical' and
                    type(critical_weight) in (int,float) and
                    0 < float(critical_weight) <= 1.):
                generated=self._generated_resource_ids(event.action_id)
                self._queue_resource_event_gains(
                    event_kind='nonperiodic_melee_critical',
                    time_s=float(event.time_s),source_action_id=event.action_id,
                    target_id=str(event.target_id),
                    payload={'expected_critical_count':float(critical_weight),
                             'sampled_critical_count':event.payload.get('sampled_critical_count'),
                             'generated_resource_ids':generated,
                             'school':str(event.payload.get('school')),
                             'damage_action_id':event.action_id})
            # A sourced spell crit haste trigger shares the already-realized
            # direct spell damage outcome. Never roll a second independent proc.
            haste_rule=self.actor.metadata.get('source_timed_spell_crit_haste')
            if (self._is_source_spell_crit_haste_event(event) and
                    event.payload.get('sampled_critical_count') == 1):
                duration=float(haste_rule['duration_s'])
                before=float(self.actor.source_timed_spell_crit_haste_until_s)
                self.actor.source_timed_spell_crit_haste_until_s=float(event.time_s)+duration
                self.queue.push(CombatEvent(time_s=float(event.time_s),
                    kind='TimedSpellCritHasteGranted',actor_id=self.actor.id,
                    target_id=self.actor.id,action_id=event.action_id,
                    payload={'duration_s':duration,'expires_at_s':float(event.time_s)+duration,
                        'before_expires_at_s':before,'crit_probability':float(critical_weight),
                        'sample_roll':event.payload['sampled_hit_crit_roll'],
                        'sampled_critical_count':1,'source':dict(haste_rule['source'])}))
            self._queue_resource_event_gains(
                event_kind="damage_dealt", time_s=float(event.time_s), source_action_id=event.action_id,
                payload=dict(event.payload),
            )
            if not self.target.alive and self.target.id not in self._pack_target_death_times:
                self.queue.push(CombatEvent(
                    time_s=event.time_s, kind="TargetDied", actor_id=self.actor.id,
                    target_id=self.target.id, action_id=event.action_id,
                    payload={"health": 0.0},
                ))
            return

        if event.kind == "TargetDied":
            self._pack_target_death_times[self.target.id] = float(event.time_s)
            if not self.multi_target or all(not t.alive for t in self.targets.values()):
                if self.target_death_s is None:
                    self.target_death_s = float(event.time_s)
            # Stop only this enemy's future swings, not other engaged mobs.
            if self.multi_target:
                dead_id = self.target.id
                self._melee_targets.discard(dead_id)
                self.queue.discard_where(lambda queued: queued.kind == 'ScheduledIncomingAttack'
                    and queued.target_id == dead_id)
            else:
                self.queue.discard_where(lambda queued: queued.kind == "ScheduledIncomingAttack")
            self.target.clear_auras()
            if self.multi_target:
                # Continue the same encounter when a selected mob dies. The
                # target change invalidates pending melee-swing generations;
                # its replacement cannot swing before coming into range.
                next_target = self._next_engaged_target()
                if next_target is not None:
                    self.select_target(next_target)
                else:
                    self._sync_auto_attacks(float(event.time_s))
            else:
                self._sync_auto_attacks(float(event.time_s))
            return

        if event.kind in {"AuraApplySkipped", "PeriodicTickSkipped", "AuraExpirySkipped"}:
            return

        raise ValueError(f"unknown combat event kind: {event.kind}")

    def result(self) -> CombatTimelineResult:
        contributions = {actor_id: 0.0 for actor_id in self.actors}
        for event in self.trace:
            if event.kind == "Damage" and bool(event.payload.get("applied")):
                contributions[str(event.actor_id)] += float(event.payload["amount"])
        by_role = {"player": 0.0, "pet": 0.0, "summon": 0.0}
        for actor_id, amount in contributions.items():
            by_role[self.actor_roles[actor_id]] += amount
        return CombatTimelineResult(
            damage_by_actor=contributions,
            damage_by_role=by_role,
            actor_roles=dict(self.actor_roles),
            start_time_s=self.start_time_s,
            end_time_s=max(float(self.actor.current_time_s), self.last_event_time_s),
            total_damage=float(self.total_damage),
            direct_damage=float(self.direct_damage),
            periodic_damage=float(self.periodic_damage),
            auto_attack_damage=float(self.auto_attack_damage),
            target_start_health=(sum(t.max_health for t in self.targets.values())
                                 if self.multi_target else self.target_start_health),
            target_end_health=(sum(t.health for t in self.targets.values())
                               if self.multi_target else float(self.target.health)),
            target_defeated=(all(not t.alive for t in self.targets.values())
                             if self.multi_target else not self.target.alive),
            target_death_s=self.target_death_s,
            resources_before=dict(self.resources_before),
            resources_after={str(k): float(v) for k, v in self.actor.resources.items()},
            events=tuple(self.trace),
        )


def execute_action_timeline(
    *, scheduled_actions: Sequence[tuple[float, ActionDefinition]], actor: ActorState,
    target: TargetState, spell_power: float = 0.0,
) -> CombatTimelineResult:
    """Execute a caller-chosen Action timeline through one persistent queue.

    The schedule is a mechanics probe, not policy search. Readiness/resource
    eligibility is still enforced by the same generic runtime for every Action.
    """
    runtime = CombatRuntime(actor=actor, target=target, spell_power=spell_power)
    for at_time_s, action in scheduled_actions:
        runtime.schedule_action(action, at_time_s=float(at_time_s))
    runtime.run_until_idle()
    return runtime.result()


def execute_action(
    *, action: ActionDefinition, actor: ActorState, target: TargetState,
    spell_power: float = 0.0, allow_source_partial_l1: bool = False,
) -> ActionExecutionResult:
    """Execute one Action through the persistent generic runtime."""
    start_time = float(actor.current_time_s)
    resources_before = {str(k): float(v) for k, v in actor.resources.items()}
    runtime = CombatRuntime(actor=actor, target=target, spell_power=spell_power,
                            allow_source_partial_l1=allow_source_partial_l1)
    runtime.schedule_action(action)
    runtime.run_until_idle()
    timeline = runtime.result()
    return ActionExecutionResult(
        action_id=action.id,
        start_time_s=start_time,
        end_time_s=timeline.end_time_s,
        elapsed_s=timeline.end_time_s - start_time,
        total_damage=timeline.total_damage,
        target_start_health=timeline.target_start_health,
        target_end_health=timeline.target_end_health,
        target_defeated=timeline.target_defeated,
        target_death_s=timeline.target_death_s,
        resources_before=resources_before,
        resources_after=timeline.resources_after,
        gcd_ready_s=float(actor.gcd_ready_s),
        cooldown_ready_s=float(actor.cooldown_ready_s[action.id]),
        events=timeline.events,
        damage_resolution="expected_value",
    )


def execute_repeated_actions(
    *, action: ActionDefinition, actor: ActorState, target: TargetState, count: int,
    spell_power: float = 0.0, wait_for_readiness: bool = True,
    stop_on_ineligible: bool = True,
) -> ActionSequenceResult:
    """Execute repeated uses of one caller-selected Action.

    This remains state progression rather than policy search. Periodic cross-cast
    overlap/refresh scenarios should use ``execute_action_timeline`` so one event
    queue persists across casts.
    """
    requested = max(0, int(count))
    start_time = float(actor.current_time_s)
    resources_before = {str(k): float(v) for k, v in actor.resources.items()}
    executions: list[ActionExecutionResult] = []
    stopped_reason: str | None = None

    for _ in range(requested):
        if not target.alive:
            stopped_reason = "target is dead"
            break
        eligibility = action_eligibility(action=action, actor=actor)
        if not eligibility.eligible and wait_for_readiness and eligibility.reason == "action not ready: gcd/cooldown":
            actor.current_time_s = max(float(actor.current_time_s), float(eligibility.next_ready_s))
            eligibility = action_eligibility(action=action, actor=actor)
        if not eligibility.eligible:
            stopped_reason = eligibility.reason
            if stop_on_ineligible:
                break
            raise ActionNotEligibleError(eligibility)
        executions.append(execute_action(action=action, actor=actor, target=target, spell_power=spell_power))

    return ActionSequenceResult(
        action_id=action.id, requested_casts=requested, completed_casts=len(executions),
        start_time_s=start_time, end_time_s=float(actor.current_time_s),
        resources_before=resources_before,
        resources_after={str(k): float(v) for k, v in actor.resources.items()},
        executions=tuple(executions), stopped_reason=stopped_reason,
    )

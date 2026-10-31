from __future__ import annotations

"""Backend-neutral executable Game IR.

G04 introduced the minimum reusable vocabulary needed for one real direct-cast
spell. G05 adds reusable actor/resource starting-state authority so a runtime can
construct the supported actor entirely from normalized game data rather than
class scorer constants.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


GAME_IR_SCHEMA_VERSION = 17


@dataclass(frozen=True)
class ActorDefinition:
    id: str
    actor_type: str
    base_stats: Mapping[str, float] = field(default_factory=dict)
    state_status: str = "definition_only"
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "actor_type": self.actor_type,
            "base_stats": {str(k): float(v) for k, v in dict(self.base_stats).items()},
            "state_status": self.state_status,
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActorLinkModifier:
    """Ruleset-neutral stat transfer from one actor to another at encounter spawn.

    Source snapshot avoids evaluation-order effects between linked actors.
    ``requires_actor_id`` permits companion-dependent owner bonuses.
    """
    id: str
    source_actor_id: str
    target_actor_id: str
    source_stat_ids: tuple[str, ...]
    target_stat_id: str
    coefficient: float
    operation: str = "add_scaled"
    requires_actor_id: str | None = None
    provenance: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": "actor_link_modifier", "source_actor_id": self.source_actor_id,
            "target_actor_id": self.target_actor_id, "source_stat_ids": list(self.source_stat_ids),
            "target_stat_id": self.target_stat_id, "coefficient": float(self.coefficient),
            "operation": self.operation, "requires_actor_id": self.requires_actor_id,
            "provenance": [dict(x) for x in self.provenance],
        }


@dataclass(frozen=True)
class TimedSummonDefinition:
    """Reusable Actor lifecycle; the compiler supplies the timer and source.

    The summoned actor is predeclared as an encounter companion but remains
    inactive until its spawn event. No combat stats are inferred here.
    """
    id: str
    owner_actor_id: str
    summoned_actor_id: str
    duration_s: float
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id), "kind": "timed_summon",
            "owner_actor_id": str(self.owner_actor_id),
            "summoned_actor_id": str(self.summoned_actor_id),
            "duration_s": float(self.duration_s),
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResourceEventGainRule:
    """Generic event-driven Resource gain rule.

    ``event_kind`` is runtime vocabulary (for example ``damage_dealt`` or
    ``damage_taken``). The gain is ``flat_amount + event_value * multiplier``
    and normal Resource capacity semantics clamp the result. Optional mode and
    payload filters keep the rule data-driven instead of adding class branches.
    """
    id: str
    event_kind: str
    event_value_field: str = "amount"
    multiplier: float = 0.0
    flat_amount: float = 0.0
    required_mode_id: str | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "event_kind": str(self.event_kind),
            "event_value_field": str(self.event_value_field),
            "multiplier": float(self.multiplier),
            "flat_amount": float(self.flat_amount),
            "required_mode_id": self.required_mode_id,
            "filters": dict(self.filters),
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ArmorMitigationDefinition:
    """Reusable expected-value physical mitigation rule.

    The source/compiler owns the curve constant and provenance; runtime only
    executes ``armor / (armor + constant)`` with an explicit cap. This keeps
    ruleset/class facts out of combat code while allowing the same primitive
    to serve Bear, Warrior, Paladin and ordinary incoming physical attacks.
    """
    id: str
    school: str
    armor_stat_id: str
    armor_constant: float
    reduction_cap: float = 0.75
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id), "kind": "armor_mitigation", "school": str(self.school),
            "armor_stat_id": str(self.armor_stat_id), "armor_constant": float(self.armor_constant),
            "reduction_cap": float(self.reduction_cap),
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class IncomingEventProjection:
    """Project one resolved incoming-attack value into a generic combat event."""
    id: str
    event_kind: str
    source_value_field: str
    event_value_field: str = "amount"
    multiplier: float = 1.0
    flat_amount: float = 0.0
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id), "event_kind": str(self.event_kind),
            "source_value_field": str(self.source_value_field),
            "event_value_field": str(self.event_value_field),
            "multiplier": float(self.multiplier), "flat_amount": float(self.flat_amount),
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class IncomingAttackDefinition:
    """One expected incoming attack resolved against the player Actor.

    Scheduling/multi-Actor enemy AI is intentionally outside G28. This record
    owns reusable attack outcome + mitigation inputs and event projections.
    """
    id: str
    name: str
    source_actor_id: str
    target_actor_id: str
    school: str
    raw_damage: float
    hit_chance: float
    health_resource_id: str
    mitigation_rule_id: str | None = None
    event_projections: tuple[IncomingEventProjection, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id), "kind": "incoming_attack", "name": str(self.name),
            "source_actor_id": str(self.source_actor_id), "target_actor_id": str(self.target_actor_id),
            "school": str(self.school), "raw_damage": float(self.raw_damage),
            "hit_chance": float(self.hit_chance), "health_resource_id": str(self.health_resource_id),
            "mitigation_rule_id": self.mitigation_rule_id,
            "event_projections": [x.as_dict() for x in self.event_projections],
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResourceDefinition:
    id: str
    name: str
    owner_actor_id: str
    scope: str = "actor"
    state_status: str = "definition_only"
    initial_amount: float | None = None
    capacity: float | None = None
    active_by_default: bool = True
    regeneration_per_s: float = 0.0
    event_gain_rules: tuple[ResourceEventGainRule, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner_actor_id": self.owner_actor_id,
            "scope": self.scope,
            "state_status": self.state_status,
            "initial_amount": None if self.initial_amount is None else float(self.initial_amount),
            "capacity": None if self.capacity is None else float(self.capacity),
            "active_by_default": bool(self.active_by_default),
            "regeneration_per_s": float(self.regeneration_per_s),
            "event_gain_rules": [x.as_dict() for x in self.event_gain_rules],
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResourceCost:
    resource_id: str
    amount: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceChangeEffect:
    """Generic resource mutation on the actor or current target."""
    effect_type: str
    resource_id: str
    target: str
    operation: str
    amount: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": str(self.effect_type),
            "resource_id": str(self.resource_id),
            "target": str(self.target),
            "operation": str(self.operation),
            "amount": float(self.amount),
        }


@dataclass(frozen=True)
class SummonEffect:
    """Spawn a predeclared timed Actor as an ordinary action effect."""
    effect_type: str
    summon_id: str

    def as_dict(self) -> dict[str, Any]:
        return {"effect_type": self.effect_type, "summon_id": self.summon_id}


@dataclass(frozen=True)
class PeriodicResourceEffect:
    """Generic actor/target Resource gain or loss over an Aura lifetime."""
    effect_type: str
    resource_id: str
    target: str
    aura_id: str
    amount_per_tick: float
    duration_s: float
    tick_interval_s: float
    operation: str = "add"
    refresh_rule: str = "replace"
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": str(self.effect_type), "resource_id": str(self.resource_id),
            "target": str(self.target), "aura_id": str(self.aura_id),
            "amount_per_tick": float(self.amount_per_tick), "duration_s": float(self.duration_s),
            "tick_interval_s": float(self.tick_interval_s), "operation": str(self.operation),
            "refresh_rule": str(self.refresh_rule),
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResourceScaledPeriodicEffect:
    """Periodic damage whose source-backed total is selected from a resource snapshot.

    This is the reusable combo-point finisher shape used by Druid Rip and later
    Rogue Rupture: the resource itself remains a normal target-bound Resource.
    """
    effect_type: str
    school: str
    target: str
    aura_id: str
    resource_id: str
    resource_scope: str
    total_base_damage_by_resource_amount: Mapping[int, float]
    duration_s: float
    tick_interval_s: float
    refresh_rule: str = "replace"
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": str(self.effect_type), "school": str(self.school), "target": str(self.target),
            "aura_id": str(self.aura_id), "resource_id": str(self.resource_id),
            "resource_scope": str(self.resource_scope),
            "total_base_damage_by_resource_amount": {str(int(k)): float(v) for k, v in self.total_base_damage_by_resource_amount.items()},
            "duration_s": float(self.duration_s), "tick_interval_s": float(self.tick_interval_s),
            "refresh_rule": str(self.refresh_rule),
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class ResourceScaledDirectDamageEffect:
    """One immediate direct hit selected by a target/actor Resource snapshot.

    A generic counterpart to ResourceScaledPeriodicEffect for combo-point
    finishers: snapshot before any following ResourceChangeEffect consumes CP.
    No Rogue-specific attack logic lives in the event runtime.
    """
    effect_type: str
    school: str
    target: str
    resource_id: str
    resource_scope: str
    base_min_by_resource_amount: Mapping[int, float]
    base_max_by_resource_amount: Mapping[int, float]
    attack_power_coefficient_per_resource: float = 0.0
    attack_power_stat_id: str = "attack_power"
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()
    crit_chance_bonus: float = 0.0
    crit_multiplier: float = 2.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": self.effect_type, "school": self.school, "target": self.target,
            "resource_id": self.resource_id, "resource_scope": self.resource_scope,
            "base_min_by_resource_amount": {str(k): float(v) for k, v in self.base_min_by_resource_amount.items()},
            "base_max_by_resource_amount": {str(k): float(v) for k, v in self.base_max_by_resource_amount.items()},
            "attack_power_coefficient_per_resource": float(self.attack_power_coefficient_per_resource),
            "attack_power_stat_id": self.attack_power_stat_id,
            "crit_chance_bonus": float(self.crit_chance_bonus), "crit_multiplier": float(self.crit_multiplier),
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class DamageEffect:
    effect_type: str
    school: str
    target: str
    base_min: float
    base_max: float
    spell_power_coefficient: float = 0.0
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()
    crit_chance_stat_id: str | None = None
    crit_multiplier: float = 2.0
    crit_chance_bonus: float = 0.0
    self_absorb_fraction: float = 0.0
    self_absorb_requires_stat: str | None = None
    self_absorb_shield_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": self.effect_type,
            "school": self.school,
            "target": self.target,
            "base_min": float(self.base_min),
            "base_max": float(self.base_max),
            "spell_power_coefficient": float(self.spell_power_coefficient),
            "crit_chance_stat_id": self.crit_chance_stat_id, "crit_multiplier": float(self.crit_multiplier),
            "crit_chance_bonus": float(self.crit_chance_bonus),
            "self_absorb_fraction": float(self.self_absorb_fraction),
            "self_absorb_requires_stat": self.self_absorb_requires_stat,
            "self_absorb_shield_id": self.self_absorb_shield_id,
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class StatusAuraEffect:
    """Timed non-periodic actor/target aura, used by event-driven mechanics."""
    effect_type: str
    aura_id: str
    target: str
    duration_s: float
    refresh_rule: str = 'replace'
    exclusive_group: str | None = None
    actor_stat_deltas: Mapping[str, float] = field(default_factory=dict)
    actor_resource_capacity_deltas: Mapping[str, float] = field(default_factory=dict)
    auto_attack_speed_multiplier: float = 1.0
    apply_primary_stat_conversions: bool = False
    # Source-valued absorb capacity tied to the same timed aura generation.
    # Only an explicitly all-school shield can use this generic capacity.
    actor_absorb_amount: float = 0.0
    actor_absorb_spell_power_coefficient: float = 0.0
    stealth: bool = False
    indefinite: bool = False
    movement_speed_multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        result = {'effect_type': self.effect_type, 'aura_id': self.aura_id,
                  'target': self.target, 'duration_s': float(self.duration_s),
                  'refresh_rule': self.refresh_rule}
        if self.exclusive_group is not None:
            result['exclusive_group'] = self.exclusive_group
        if self.actor_stat_deltas:
            result['actor_stat_deltas'] = dict(self.actor_stat_deltas)
        if self.actor_resource_capacity_deltas:
            result['actor_resource_capacity_deltas'] = dict(self.actor_resource_capacity_deltas)
        if self.apply_primary_stat_conversions:
            result['apply_primary_stat_conversions'] = True
        if self.auto_attack_speed_multiplier != 1.0:
            result['auto_attack_speed_multiplier'] = self.auto_attack_speed_multiplier
        if self.actor_absorb_amount != 0.0:
            result['actor_absorb_amount'] = float(self.actor_absorb_amount)
        if self.actor_absorb_spell_power_coefficient != 0.0:
            result['actor_absorb_spell_power_coefficient'] = float(self.actor_absorb_spell_power_coefficient)
        if self.stealth:
            result['stealth'] = True
            result['movement_speed_multiplier'] = float(self.movement_speed_multiplier)
        if self.indefinite:
            result['indefinite'] = True
        return result


@dataclass(frozen=True)
class EventEmitEffect:
    """Action-generated generic combat event, consumed by registered triggers."""
    effect_type: str
    event_kind: str
    target: str = 'enemy'
    clears_target_exclusive_group: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type': self.effect_type, 'event_kind': self.event_kind,
                'target': self.target, 'clears_target_exclusive_group': self.clears_target_exclusive_group}


@dataclass(frozen=True)
class TargetSchoolPowerEffect:
    """Source-valued temporary target spell-power vulnerability, applied by a trigger.

    The amount is *spell power*, not raw damage. Individual effects retain
    their own SP coefficient. The aura has target-level expiry and exclusivity.
    """
    effect_type: str
    aura_id: str
    school: str
    bonus_spell_power: float
    duration_s: float
    exclusive_group: str

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type':self.effect_type,'aura_id':self.aura_id,
                'school':self.school,'bonus_spell_power':float(self.bonus_spell_power),
                'duration_s':float(self.duration_s),'exclusive_group':self.exclusive_group}


@dataclass(frozen=True)
class TargetStatDebuffEffect:
    """Timed source-valued enemy stat modifier, with replace/expiry semantics."""
    effect_type: str
    aura_id: str
    target_stat_id: str
    delta: float
    duration_s: float
    refresh_rule: str = 'replace'
    provenance: tuple[Mapping[str, Any], ...] = ()
    target: str = 'enemy'

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type': self.effect_type, 'aura_id': self.aura_id,
                'target': self.target,
                'target_stat_id': self.target_stat_id, 'delta': float(self.delta),
                'duration_s': float(self.duration_s), 'refresh_rule': self.refresh_rule,
                'provenance': [dict(x) for x in self.provenance]}


@dataclass(frozen=True)
class SpatialChargeEffect:
    """Generic immediate leap to a hostile target in explicit 2D geometry."""
    effect_type: str
    target: str
    minimum_range_yards: float
    maximum_range_yards: float
    arrival_distance_yards: float
    arrival_position_kind: str = 'target_contact'

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type':self.effect_type,'target':self.target,
            'minimum_range_yards':float(self.minimum_range_yards),
            'maximum_range_yards':float(self.maximum_range_yards),
            'arrival_distance_yards':float(self.arrival_distance_yards),
            'arrival_position_kind':self.arrival_position_kind}


@dataclass(frozen=True)
class ControlEffect:
    """Timed control, with optional source-declared combat suppression and break conditions."""
    effect_type: str
    control_id: str
    target: str
    duration_s: float
    prevents_enemy_actions: bool = False
    breaks_on_damage: bool = False
    proc_chance: float = 1.0
    break_chance_on_damage: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"effect_type": self.effect_type, "control_id": self.control_id,
                "target": self.target, "duration_s": float(self.duration_s),
                "prevents_enemy_actions": bool(self.prevents_enemy_actions),
                "breaks_on_damage": bool(self.breaks_on_damage),
                "proc_chance": float(self.proc_chance),
                "break_chance_on_damage": (None if self.break_chance_on_damage is None
                    else float(self.break_chance_on_damage))}


@dataclass(frozen=True)
class TriggerDefinition:
    """Generic event -> Effect trigger.

    The trigger listens to runtime event vocabulary (for example
    ``damage_taken``), optionally scales expected effects by an event
    probability field, and emits ordinary executable Effects.  Activation is
    data, not class/spell dispatch; long-lived maintenance buffs may compile to
    an ``active_by_default`` trigger when their per-pull cast cost is explicitly
    amortized outside combat.
    """
    id: str
    name: str
    owner_actor_id: str
    event_kind: str
    effects: tuple[DamageEffect | WeaponDamageEffect | TargetSchoolPowerEffect | ControlEffect | PeriodicEffect, ...]
    active_by_default: bool = True
    required_mode_id: str | None = None
    event_probability_field: str | None = None
    required_aura_id: str | None = None
    event_scale_field: str | None = None
    event_scale_reference: float | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id), "kind": "event_trigger", "name": str(self.name),
            "owner_actor_id": str(self.owner_actor_id), "event_kind": str(self.event_kind),
            "effects": [x.as_dict() for x in self.effects],
            "active_by_default": bool(self.active_by_default),
            "required_mode_id": self.required_mode_id,
            "event_probability_field": self.event_probability_field,
            "required_aura_id": self.required_aura_id,
            "event_scale_field": self.event_scale_field,
            "event_scale_reference": self.event_scale_reference,
            "filters": dict(self.filters),
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HealEffect:
    effect_type: str
    target: str
    resource_id: str
    base_min: float
    base_max: float
    spell_power_coefficient: float = 0.0
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()
    crit_chance_bonus: float = 0.0
    crit_multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": self.effect_type,
            "target": self.target,
            "resource_id": self.resource_id,
            "base_min": float(self.base_min),
            "base_max": float(self.base_max),
            "spell_power_coefficient": float(self.spell_power_coefficient),
            "crit_chance_bonus": float(self.crit_chance_bonus),
            "crit_multiplier": float(self.crit_multiplier),
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class ActivePeriodicFullHealEffect:
    """Instant full-*duration* value of a qualifying active periodic heal.

    Source declares acceptable source action families. The active aura is not
    consumed; the executor resolves the originating periodic effect at cast.
    """
    effect_type: str
    target: str
    resource_id: str
    source_families: tuple[str,...]
    multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type':self.effect_type,'target':self.target,
                'resource_id':self.resource_id,
                'source_families':list(self.source_families),
                'multiplier':float(self.multiplier)}


@dataclass(frozen=True)
class PeriodicHealEffect:
    effect_type: str
    target: str
    resource_id: str
    aura_id: str
    total_base_heal: float
    duration_s: float
    tick_interval_s: float
    spell_power_coefficient_per_tick: float = 0.0
    refresh_rule: str = "replace"
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": self.effect_type,
            "target": self.target,
            "resource_id": self.resource_id,
            "aura_id": self.aura_id,
            "total_base_heal": float(self.total_base_heal),
            "duration_s": float(self.duration_s),
            "tick_interval_s": float(self.tick_interval_s),
            "spell_power_coefficient_per_tick": float(self.spell_power_coefficient_per_tick),
            "refresh_rule": self.refresh_rule,
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class PeriodicEffect:
    effect_type: str
    school: str
    target: str
    aura_id: str
    total_base_damage: float
    duration_s: float
    tick_interval_s: float
    spell_power_coefficient_per_tick: float = 0.0
    refresh_rule: str = "replace"
    field_provenance: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    crit_chance_bonus: float = 0.0
    crit_multiplier: float = 2.0
    crit_chance_stat_id: str | None = None
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": self.effect_type,
            "school": self.school,
            "target": self.target,
            "aura_id": self.aura_id,
            "total_base_damage": float(self.total_base_damage),
            "duration_s": float(self.duration_s),
            "tick_interval_s": float(self.tick_interval_s),
            "spell_power_coefficient_per_tick": float(self.spell_power_coefficient_per_tick),
            "crit_chance_bonus": float(self.crit_chance_bonus), "crit_multiplier": float(self.crit_multiplier),
            "crit_chance_stat_id": self.crit_chance_stat_id,
            "refresh_rule": self.refresh_rule,
            "field_provenance": {str(k): [dict(x) for x in v] for k, v in self.field_provenance.items()},
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
        }


@dataclass(frozen=True)
class TalentModifier:
    kind: str
    target_type: str
    target_id: str
    value: float
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "target_type": self.target_type, "target_id": self.target_id,
            "value": float(self.value), "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class TalentRankDefinition:
    rank: int
    modifiers: tuple[TalentModifier, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"rank": int(self.rank), "modifiers": [x.as_dict() for x in self.modifiers], "provenance": dict(self.provenance)}


@dataclass(frozen=True)
class TalentDefinition:
    id: str
    name: str
    tree_key: str
    max_rank: int
    prerequisite: Mapping[str, Any] | None = None
    ranks: tuple[TalentRankDefinition, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "tree_key": self.tree_key, "max_rank": int(self.max_rank),
            "prerequisite": None if self.prerequisite is None else dict(self.prerequisite),
            "ranks": [x.as_dict() for x in self.ranks],
            "provenance": [dict(x) for x in self.provenance], "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PolicyCondition:
    """Canonical backend-neutral priority-policy predicate.

    Supported executable kinds are intentionally small and reusable:
    aura_present/aura_missing, resource_threshold, mode_state, and target_state.
    """
    kind: str
    scope: str | None = None
    field: str | None = None
    aura_id: str | None = None
    resource_id: str | None = None
    operator: str | None = None
    value: Any = None
    threshold_source: str | None = None
    search_values: tuple[float, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {"kind": str(self.kind)}
        if self.scope is not None: out["scope"] = str(self.scope)
        if self.field is not None: out["field"] = str(self.field)
        if self.aura_id is not None: out["aura_id"] = str(self.aura_id)
        if self.resource_id is not None: out["resource_id"] = str(self.resource_id)
        if self.operator is not None: out["operator"] = str(self.operator)
        if self.value is not None: out["value"] = self.value
        if self.threshold_source is not None: out["threshold_source"] = str(self.threshold_source)
        if self.search_values is not None: out["search_values"] = [float(x) for x in self.search_values]
        return out


@dataclass(frozen=True)
class PolicyRuleDefinition:
    id: str
    action_id: str
    conditions: tuple[PolicyCondition, ...] = ()
    phase: str = "combat"
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "phase": self.phase, "action_id": self.action_id,
            "conditions": [x.as_dict() for x in self.conditions],
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class PolicyDefinition:
    id: str
    label: str
    rules: tuple[PolicyRuleDefinition, ...]
    maintenance: tuple[Mapping[str, Any], ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": "priority_policy", "label": self.label,
            "rules": [x.as_dict() for x in self.rules],
            "maintenance": [dict(x) for x in self.maintenance],
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class ModeStatModifier:
    target_stat: str
    kind: str
    value: float
    source_stat: str | None = None
    reference_level_multiplier: float | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "target_stat": str(self.target_stat),
            "kind": str(self.kind),
            "value": float(self.value),
        }
        if self.source_stat is not None:
            out["source_stat"] = str(self.source_stat)
        if self.reference_level_multiplier is not None:
            out["reference_level_multiplier"] = float(self.reference_level_multiplier)
        return out


@dataclass(frozen=True)
class ModeResourceCapacityModifier:
    resource_id: str
    kind: str
    value: float
    source_stat: str

    def as_dict(self) -> dict[str, Any]:
        return {'resource_id': str(self.resource_id), 'kind': str(self.kind),
                'value': float(self.value), 'source_stat': str(self.source_stat)}


@dataclass(frozen=True)
class ModeResourceRule:
    resource_id: str
    active: bool
    on_enter: str = "preserve"
    on_exit: str = "preserve"
    enter_value: float | None = None
    exit_value: float | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "resource_id": str(self.resource_id),
            "active": bool(self.active),
            "on_enter": str(self.on_enter),
            "on_exit": str(self.on_exit),
        }
        if self.enter_value is not None:
            out["enter_value"] = float(self.enter_value)
        if self.exit_value is not None:
            out["exit_value"] = float(self.exit_value)
        return out


@dataclass(frozen=True)
class ModeEntryResourceModifier:
    """Source-configured expected resource gain or retained-resource restoration.

    `expected_flat_gain` is an already probability-weighted gain. For
    `restore_last_mode_resource`, the source supplies retained_fraction,
    outside_regen_per_s and a hard restoration cap; forbidden modes wipe the
    stored balance and prevent outside regeneration.
    """
    kind: str
    resource_id: str
    value: float
    outside_regen_per_s: float = 0.0
    max_restored: float = 0.0
    forbidden_mode_ids: tuple[str, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "resource_id": self.resource_id,
                "value": float(self.value), "outside_regen_per_s": float(self.outside_regen_per_s),
                "max_restored": float(self.max_restored),
                "forbidden_mode_ids": list(self.forbidden_mode_ids),
                "provenance": [dict(x) for x in self.provenance]}


@dataclass(frozen=True)
class ModeDefinition:
    id: str
    label: str
    initial: bool = False
    enabled_action_ids: tuple[str, ...] | None = None
    stat_modifiers: tuple[ModeStatModifier, ...] = ()
    resource_rules: tuple[ModeResourceRule, ...] = ()
    resource_capacity_modifiers: tuple[ModeResourceCapacityModifier, ...] = ()
    entry_resource_modifiers: tuple[ModeEntryResourceModifier, ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": "combat_mode",
            "label": str(self.label),
            "initial": bool(self.initial),
            "enabled_action_ids": (
                None if self.enabled_action_ids is None else [str(x) for x in self.enabled_action_ids]
            ),
            "stat_modifiers": [x.as_dict() for x in self.stat_modifiers],
            "resource_rules": [x.as_dict() for x in self.resource_rules],
            "resource_capacity_modifiers": [x.as_dict() for x in self.resource_capacity_modifiers],
            "entry_resource_modifiers": [x.as_dict() for x in self.entry_resource_modifiers],
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ModeChangeEffect:
    effect_type: str
    target_mode_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": str(self.effect_type),
            "target_mode_id": str(self.target_mode_id),
        }


@dataclass(frozen=True)
class AutoAttackDamageSource:
    """Generic per-second damage source for a repeated auto attack.

    ``flat_dps`` covers a source-backed equipped/natural weapon anchor.
    ``dps_stat_id`` lets later Warrior/Rogue/Hunter slices take weapon DPS from
    actor state instead. Attack Power contributes through the normal AP/14 DPS
    conversion without making the runtime aware of any class.
    """

    kind: str
    flat_dps: float = 0.0
    dps_stat_id: str | None = None
    attack_power_stat_id: str | None = "attack_power"
    attack_power_per_dps: float = 14.0
    damage_multiplier: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "flat_dps": float(self.flat_dps),
            "dps_stat_id": self.dps_stat_id,
            "attack_power_stat_id": self.attack_power_stat_id,
            "attack_power_per_dps": float(self.attack_power_per_dps),
            "damage_multiplier": float(self.damage_multiplier),
        }


@dataclass(frozen=True)
class WeaponDamageEffect:
    """Reusable instant weapon/natural-attack damage effect.

    The source is expressed as DPS + Attack Power/14, then converted to one
    normalized weapon hit and modified by the action multiplier/flat bonus.
    Outcome probabilities stay explicit data so later canonical hit/crit
    derivation can replace the provisional probabilities without class code.
    """
    effect_type: str
    school: str
    target: str
    damage_source: "AutoAttackDamageSource"
    weapon_damage_time_s: float
    weapon_damage_multiplier: float = 1.0
    flat_damage: float = 0.0
    hit_chance: float = 1.0
    crit_chance_on_landed_hit: float = 0.0
    crit_multiplier: float = 2.0
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect_type": str(self.effect_type), "school": str(self.school), "target": str(self.target),
            "damage_source": self.damage_source.as_dict(),
            "weapon_damage_time_s": float(self.weapon_damage_time_s),
            "weapon_damage_multiplier": float(self.weapon_damage_multiplier),
            "flat_damage": float(self.flat_damage),
            "hit_chance": float(self.hit_chance),
            "crit_chance_on_landed_hit": float(self.crit_chance_on_landed_hit),
            "crit_multiplier": float(self.crit_multiplier),
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class QueuedSwingEffect:
    """Replace the next eligible auto swing with its normal hit plus source bonus.

    The action pays costs on queue.  The next auto attack owns the damage
    timestamp and swing timer.  No immediate damage or extra swing is emitted.
    """
    effect_type: str
    target: str
    auto_attack_id: str
    bonus_damage: float

    def as_dict(self) -> dict[str, Any]:
        return {'effect_type': self.effect_type, 'target': self.target,
                'auto_attack_id': self.auto_attack_id, 'bonus_damage': float(self.bonus_damage)}


@dataclass(frozen=True)
class AutoAttackDefinition:
    id: str
    name: str
    owner_actor_id: str
    attack_type: str
    swing_time_s: float
    school: str
    damage_source: AutoAttackDamageSource
    required_mode_id: str | None = None
    hit_chance: float = 1.0
    crit_chance_on_landed_hit: float = 0.0
    crit_multiplier: float = 2.0
    crit_chance_stat_id: str | None = None
    exclusive_with_casts: bool = False
    provenance: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "kind": "auto_attack",
            "name": str(self.name),
            "owner_actor_id": str(self.owner_actor_id),
            "attack_type": str(self.attack_type),
            "swing_time_s": float(self.swing_time_s),
            "school": str(self.school),
            "damage_source": self.damage_source.as_dict(),
            "required_mode_id": self.required_mode_id,
            "hit_chance": float(self.hit_chance),
            "crit_chance_on_landed_hit": float(self.crit_chance_on_landed_hit),
            "crit_multiplier": float(self.crit_multiplier),
            "exclusive_with_casts": bool(self.exclusive_with_casts),
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    family_key: str
    name: str
    owner_actor_id: str
    requirements: tuple[Mapping[str, Any], ...]
    costs: tuple[ResourceCost, ...]
    cast_time_s: float
    gcd_s: float
    cooldown_s: float
    effects: tuple[QueuedSwingEffect | StatusAuraEffect | EventEmitEffect | ControlEffect | SpatialChargeEffect | SummonEffect | DamageEffect | WeaponDamageEffect | PeriodicEffect | PeriodicResourceEffect | ResourceScaledPeriodicEffect | ResourceScaledDirectDamageEffect | ResourceChangeEffect | HealEffect | PeriodicHealEffect | ActivePeriodicFullHealEffect | ModeChangeEffect, ...]
    provenance: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_key": self.family_key,
            "name": self.name,
            "owner_actor_id": self.owner_actor_id,
            "requirements": [dict(x) for x in self.requirements],
            "costs": [x.as_dict() for x in self.costs],
            "cast_time_s": float(self.cast_time_s),
            "gcd_s": float(self.gcd_s),
            "cooldown_s": float(self.cooldown_s),
            "effects": [x.as_dict() for x in self.effects],
            "provenance": [dict(x) for x in self.provenance],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GameIRSlice:
    id: str
    ruleset: str
    actor: ActorDefinition
    resources: tuple[ResourceDefinition, ...]
    actions: tuple[ActionDefinition, ...]
    talents: tuple[TalentDefinition, ...] = ()
    policies: tuple[PolicyDefinition, ...] = ()
    modes: tuple[ModeDefinition, ...] = ()
    auto_attacks: tuple[AutoAttackDefinition, ...] = ()
    mitigation_rules: tuple[ArmorMitigationDefinition, ...] = ()
    incoming_attacks: tuple[IncomingAttackDefinition, ...] = ()
    triggers: tuple[TriggerDefinition, ...] = ()
    source_facts: tuple[Mapping[str, Any], ...] = ()
    overlays: tuple[Mapping[str, Any], ...] = ()
    unsupported_semantics: tuple[Mapping[str, Any], ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    companions: tuple[ActorDefinition, ...] = ()
    actor_links: tuple[ActorLinkModifier, ...] = ()
    timed_summons: tuple[TimedSummonDefinition, ...] = ()
    schema_version: int = GAME_IR_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "id": self.id,
            "ruleset": self.ruleset,
            "actor": self.actor.as_dict(),
            "companions": [x.as_dict() for x in self.companions],
            "actor_links": [x.as_dict() for x in self.actor_links],
            "timed_summons": [x.as_dict() for x in self.timed_summons],
            "resources": [x.as_dict() for x in self.resources],
            "actions": [x.as_dict() for x in self.actions],
            "talents": [x.as_dict() for x in self.talents],
            "policies": [x.as_dict() for x in self.policies],
            "modes": [x.as_dict() for x in self.modes],
            "auto_attacks": [x.as_dict() for x in self.auto_attacks],
            "mitigation_rules": [x.as_dict() for x in self.mitigation_rules],
            "incoming_attacks": [x.as_dict() for x in self.incoming_attacks],
            "triggers": [x.as_dict() for x in self.triggers],
            "source_facts": [dict(x) for x in self.source_facts],
            "overlays": [dict(x) for x in self.overlays],
            "unsupported_semantics": [dict(x) for x in self.unsupported_semantics],
            "provenance": dict(self.provenance),
        }

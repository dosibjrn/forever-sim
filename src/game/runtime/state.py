from __future__ import annotations

"""Backend-neutral mutable runtime state constructed from Game IR."""

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping

from src.game.model.ir import ActorDefinition, ModeDefinition, ModeResourceRule, ModeStatModifier, ResourceDefinition


@dataclass
class ActorState:
    id: str
    stats: dict[str, float] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)
    resource_capacity: dict[str, float] = field(default_factory=dict)
    resource_initial_amount: dict[str, float] = field(default_factory=dict)
    resource_active: dict[str, bool] = field(default_factory=dict)
    resource_regeneration_per_s: dict[str, float] = field(default_factory=dict)
    resource_definitions: dict[str, ResourceDefinition] = field(default_factory=dict)
    mode_definitions: dict[str, ModeDefinition] = field(default_factory=dict)
    current_mode_id: str | None = None
    mode_stat_adjustments: dict[str, float] = field(default_factory=dict)
    mode_resource_capacity_adjustments: dict[str, float] = field(default_factory=dict)
    last_mode_resource_snapshots: dict[str, dict[str, float]] = field(default_factory=dict)
    last_mode_exit_time_s: dict[str, float] = field(default_factory=dict)
    forfeited_mode_resource_ids: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    current_time_s: float = 0.0
    gcd_ready_s: float = 0.0
    cooldown_ready_s: dict[str, float] = field(default_factory=dict)
    source_cast_charge_banks: dict[str, dict[str, float | int]] = field(default_factory=dict)
    source_timed_spell_crit_haste_until_s: float = 0.0
    # Actor-owned, persistent between encounters; bank content is sourced
    # from a granted action, never inferred from a class/spell ID.
    source_next_cast_instant_charges: dict[str, int] = field(default_factory=dict)
    active_auras: dict[str, "AuraState"] = field(default_factory=dict)
    # Source-aura modifiers persist with actor auras across repeated encounters.
    aura_stat_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    aura_resource_capacity_deltas: dict[str, dict[str, float]] = field(default_factory=dict)
    aura_attack_speed_multipliers: dict[str, float] = field(default_factory=dict)
    absorb_shields: dict[str, float] = field(default_factory=dict)
    aura_generations: dict[str, int] = field(default_factory=dict)
    # Pending actor-scoped periodic effects survive an encounter boundary.
    # These are runtime events + the original source Action IR, never inferred
    # from aura names or reconstructed from tooltip guesses.
    pending_actor_periodic_events: tuple[Any, ...] = ()
    pending_actor_periodic_actions: dict[str, Any] = field(default_factory=dict)

    def effective_healing_power(self, spell_power: float) -> float:
        """Source-declared healing-only stat conversions on current equipped stats."""
        total = float(spell_power)
        for source_stat, coefficient in dict(
                self.metadata.get('source_healing_power_from_stats') or {}).items():
            value = float(self.stats.get(str(source_stat), 0.))
            coefficient = float(coefficient)
            if not isfinite(value) or not isfinite(coefficient) or coefficient < 0.:
                raise ValueError('INVALID_SOURCE_HEALING_STAT_CONVERSION')
            total += value * coefficient
        return total

    @classmethod
    def from_ir(
        cls,
        actor: ActorDefinition,
        resources: tuple[ResourceDefinition, ...],
        modes: tuple[ModeDefinition, ...] = (),
    ) -> "ActorState":
        values: dict[str, float] = {}
        capacity: dict[str, float] = {}
        initial: dict[str, float] = {}
        active: dict[str, bool] = {}
        regen: dict[str, float] = {}
        definitions: dict[str, ResourceDefinition] = {}
        for resource in resources:
            if resource.owner_actor_id != actor.id:
                continue
            definitions[str(resource.id)] = resource
            if str(resource.scope or "actor") == "target":
                continue
            if resource.initial_amount is not None:
                values[resource.id] = float(resource.initial_amount)
                initial[resource.id] = float(resource.initial_amount)
            if resource.capacity is not None:
                capacity[resource.id] = float(resource.capacity)
            active[resource.id] = bool(resource.active_by_default)
            regen[resource.id] = max(0.0, float(resource.regeneration_per_s))
        # Passive equipment HP5 applies during combat as well as recovery.
        # ResourceDefinition regeneration (energy etc.) remains authoritative;
        # this is an additive sourced actor-stat channel, not a new spell.
        hp5 = float(actor.base_stats.get('health_regeneration_per_5s', 0.0))
        if not isfinite(hp5) or hp5 < 0.:
            raise ValueError('INVALID_SOURCE_HEALTH_REGEN_PER_5S')
        if hp5 and 'health' in regen:
            regen['health'] = regen.get('health', 0.0) + hp5 / 5.0
        mode_map = {str(mode.id): mode for mode in modes}
        initial_modes = [mode for mode in modes if bool(mode.initial)]
        if len(initial_modes) > 1:
            raise ValueError("actor Game IR contains multiple initial modes")
        state = cls(
            id=str(actor.id),
            stats={str(k): float(v) for k, v in dict(actor.base_stats).items()},
            resources=values,
            resource_capacity=capacity,
            resource_initial_amount=initial,
            resource_active=active,
            resource_regeneration_per_s=regen,
            resource_definitions=definitions,
            mode_definitions=mode_map,
            metadata={**dict(actor.metadata), "declared_base_stat_ids": tuple(str(k) for k in actor.base_stats)},
        )
        if initial_modes:
            state.transition_mode(str(initial_modes[0].id))
        return state

    def resource_scope(self, resource_id: str) -> str | None:
        definition = self.resource_definitions.get(str(resource_id))
        return None if definition is None else str(definition.scope or "actor")

    def resource_amount(self, resource_id: str) -> float | None:
        value = self.resources.get(str(resource_id))
        return None if value is None else float(value)

    def resource_is_active(self, resource_id: str) -> bool:
        return bool(self.resource_active.get(str(resource_id), False))

    def can_spend(self, resource_id: str, amount: float) -> bool:
        current = self.resource_amount(resource_id)
        return self.resource_is_active(resource_id) and current is not None and current + 1e-12 >= max(0.0, float(amount))

    def spend(self, resource_id: str, amount: float) -> tuple[float, float]:
        resource_id = str(resource_id)
        cost = max(0.0, float(amount))
        current = self.resource_amount(resource_id)
        if current is None:
            raise ValueError(f"resource {resource_id!r} is not present in actor state")
        if current + 1e-12 < cost:
            raise ValueError(f"insufficient {resource_id}: have {current}, need {cost}")
        remaining = max(0.0, current - cost)
        self.resources[resource_id] = remaining
        return current, remaining

    def regenerate_for(self, elapsed_s: float) -> tuple[dict[str, float | str], ...]:
        elapsed = max(0.0, float(elapsed_s))
        if elapsed <= 0.0:
            return ()
        rows: list[dict[str, float | str]] = []
        for resource_id, rate in self.resource_regeneration_per_s.items():
            rate = max(0.0, float(rate))
            if rate <= 0.0 or not self.resource_is_active(resource_id):
                continue
            current = self.resource_amount(resource_id)
            capacity = self.resource_capacity.get(resource_id)
            if current is None or capacity is None:
                continue
            after = min(float(capacity), float(current) + rate * elapsed)
            gained = max(0.0, after - float(current))
            if gained <= 1e-12:
                continue
            self.resources[resource_id] = after
            rows.append({
                "resource_id": str(resource_id), "before": float(current), "after": float(after),
                "gained": float(gained), "elapsed_s": float(elapsed), "regeneration_per_s": float(rate),
            })
        return tuple(rows)

    def deplete(self, resource_id: str, amount: float) -> tuple[float, float, float]:
        """Apply a clamped loss to one actor Resource (for example Health)."""
        resource_id = str(resource_id)
        current = self.resource_amount(resource_id)
        if current is None:
            raise ValueError(f"resource {resource_id!r} is not present in actor state")
        requested = max(0.0, float(amount))
        after = max(0.0, float(current) - requested)
        self.resources[resource_id] = after
        return float(current), float(after), max(0.0, float(current) - after)

    def resource_positive(self, resource_id: str) -> bool:
        current = self.resource_amount(resource_id)
        return current is not None and float(current) > 1e-12

    def restore(self, resource_id: str, amount: float) -> tuple[float, float, float]:
        resource_id = str(resource_id)
        current = self.resource_amount(resource_id)
        capacity = self.resource_capacity.get(resource_id)
        if current is None or capacity is None:
            raise ValueError(f"resource {resource_id!r} is not restorable in actor state")
        requested = max(0.0, float(amount))
        after = min(float(capacity), float(current) + requested)
        self.resources[resource_id] = after
        return float(current), float(after), max(0.0, after - float(current))

    def expire_elapsed_auras(self, at_time_s: float) -> tuple[str, ...]:
        """Reconcile actor aura modifiers after off-combat clock advancement.

        The combat event queue is encounter-scoped. Status aura expiry events
        are not carried through food/water recovery; the shared ActorState is.
        This removes only genuinely elapsed auras and reverses their stat/rate
        modifiers exactly once before the next combat's auto-attack schedule.
        """
        elapsed=[]
        for aura_id,aura in tuple(self.active_auras.items()):
            if float(aura.expires_at_s) > float(at_time_s)+1e-12:
                continue
            if self.remove_aura(aura_id,aura.generation) is None:
                continue
            for stat,delta in self.aura_stat_deltas.pop(aura_id,{}).items():
                self.stats[stat]=float(self.stats.get(stat,0.0))-float(delta)
            for resource,delta in self.aura_resource_capacity_deltas.pop(aura_id,{}).items():
                old_cap=float(self.resource_capacity[resource])
                new_cap=old_cap-float(delta)
                if new_cap <= 0:
                    raise ValueError('actor aura capacity removal invalid')
                if resource in self.resources:
                    self.resources[resource]=float(self.resources[resource])*new_cap/old_cap
                self.resource_capacity[resource]=new_cap
            self.aura_attack_speed_multipliers.pop(aura_id,None)
            elapsed.append(aura_id)
        return tuple(elapsed)

    def apply_aura(
        self, *, aura_id: str, source_action_id: str, applied_at_s: float,
        duration_s: float, refresh_rule: str, exclusive_group: str | None = None,
    ) -> tuple["AuraState" | None, "AuraState"]:
        aura_id = str(aura_id)
        if refresh_rule != "replace":
            raise ValueError(f"unsupported aura refresh rule: {refresh_rule}")
        previous = self.active_auras.get(aura_id)
        generation = int(self.aura_generations.get(aura_id, 0)) + 1
        self.aura_generations[aura_id] = generation
        aura = AuraState(
            id=aura_id, source_action_id=str(source_action_id), generation=generation,
            applied_at_s=float(applied_at_s),
            expires_at_s=float(applied_at_s) + max(0.0, float(duration_s)),
            refresh_rule=str(refresh_rule),
            exclusive_group=exclusive_group,
        )
        self.active_auras[aura_id] = aura
        return previous, aura

    def remove_aura(self, aura_id: str, generation: int | None = None) -> "AuraState" | None:
        current = self.active_auras.get(str(aura_id))
        if current is None:
            return None
        if generation is not None and int(current.generation) != int(generation):
            return None
        return self.active_auras.pop(str(aura_id), None)

    def _apply_resource_behavior(self, resource_id: str, behavior: str, value: float | None) -> tuple[float | None, float | None]:
        resource_id = str(resource_id)
        before = self.resource_amount(resource_id)
        behavior = str(behavior or "preserve")
        if behavior == "preserve":
            return before, before
        if before is None:
            raise ValueError(f"mode rule references unavailable resource {resource_id!r}")
        if behavior == "reset_to_initial":
            if resource_id not in self.resource_initial_amount:
                raise ValueError(f"resource {resource_id!r} has no initial amount")
            after = float(self.resource_initial_amount[resource_id])
        elif behavior == "reset_to_capacity":
            if resource_id not in self.resource_capacity:
                raise ValueError(f"resource {resource_id!r} has no capacity")
            after = float(self.resource_capacity[resource_id])
        elif behavior == "reset_to_zero":
            after = 0.0
        elif behavior == "set_value":
            if value is None:
                raise ValueError("set_value mode resource behavior requires a value")
            after = float(value)
        else:
            raise ValueError(f"unsupported mode resource behavior: {behavior}")
        capacity = self.resource_capacity.get(resource_id)
        if capacity is not None:
            after = max(0.0, min(float(capacity), after))
        self.resources[resource_id] = float(after)
        return before, float(after)

    def _modifier_amount(self, modifier: ModeStatModifier) -> float:
        kind = str(modifier.kind)
        if kind == "add_flat":
            return float(modifier.value)
        if kind == "add_stat_scaled":
            if modifier.source_stat is None:
                raise ValueError("add_stat_scaled mode modifier requires source_stat")
            return float(self.stats.get(str(modifier.source_stat), 0.0)) * float(modifier.value)
        if kind == "add_level_scaled":
            if "level" not in self.metadata:
                raise ValueError("add_level_scaled requires source actor level")
            return float(self.metadata["level"]) * float(modifier.value)
        if kind == "add_stat_above_level_scaled":
            if (modifier.source_stat is None or modifier.reference_level_multiplier is None
                    or "level" not in self.metadata):
                raise ValueError("add_stat_above_level_scaled requires source stat, level and threshold")
            excess = max(0.0, float(self.stats.get(str(modifier.source_stat), 0.0))
                         - float(self.metadata["level"]) * float(modifier.reference_level_multiplier))
            return excess * float(modifier.value)
        raise ValueError(f"unsupported mode stat modifier: {kind}")

    def transition_mode(self, target_mode_id: str) -> dict[str, Any]:
        target_mode_id = str(target_mode_id)
        if target_mode_id not in self.mode_definitions:
            raise ValueError(f"unknown target mode {target_mode_id!r}")
        previous_id = self.current_mode_id
        previous = self.mode_definitions.get(str(previous_id)) if previous_id is not None else None
        target = self.mode_definitions[target_mode_id]

        resource_changes: list[dict[str, Any]] = []
        if previous is not None:
            # Capture the previous form's resource BEFORE its source-declared
            # exit reset; otherwise a retention talent could only restore 0.
            self.last_mode_resource_snapshots[str(previous.id)] = {
                str(rule.resource_id): float(self.resources[rule.resource_id])
                for rule in previous.resource_rules if rule.resource_id in self.resources}
            self.last_mode_exit_time_s[str(previous.id)] = float(self.current_time_s)
            for rule in previous.resource_rules:
                before, after = self._apply_resource_behavior(rule.resource_id, rule.on_exit, rule.exit_value)
                resource_changes.append({
                    "phase": "exit", "mode_id": previous.id, "resource_id": rule.resource_id,
                    "behavior": rule.on_exit, "before": before, "after": after,
                    "active_before": self.resource_is_active(rule.resource_id),
                })

        for stat, amount in tuple(self.mode_stat_adjustments.items()):
            self.stats[stat] = float(self.stats.get(stat, 0.0)) - float(amount)
            if abs(self.stats[stat]) <= 1e-12 and stat not in self.metadata.get("declared_base_stat_ids", ()):
                self.stats.pop(stat, None)
        self.mode_stat_adjustments = {}

        # Remove old form's capacity bonus before applying the new one.
        # Preserve the percentage of HP/Mana when capacity changes, so entering
        # or leaving a mode neither grants free recovery nor destroys health.
        for resource_id, amount in tuple(self.mode_resource_capacity_adjustments.items()):
            old_cap = float(self.resource_capacity[resource_id])
            new_cap = old_cap - float(amount)
            if new_cap <= 0:
                raise ValueError('mode capacity removal would create invalid resource')
            current = self.resources.get(resource_id)
            if current is not None:
                self.resources[resource_id] = max(0.0, min(new_cap, float(current) * new_cap / old_cap))
            self.resource_capacity[resource_id] = new_cap
        self.mode_resource_capacity_adjustments = {}

        for rule in target.resource_rules:
            active_before = self.resource_is_active(rule.resource_id)
            before, after = self._apply_resource_behavior(rule.resource_id, rule.on_enter, rule.enter_value)
            self.resource_active[str(rule.resource_id)] = bool(rule.active)
            resource_changes.append({
                "phase": "enter", "mode_id": target.id, "resource_id": rule.resource_id,
                "behavior": rule.on_enter, "before": before, "after": after,
                "active_before": active_before, "active_after": bool(rule.active),
            })

        capacity_adjustments: dict[str, float] = {}
        for modifier in target.resource_capacity_modifiers:
            if modifier.kind != 'add_stat_scaled':
                raise ValueError(f'unsupported mode capacity modifier: {modifier.kind}')
            if modifier.source_stat not in self.stats:
                raise ValueError(f'mode capacity source stat unavailable: {modifier.source_stat}')
            if modifier.resource_id not in self.resource_capacity:
                raise ValueError(f'mode capacity resource unavailable: {modifier.resource_id}')
            amount = float(self.stats[modifier.source_stat]) * float(modifier.value)
            capacity_adjustments[modifier.resource_id] = (capacity_adjustments.get(modifier.resource_id, 0.0) + amount)
        adjustments: dict[str, float] = {}
        for modifier in target.stat_modifiers:
            amount = self._modifier_amount(modifier)
            key = str(modifier.target_stat)
            adjustments[key] = float(adjustments.get(key, 0.0)) + float(amount)
        for stat, amount in adjustments.items():
            self.stats[stat] = float(self.stats.get(stat, 0.0)) + float(amount)
        self.mode_stat_adjustments = adjustments
        for resource_id, amount in capacity_adjustments.items():
            old_cap = float(self.resource_capacity[resource_id])
            new_cap = old_cap + float(amount)
            if new_cap <= 0:
                raise ValueError('mode capacity modifier would create invalid resource')
            current = self.resources.get(resource_id)
            if current is not None:
                self.resources[resource_id] = max(0.0, min(new_cap, float(current) * new_cap / old_cap))
            self.resource_capacity[resource_id] = new_cap
        self.mode_resource_capacity_adjustments = capacity_adjustments
        # Time spent after leaving a forbidden form counts again, but time
        # inside it never does. Direct forbidden->source transitions restore 0.
        for source_mode in self.mode_definitions.values():
            for modifier in source_mode.entry_resource_modifiers:
                if modifier.kind != 'restore_last_mode_resource':
                    continue
                if previous_id in modifier.forbidden_mode_ids and target_mode_id not in (
                        source_mode.id, *modifier.forbidden_mode_ids):
                    self.last_mode_resource_snapshots.setdefault(source_mode.id, {})[
                        modifier.resource_id] = 0.0
                    self.last_mode_exit_time_s[source_mode.id] = float(self.current_time_s)
                    self.forfeited_mode_resource_ids.discard(modifier.resource_id)
        # Generic source-backed on-entry resource effects, evaluated after
        # ordinary mode rules and before the transition is published.
        # The source may explicitly forbid storing a balance in other forms.
        for modifier in target.entry_resource_modifiers:
            resource_id = str(modifier.resource_id)
            if resource_id not in self.resources or resource_id not in self.resource_capacity:
                raise ValueError(f'mode entry resource unavailable: {resource_id}')
            if (not all(isfinite(float(x)) for x in (modifier.value,modifier.outside_regen_per_s,modifier.max_restored))
                    or float(modifier.value)<0 or float(modifier.outside_regen_per_s)<0
                    or float(modifier.max_restored)<0):
                raise ValueError('mode entry resource modifier has invalid numeric source')
            if modifier.kind == 'restore_last_mode_resource' and float(modifier.value)>1:
                raise ValueError('mode entry retained resource fraction exceeds 100%')
            if modifier.kind == 'expected_flat_gain':
                before, after, gained = self.restore(resource_id, float(modifier.value))
            elif modifier.kind == 'restore_last_mode_resource':
                # Source-specific source-mode identity is the destination mode:
                # store the last balance on exiting that mode.
                stored = float(self.last_mode_resource_snapshots.get(target_mode_id, {}).get(resource_id, 0.0))
                exit_time = self.last_mode_exit_time_s.get(target_mode_id)
                if resource_id in self.forfeited_mode_resource_ids:
                    stored = 0.0
                outside_s = (0.0 if exit_time is None else
                             max(0.0, float(self.current_time_s)-float(exit_time)))
                if resource_id in self.forfeited_mode_resource_ids:
                    outside_s = 0.0
                amount = min(float(modifier.max_restored),
                    stored*float(modifier.value)+outside_s*float(modifier.outside_regen_per_s))
                before, after, gained = self.restore(resource_id, amount)
                self.forfeited_mode_resource_ids.discard(resource_id)
            else:
                raise ValueError(f'unsupported mode entry resource effect: {modifier.kind}')
            resource_changes.append({'phase':'talent_entry','mode_id':target.id,
                'resource_id':resource_id,'behavior':modifier.kind,'before':before,
                'after':after,'gained':gained})
        # Forbidden modes wipe any stored balance for a subsequent entry.
        for mode in self.mode_definitions.values():
            for modifier in mode.entry_resource_modifiers:
                if target_mode_id in modifier.forbidden_mode_ids:
                    self.forfeited_mode_resource_ids.add(str(modifier.resource_id))
        self.current_mode_id = target_mode_id
        return {
            "from_mode_id": previous_id,
            "to_mode_id": target_mode_id,
            "stat_adjustments": dict(adjustments),
            "resource_capacity_adjustments": dict(capacity_adjustments),
            "resource_changes": resource_changes,
            "enabled_action_ids": (None if target.enabled_action_ids is None else list(target.enabled_action_ids)),
        }

    def source_cast_charge_count(self, bank_id: str, *, at_time_s: float | None = None) -> int:
        """Read the same expiring, actor-owned bank across combat and recovery."""
        now=float(self.current_time_s if at_time_s is None else at_time_s)
        state=self.source_cast_charge_banks.get(str(bank_id)) or {}
        return (int(state.get('charges',0)) if
                float(state.get('expires_at_s',0.))>now+1e-12 else 0)

    def grant_source_cast_charges(self, bank_id: str, *, amount: int,
                                  capacity: int, duration_s: float,
                                  at_time_s: float) -> tuple[int,int]:
        if (not bank_id or type(amount) is not int or type(capacity) is not int
                or not 0<amount<=capacity<=16 or not isfinite(duration_s)
                or not 0<float(duration_s)<=120.):
            raise ValueError('INVALID_SOURCE_CAST_CHARGE_GRANT')
        before=self.source_cast_charge_count(bank_id,at_time_s=at_time_s)
        after=min(capacity,before+amount)
        self.source_cast_charge_banks[str(bank_id)]={
            'charges':after,'expires_at_s':float(at_time_s)+float(duration_s)}
        return before,after

    def consume_source_cast_charge(self, bank_id: str, *, at_time_s: float) -> int:
        before=self.source_cast_charge_count(bank_id,at_time_s=at_time_s)
        if before<=0:
            raise ValueError('SOURCE_CAST_CHARGE_SPEND_INCONSISTENT')
        self.source_cast_charge_banks[str(bank_id)]['charges']=before-1
        return before-1

    def ready_time_for(self, action_id: str) -> float:
        return max(
            float(self.current_time_s),
            float(self.gcd_ready_s),
            float(self.cooldown_ready_s.get(str(action_id), 0.0)),
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "stats": dict(self.stats),
            "resources": dict(self.resources),
            "resource_capacity": dict(self.resource_capacity),
            "resource_active": {str(k): bool(v) for k, v in self.resource_active.items()},
            "current_mode_id": self.current_mode_id,
            "mode_stat_adjustments": dict(self.mode_stat_adjustments),
            "mode_resource_capacity_adjustments": dict(self.mode_resource_capacity_adjustments),
            "last_mode_resource_snapshots": {k:dict(v) for k,v in self.last_mode_resource_snapshots.items()},
            "last_mode_exit_time_s": dict(self.last_mode_exit_time_s),
            "forfeited_mode_resource_ids": sorted(self.forfeited_mode_resource_ids),
            "metadata": dict(self.metadata),
            "current_time_s": float(self.current_time_s),
            "gcd_ready_s": float(self.gcd_ready_s),
            "cooldown_ready_s": {str(k): float(v) for k, v in self.cooldown_ready_s.items()},
            "source_cast_charge_banks": {str(k):dict(v) for k,v in self.source_cast_charge_banks.items()},
            "source_timed_spell_crit_haste_until_s": float(self.source_timed_spell_crit_haste_until_s),
            "source_next_cast_instant_charges": dict(self.source_next_cast_instant_charges),
            "active_auras": {str(k): v.as_dict() for k, v in self.active_auras.items()},
        }


@dataclass(frozen=True)
class AuraState:
    id: str
    source_action_id: str
    generation: int
    applied_at_s: float
    expires_at_s: float
    refresh_rule: str
    exclusive_group: str | None = None

    def as_dict(self) -> dict[str, object]:
        result = {
            "id": self.id,
            "source_action_id": self.source_action_id,
            "generation": int(self.generation),
            "applied_at_s": float(self.applied_at_s),
            "expires_at_s": float(self.expires_at_s),
            "refresh_rule": self.refresh_rule,
        }
        if self.exclusive_group is not None:
            result["exclusive_group"] = self.exclusive_group
        return result


@dataclass
class TargetState:
    id: str
    health: float
    max_health: float
    alive: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)
    resource_capacity: dict[str, float] = field(default_factory=dict)
    resource_active: dict[str, bool] = field(default_factory=dict)
    active_auras: dict[str, AuraState] = field(default_factory=dict)
    aura_generations: dict[str, int] = field(default_factory=dict)
    # Pending actor-scoped periodic effects survive an encounter boundary.
    # These are runtime events + the original source Action IR, never inferred
    # from aura names or reconstructed from tooltip guesses.
    pending_actor_periodic_events: tuple[Any, ...] = ()
    pending_actor_periodic_actions: dict[str, Any] = field(default_factory=dict)
    active_controls: dict[str, float] = field(default_factory=dict)
    active_stat_modifiers: dict[str, tuple[str, float, int]] = field(default_factory=dict)
    active_school_power: dict[str, tuple[str, float, int]] = field(default_factory=dict)

    def effective_stat(self, stat_id: str) -> float:
        if stat_id not in self.metadata:
            raise ValueError(f'target stat {stat_id!r} has no sourced scenario value')
        baseline = float(self.metadata[stat_id])
        if not isfinite(baseline) or baseline < 0:
            raise ValueError('invalid sourced target stat')
        return max(0.0, baseline + sum(
            float(delta) for target_id, delta, _ in self.active_stat_modifiers.values()
            if target_id == stat_id))


    @classmethod
    def with_health(cls, target_id: str, health: float, **metadata: object) -> "TargetState":
        hp = max(0.0, float(health))
        return cls(id=str(target_id), health=hp, max_health=hp, alive=hp > 0.0, metadata=dict(metadata))

    def bind_resource_definitions(self, resources: tuple[ResourceDefinition, ...]) -> None:
        for resource in resources:
            if str(resource.scope or "actor") != "target":
                continue
            rid = str(resource.id)
            if rid not in self.resources and resource.initial_amount is not None:
                self.resources[rid] = float(resource.initial_amount)
            if resource.capacity is not None:
                self.resource_capacity[rid] = float(resource.capacity)
            self.resource_active[rid] = bool(resource.active_by_default)

    def resource_amount(self, resource_id: str) -> float | None:
        value = self.resources.get(str(resource_id))
        return None if value is None else float(value)

    def can_spend(self, resource_id: str, amount: float) -> bool:
        rid = str(resource_id)
        current = self.resource_amount(rid)
        return bool(self.resource_active.get(rid, False)) and current is not None and current + 1e-12 >= max(0.0, float(amount))

    def spend(self, resource_id: str, amount: float) -> tuple[float, float]:
        rid = str(resource_id)
        cost = max(0.0, float(amount))
        current = self.resource_amount(rid)
        if current is None:
            raise ValueError(f"resource {rid!r} is not present in target state")
        if current + 1e-12 < cost:
            raise ValueError(f"insufficient {rid}: have {current}, need {cost}")
        after = max(0.0, current - cost)
        self.resources[rid] = after
        return float(current), float(after)

    def change_resource(self, resource_id: str, *, operation: str, amount: float = 0.0) -> tuple[float, float]:
        rid = str(resource_id)
        current = self.resource_amount(rid)
        if current is None:
            raise ValueError(f"resource {rid!r} is not present in target state")
        op = str(operation)
        if op == "add":
            after = float(current) + float(amount)
        elif op == "set":
            after = float(amount)
        else:
            raise ValueError(f"unsupported resource change operation: {op}")
        cap = self.resource_capacity.get(rid)
        if cap is not None:
            after = min(float(cap), after)
        after = max(0.0, float(after))
        self.resources[rid] = after
        return float(current), float(after)

    def apply_damage(self, amount: float) -> float:
        dealt = max(0.0, float(amount))
        self.health = max(0.0, self.health - dealt)
        self.alive = self.health > 0.0
        return dealt

    def apply_aura(
        self, *, aura_id: str, source_action_id: str, applied_at_s: float,
        duration_s: float, refresh_rule: str, exclusive_group: str | None = None,
    ) -> tuple[AuraState | None, AuraState]:
        aura_id = str(aura_id)
        if refresh_rule != "replace":
            raise ValueError(f"unsupported aura refresh rule: {refresh_rule}")
        previous = self.active_auras.get(aura_id)
        generation = int(self.aura_generations.get(aura_id, 0)) + 1
        self.aura_generations[aura_id] = generation
        aura = AuraState(
            id=aura_id,
            source_action_id=str(source_action_id),
            generation=generation,
            applied_at_s=float(applied_at_s),
            expires_at_s=float(applied_at_s) + max(0.0, float(duration_s)),
            refresh_rule=str(refresh_rule),
            exclusive_group=exclusive_group,
        )
        self.active_auras[aura_id] = aura
        return previous, aura

    def remove_aura(self, aura_id: str, generation: int | None = None) -> AuraState | None:
        current = self.active_auras.get(str(aura_id))
        if current is None:
            return None
        if generation is not None and int(current.generation) != int(generation):
            return None
        return self.active_auras.pop(str(aura_id), None)

    def clear_auras(self) -> None:
        self.active_auras.clear()

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "health": float(self.health),
            "max_health": float(self.max_health),
            "alive": bool(self.alive),
            "metadata": dict(self.metadata),
            "resources": {str(k): float(v) for k, v in self.resources.items()},
            "resource_capacity": {str(k): float(v) for k, v in self.resource_capacity.items()},
            "active_auras": {str(k): v.as_dict() for k, v in self.active_auras.items()},
        }

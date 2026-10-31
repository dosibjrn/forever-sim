from __future__ import annotations

"""Backend-neutral application of selected gear to executable Game IR state.

G20 keeps item legality/source selection outside the runtime.  This module only
knows reusable stat semantics: add executable gear stats to the Actor and
recompute resources whose capacity is derived from those stats.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import math
import re
from typing import Any, Mapping, Sequence

from src.game.data.forever.player_state import classic_mana_bonus_from_intellect
from src.game.data.forever.primary_stat_conversions import converted_stat_amount
from src.game.model.ir import GameIRSlice, ModeStatModifier, ModeResourceCapacityModifier, WeaponDamageEffect
from src.game.data.forever.stat_conversions import (load_mode_stat_conversions,
    load_mode_resource_capacity_conversions)
from src.game.data.forever.equipped_weapon_modes import load_equipped_weapon_mode_facts


EXECUTABLE_CASTER_GEAR_STATS = ("spell_power", "intellect", "spirit", "mp5")
# The shared combat executor already reads agility (mode AP modifiers) and
# attack_power (weapon/auto-attack damage). Keep the legacy caster envelope
# unchanged while allowing the joint search to evaluate sourced melee gear.
EXECUTABLE_GEAR_STATS = EXECUTABLE_CASTER_GEAR_STATS + ("agility", "attack_power", "armor")


def _mode_label(label: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(label).lower()).strip('_')


def _weapon_facts_for_ir(ir_slice: GameIRSlice, *, db_path: Path | None = None):
    class_key = str(ir_slice.actor.metadata.get('class_key', '')).lower()
    if not class_key:
        return ()
    labels = {_mode_label(m.label): m.id for m in ir_slice.modes}
    return tuple((fact, labels[_mode_label(fact.mode_label)] if fact.mode_label != '*' else None)
                 for fact in load_equipped_weapon_mode_facts(class_key, db_path=db_path)
                 if fact.mode_label == '*' or _mode_label(fact.mode_label) in labels)


def _replace_equipped_weapon_dps(ir_slice: GameIRSlice, dps: float, *,
                                 selected_items: Sequence[Mapping[str, Any]] = (),
                                 db_path: Path | None = None) -> GameIRSlice:
    """Replace the *existing weapon anchor*, never add a second weapon's DPS.

    Source mode+damage-source identity is required for both auto attacks and
    weapon-damage actions. Non-weapon effects and unapproved modes are untouched.
    """
    if not math.isfinite(dps) or dps <= 0:
        raise ValueError('equipped weapon DPS must be a finite positive absolute value')
    facts = _weapon_facts_for_ir(ir_slice, db_path=db_path)
    if not facts:
        raise ValueError('no source-authorized equipped weapon DPS modes')
    auto_attacks = list(ir_slice.auto_attacks)
    actions = list(ir_slice.actions)
    applied = []
    for fact, mode_id in facts:
        # A Hunter may equip a melee weapon AND a ranged weapon. Their DPS
        # values must never be summed for either attack source. Source mode
        # facts choose the relevant named equipment slot, not class branches.
        selected=tuple(selected_items)
        if selected:
            matching=[item for item in selected if str(item.get('slot')) == fact.source_item_slot]
            if len(matching)!=1 or float(matching[0].get('weapon_dps') or 0.)<=0:
                raise ValueError(f'missing named equipped weapon for source slot {fact.source_item_slot!r}')
            source_dps=float(matching[0]['weapon_dps'])
        else:
            source_dps=dps  # Explicit synthetic stat-probe, no named equipment.
        source_speed = None
        if selected and fact.weapon_speed_semantics == 'equipped':
            source_speed = float(matching[0].get('weapon_speed') or 0.)
            if not math.isfinite(source_speed) or source_speed <= 0.:
                raise ValueError('named equipped weapon lacks sourced positive speed')
        provenance = {'stage': 'equipped_weapon_dps_replacement', 'mode_id': mode_id,
                      'source_stat': fact.source_stat, 'source_url': fact.source_url,
                      'authority': fact.authority, 'source_date': fact.source_date,
                      'capture_id': fact.capture_id, 'new_dps': float(source_dps),
                      'source_item_slot':fact.source_item_slot}
        count = 0
        for i, attack in enumerate(auto_attacks):
            if (attack.required_mode_id == mode_id
                    and attack.damage_source.kind == fact.damage_source_kind):
                auto_attacks[i] = replace(attack,
                    damage_source=replace(attack.damage_source, flat_dps=source_dps, dps_stat_id=None),
                    swing_time_s=source_speed if source_speed is not None else attack.swing_time_s,
                    provenance=attack.provenance + (provenance,))
                count += 1
        for i, action in enumerate(actions):
            if not any(req.get('kind') == 'mode_is' and req.get('value') == mode_id
                       for req in action.requirements):
                continue
            effects = []
            changed = False
            for effect in action.effects:
                if (isinstance(effect, WeaponDamageEffect)
                        and effect.damage_source.kind == fact.damage_source_kind):
                    effects.append(replace(effect,
                        damage_source=replace(effect.damage_source, flat_dps=source_dps, dps_stat_id=None),
                        weapon_damage_time_s=source_speed if source_speed is not None else effect.weapon_damage_time_s,
                        provenance=effect.provenance + (provenance,)))
                    changed = True
                    count += 1
                else:
                    effects.append(effect)
            if changed:
                actions[i] = replace(action, effects=tuple(effects),
                                     provenance=action.provenance + (provenance,))
        if not count:
            raise ValueError(f'authorized weapon mode has no executable damage source: {mode_id}')
        applied.append({**provenance, 'rewritten_sources': count})
    return replace(ir_slice, auto_attacks=tuple(auto_attacks), actions=tuple(actions),
                   provenance={**dict(ir_slice.provenance), 'equipped_weapon_dps_application': applied})


def _equipped_stat_dps_sources(ir_slice: GameIRSlice) -> dict[str, str]:
    """Generic named-slot DPS anchors for auto attacks without weapon-mode facts.

    A stat ``wand_dps`` is anchored to the named ``wand`` slot. Unlike a
    synthetic stat sensitivity probe, a named weapon replaces the scenario
    proxy's DPS; it must never be added to the proxy a second time.
    """
    sources = {}
    for attack in ir_slice.auto_attacks:
        stat = attack.damage_source.dps_stat_id
        if not stat or not stat.endswith('_dps') or stat == 'weapon_dps':
            continue
        slot = stat[:-4]
        sources[stat] = slot
    return sources


def _replace_named_stat_dps(ir_slice: GameIRSlice, stat_delta: Mapping[str, float],
                            selected_items: Sequence[Mapping[str, Any]]) -> GameIRSlice:
    """Replace source-named auto attack DPS anchors, preserving provenance."""
    sources = _equipped_stat_dps_sources(ir_slice)
    actor_stats = dict(ir_slice.actor.base_stats)
    attacks = list(ir_slice.auto_attacks)
    records = []
    for stat, slot in sources.items():
        if not float(stat_delta.get(stat, 0.) or 0.):
            continue
        matches = tuple(item for item in selected_items if str(item.get('slot')) == slot)
        if len(matches) != 1:
            raise ValueError(f'named equipped stat DPS requires exactly one {slot} item')
        item = matches[0]
        dps = float(item.get('weapon_dps') or 0.)
        speed = float(item.get('weapon_speed') or 0.)
        if not math.isfinite(dps) or dps <= 0. or not math.isfinite(speed) or speed <= 0.:
            raise ValueError(f'named equipped stat DPS requires positive {slot} DPS and speed')
        if abs(dps - float(stat_delta[stat])) > 1e-8:
            raise ValueError(f'named equipped stat DPS aggregate disagrees with {slot} item')
        actor_stats[stat] = dps
        for idx, attack in enumerate(attacks):
            if attack.damage_source.dps_stat_id == stat:
                attacks[idx] = replace(attack, swing_time_s=speed)
        records.append({'stat':stat,'slot':slot,'item_id':int(item['item_id']),
                        'dps':dps,'swing_time_s':speed,
                        'method':'replace_qualified_scenario_dps_with_named_source_item'})
    if not records:
        return ir_slice
    return replace(ir_slice, actor=replace(ir_slice.actor,base_stats=actor_stats),
                   auto_attacks=tuple(attacks),
                   provenance={**dict(ir_slice.provenance),
                               'equipped_stat_dps_replacement':records})


def executable_gear_stats(ir_slice: GameIRSlice, *, db_path: Path | None = None) -> tuple[str, ...]:
    """Return executable axes from generic primitives and canonical source rows."""
    class_key = str(ir_slice.actor.metadata.get('class_key', '')).lower()
    stat_rows = load_mode_stat_conversions(class_key, db_path=db_path) if class_key else ()
    capacity_rows = load_mode_resource_capacity_conversions(class_key, db_path=db_path) if class_key else ()
    labels = {_mode_label(mode.label) for mode in ir_slice.modes}
    resources = {resource.id for resource in ir_slice.resources}
    actor_axes = {str(row['source_stat']) for row in
                  ir_slice.actor.metadata.get('canonical_primary_stat_conversions', ())}
    source_axes = sorted(
        {row.source_stat for row in stat_rows if row.mode_label in labels}
        | {row.source_stat for row in capacity_rows
           if row.mode_label in labels and row.target_stat in resources})
    weapon_axes = {fact.source_stat for fact, mode_id in _weapon_facts_for_ir(ir_slice, db_path=db_path)
                   if any(a.required_mode_id == mode_id and a.damage_source.kind == fact.damage_source_kind
                          for a in ir_slice.auto_attacks)}
    auto_dps_axes = tuple(sorted(_equipped_stat_dps_sources(ir_slice)))
    hp5_axis = ('health_regeneration_per_5s',) if 'health' in resources else ()
    return tuple(dict.fromkeys((*EXECUTABLE_GEAR_STATS, *hp5_axis, *auto_dps_axes, *source_axes,
                                *sorted(actor_axes), *sorted(weapon_axes))))



@dataclass(frozen=True)
class GearApplication:
    aggregate_stats: Mapping[str, float]
    applied_stats: Mapping[str, float]
    unsupported_stats: Mapping[str, float]
    selected_items: tuple[Mapping[str, Any], ...] = ()
    provenance: Mapping[str, Any] | None = None
    partial_stats: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "aggregate_stats": {str(k): float(v) for k, v in self.aggregate_stats.items()},
            "applied_stats": {str(k): float(v) for k, v in self.applied_stats.items()},
            "unsupported_stats": {str(k): float(v) for k, v in self.unsupported_stats.items()},
            "partial_stats": dict(self.partial_stats or {}),
            "selected_items": [dict(x) for x in self.selected_items],
            "provenance": dict(self.provenance or {}),
        }


def _primary_resource_capacity_marginal(row, stat_delta, actor_stats, missing_base):
    """Apply a sourced *gear marginal*, never a fabricated naked primary stat.

    An absent base stat is allowed only when the IR explicitly records a
    qualified lower-bound assumption for this delta-only conversion.
    """
    delta = float(stat_delta.get(row['source_stat'], 0.0) or 0.0)
    if row['source_stat'] in missing_base:
        base = float(missing_base[row['source_stat']]['assumed_at_least'])
    else:
        base = float(actor_stats[row['source_stat']]) - delta
    return (converted_stat_amount(row, base + delta)
            - converted_stat_amount(row, base))


def _apply_executable_stats(
    ir_slice: GameIRSlice,
    stat_delta: Mapping[str, float],
    *,
    provenance: Mapping[str, Any],
    db_path: Path | None = None,
    selected_items: Sequence[Mapping[str, Any]] = (),
) -> GameIRSlice:
    stats = {str(k): float(v) for k, v in dict(ir_slice.actor.base_stats).items()}
    available = executable_gear_stats(ir_slice, db_path=db_path)
    named_stat_dps = _equipped_stat_dps_sources(ir_slice) if selected_items else {}
    missing_base = dict(ir_slice.actor.metadata.get('canonical_missing_base_stat_proxies') or {})
    for stat in available:
        delta = float(stat_delta.get(stat, 0.0) or 0.0)
        if delta and stat != 'weapon_dps' and stat not in named_stat_dps and stat not in missing_base:
            stats[stat] = float(stats.get(stat, 0.0)) + delta

    # Canonical primary stat deltas affect the real combat table, not merely
    # the gear selection weights. Baseline stat contributions were compiled
    # into the naked Actor by the generic source registry.
    primary_facts = tuple(ir_slice.actor.metadata.get('canonical_primary_stat_conversions') or ())
    for row in primary_facts:
        if row['target_type'] != 'stat':
            continue
        delta = float(stat_delta.get(row['source_stat'], 0.0) or 0.0)
        if delta:
            target = str(row['target_id'])
            stats[target] = float(stats.get(target, 0.0)) + delta * float(row['coefficient'])

    # Source-compiled actor Armor is 2*total Agility plus armor from equipped
    # items. Recompute exactly once from canonical coefficients after each gear
    # delta; mode-specific additional item Armor is applied only on mode entry.
    armor_sources = tuple(ir_slice.actor.metadata.get('canonical_armor_source_rules') or ())
    if armor_sources:
        item_delta = float(stat_delta.get('armor', 0.0) or 0.0)
        if '__equipped_armor_source_stat' in ir_slice.actor.metadata:
            key = str(ir_slice.actor.metadata['__equipped_armor_source_stat'])
            stats[key] = float(stats.get(key, 0.0)) + item_delta
        elif item_delta:
            raise ValueError('equipped armor source is not represented')
        stats['armor'] = sum(float(stats[row['source_stat']])*float(row['coefficient'])
                             for row in armor_sources) + float(stats.get('__equipped_item_armor',0.0))

    class_key = str(ir_slice.actor.metadata.get('class_key', '')).lower()
    conversions = load_mode_stat_conversions(class_key, db_path=db_path) if class_key else ()
    capacity_conversions = load_mode_resource_capacity_conversions(class_key, db_path=db_path) if class_key else ()
    mode_map = {_mode_label(mode.label): idx for idx, mode in enumerate(ir_slice.modes)}
    modes = list(ir_slice.modes)
    for row in conversions:
        # A global Strength -> AP conversion already includes gear Strength.
        # Keep this mode row in SQLite: it is independently needed for
        # mode-specific *talent* scaling (e.g. increased Strength in Cat).
        if any(f['target_type'] == 'stat' and f['source_stat'] == row.source_stat
               and f['target_id'] == row.target_stat for f in primary_facts):
            continue
        delta = float(stat_delta.get(row.source_stat, 0.0) or 0.0)
        if not delta:
            continue
        idx = mode_map.get(row.mode_label)
        if idx is None:
            raise ValueError(f'source stat conversion mode unavailable: {row.mode_label}')
        mode = modes[idx]
        modes[idx] = replace(mode, stat_modifiers=mode.stat_modifiers + (
            ModeStatModifier(target_stat=row.target_stat, kind='add_flat',
                             value=delta * row.coefficient),),
            provenance=mode.provenance + ({
                'stage': 'gear_stat_conversion', 'source_stat': row.source_stat,
                'target_stat': row.target_stat, 'coefficient': row.coefficient,
                'source_url': row.source_url, 'authority': row.authority,
                'capture_id': row.capture_id},))

    # A sourced mode-specific capacity conversion must use the *gear delta*.
    # Using total Stamina would count naked/base Stamina a second time against
    # the existing source starting-health proxy. The internal stat is generic
    # bookkeeping and is not a new game-specific stat or conversion constant.
    for stat in {row.source_stat for row in capacity_conversions}:
        delta = float(stat_delta.get(stat, 0.0) or 0.0)
        if delta:
            internal_stat = f'__gear_delta__{stat}'
            stats[internal_stat] = float(stats.get(internal_stat, 0.0)) + delta
    for row in capacity_conversions:
        # Health gear delta is global. The mode-specific source row remains
        # available to the talent parser but must not add the same HP twice.
        if any(f['target_type'] == 'resource_capacity' and f['source_stat'] == row.source_stat
               and f['target_id'] == row.target_stat for f in primary_facts):
            continue
        delta = float(stat_delta.get(row.source_stat, 0.0) or 0.0)
        if not delta:
            continue
        idx = mode_map.get(row.mode_label)
        if idx is None:
            raise ValueError(f'source resource conversion mode unavailable: {row.mode_label}')
        if row.target_stat not in {resource.id for resource in ir_slice.resources}:
            raise ValueError(f'source resource conversion target unavailable: {row.target_stat}')
        internal_stat = f'__gear_delta__{row.source_stat}'
        mode = modes[idx]
        prior = [m for m in mode.resource_capacity_modifiers
                 if m.resource_id == row.target_stat and m.source_stat == internal_stat]
        if prior:
            if len(prior) != 1 or prior[0].kind != 'add_stat_scaled' or abs(prior[0].value - row.coefficient) > 1e-12:
                raise ValueError('conflicting sourced gear resource conversion on repeated application')
            continue
        modes[idx] = replace(mode, resource_capacity_modifiers=mode.resource_capacity_modifiers + (
            ModeResourceCapacityModifier(resource_id=row.target_stat, kind='add_stat_scaled',
                                         source_stat=internal_stat, value=row.coefficient),),
            provenance=mode.provenance + ({
                'stage': 'gear_resource_capacity_conversion', 'source_stat': row.source_stat,
                'target_resource': row.target_stat, 'coefficient': row.coefficient,
                'source_url': row.source_url, 'authority': row.authority,
                'capture_id': row.capture_id},))

    if selected_items:
        shields=[item for item in selected_items if str(item.get('slot'))=='offhand'
                 and str(item.get('armor_type'))=='shield']
        if len(shields)>1:raise ValueError('more than one equipped shield')
        stats['equipped_shield']=1.0 if shields else 0.0
    actor = replace(
        ir_slice.actor,
        base_stats=stats,
        metadata={
            **dict(ir_slice.actor.metadata),
            "gear_included": True,
            "gear_executable_stats": {
                stat: float(stat_delta.get(stat, 0.0) or 0.0)
                for stat in available
                if float(stat_delta.get(stat, 0.0) or 0.0) != 0.0
            },
        },
        provenance=tuple(ir_slice.actor.provenance) + (dict(provenance),),
    )

    resources = []
    for resource in ir_slice.resources:
        # Health's unverified naked baseline stays a qualified proxy. Gear
        # Stamina contributes its *increment* to capacity and initial HP.
        capacity_delta = 0.0
        for row in primary_facts:
            if row['target_type'] != 'resource_capacity' or row['target_id'] != resource.id:
                continue
            capacity_delta += _primary_resource_capacity_marginal(
                row, stat_delta, stats, missing_base)
        if capacity_delta:
            if resource.capacity is None or resource.initial_amount is None:
                raise ValueError('canonical primary stat resource lacks starting capacity')
            capacity = float(resource.capacity) + capacity_delta
            initial = float(resource.initial_amount) + capacity_delta
            if capacity <= 0 or initial < 0 or initial > capacity:
                raise ValueError('primary stat conversion would invalidate resource capacity')
            resource = replace(resource, capacity=capacity, initial_amount=initial,
                metadata={**dict(resource.metadata), 'gear_primary_stat_capacity_delta': capacity_delta,
                          'baseline_status': 'qualified_proxy_plus_sourced_gear_delta',
                          'unknown_naked_primary_stat_assumptions': missing_base},
                provenance=resource.provenance + (dict(provenance),))
        if resource.id != "mana":
            resources.append(resource)
            continue
        base_mana = resource.metadata.get("base_mana")
        if base_mana is None:
            resources.append(resource)
            continue
        total_intellect = float(stats.get("intellect", 0.0))
        capacity = float(base_mana) + classic_mana_bonus_from_intellect(total_intellect)
        resources.append(replace(
            resource,
            initial_amount=capacity,
            capacity=capacity,
            metadata={
                **dict(resource.metadata),
                "base_intellect": total_intellect,
                "intellect_mana_bonus": classic_mana_bonus_from_intellect(total_intellect),
                "gear_included": True,
                "capacity_formula": "base_mana + classic_mana_bonus_from_intellect(total_intellect)",
            },
            provenance=tuple(resource.provenance) + (dict(provenance),),
        ))

    applied = replace(
        ir_slice,
        actor=actor,
        modes=tuple(modes),
        resources=tuple(resources),
        provenance={
            **dict(ir_slice.provenance),
            "gear_application": dict(provenance),
        },
    )
    if float(stat_delta.get('weapon_dps', 0.0) or 0.0) != 0.0:
        applied = _replace_equipped_weapon_dps(applied, float(stat_delta['weapon_dps']),
            selected_items=selected_items, db_path=db_path)
    if provenance.get('source') != 'generic_stat_sensitivity_probe':
        applied = _replace_named_stat_dps(applied, stat_delta, selected_items)
    return applied


def apply_gear_selection(
    ir_slice: GameIRSlice,
    *,
    aggregate_stats: Mapping[str, float],
    selected_items: Sequence[Mapping[str, Any]] = (),
    source: str = "canonical_named_gear",
    db_path: Path | None = None,
) -> tuple[GameIRSlice, GearApplication]:
    aggregate = {str(k): float(v or 0.0) for k, v in dict(aggregate_stats).items()}
    if any(not math.isfinite(value) for value in aggregate.values()):
        raise ValueError('gear stats must be finite')
    available = executable_gear_stats(ir_slice, db_path=db_path)
    applied = {
        stat: float(aggregate.get(stat, 0.0))
        for stat in available
        if float(aggregate.get(stat, 0.0)) != 0.0
    }
    unsupported = {
        str(k): float(v)
        for k, v in aggregate.items()
        if str(k) not in available and float(v) != 0.0
    }
    class_key = str(ir_slice.actor.metadata.get('class_key', '')).lower()
    capacity_rows = load_mode_resource_capacity_conversions(class_key, db_path=db_path) if class_key else ()
    partial = {stat: {'coverage': 'source_mode_only', 'modes': sorted({row.mode_label
        for row in capacity_rows if row.source_stat == stat})}
        for stat in applied if any(row.source_stat == stat for row in capacity_rows)}
    provenance = {
        "source": str(source),
        "item_count": len(tuple(selected_items)),
        "applied_stats": dict(applied),
        "unsupported_stats_retained_as_facts": dict(unsupported),
        "partial_stats": partial,
    }
    applied_ir = _apply_executable_stats(ir_slice, applied, provenance=provenance,
                                        selected_items=selected_items, db_path=db_path)
    return applied_ir, GearApplication(
        aggregate_stats=aggregate,
        applied_stats=applied,
        unsupported_stats=unsupported,
        selected_items=tuple(dict(x) for x in selected_items),
        provenance=provenance,
        partial_stats=partial,
    )


def apply_stat_delta(ir_slice: GameIRSlice, stat: str, delta: float, *, db_path: Path | None = None) -> GameIRSlice:
    stat = str(stat)
    if stat not in executable_gear_stats(ir_slice, db_path=db_path):
        raise ValueError(f"stat {stat!r} has no executable generic gear semantic")
    if stat == 'weapon_dps':
        raise ValueError('weapon_dps is an absolute equipped-weapon replacement, not an additive stat delta')
    return _apply_executable_stats(
        ir_slice,
        {stat: float(delta)},
        provenance={"source": "generic_stat_sensitivity_probe", "stat": stat, "delta": float(delta)},
        db_path=db_path,
    )

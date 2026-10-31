from __future__ import annotations

"""Backend-neutral talent legality and immutable Game IR modifier application."""

from dataclasses import dataclass, replace
from typing import Mapping

from src.game.model.ir import (ActionDefinition, GameIRSlice, ResourceCost, ResourceEventGainRule, TalentDefinition,
                               PeriodicEffect, PeriodicHealEffect, HealEffect, ResourceScaledPeriodicEffect, ModeChangeEffect, ResourceScaledDirectDamageEffect, DamageEffect, WeaponDamageEffect,
                               ModeStatModifier, ModeResourceCapacityModifier, ModeEntryResourceModifier, ControlEffect)


@dataclass(frozen=True)
class TalentApplication:
    selection: Mapping[str, int]
    available_points: int
    spent_points: int
    applied_modifiers: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {
            "selection": {str(k): int(v) for k, v in self.selection.items()},
            "available_points": int(self.available_points),
            "spent_points": int(self.spent_points),
            "applied_modifiers": [dict(x) for x in self.applied_modifiers],
        }


def available_talent_points(level: int, *, bonus_talent_points: int = 0) -> int:
    """Base leveling points plus optional explicitly earned legacy points.

    The default is always the standard ruleset. This is a scenario axis,
    not a class constant and not a claim about the account's entitlements.
    """
    if type(bonus_talent_points) is not int or bonus_talent_points < 0:
        raise ValueError('bonus_talent_points must be a nonnegative integer')
    return min(51, max(0, int(level) - 9) + bonus_talent_points)


def talented_bonus_for_level(level: int, *, enabled: bool = True) -> int:
    """Legacy Talented 5/5: gain points starting L5, capped at 51 total.

    Explicit ruleset/scenario switch, NOT five free points after the cap.
    Returns extra points at this level relative to ordinary L10 starts.
    """
    if type(enabled) is not bool:
        raise ValueError('talented_enabled must be boolean')
    level = int(level)
    if not enabled:
        return 0
    return min(5, max(0, level - 4), max(0, 51 - max(0, level - 9)))


def talented_point_budget(level: int, *, enabled: bool = True) -> int:
    return available_talent_points(level,
        bonus_talent_points=talented_bonus_for_level(level,enabled=enabled))


def _definition_map(ir_slice: GameIRSlice) -> dict[str, TalentDefinition]:
    return {talent.id: talent for talent in ir_slice.talents}


def validate_talent_selection(ir_slice: GameIRSlice, selection: Mapping[str, int], *, level: int, bonus_talent_points: int = 0) -> None:
    definitions = _definition_map(ir_slice)
    normalized = {str(k): int(v) for k, v in selection.items() if int(v) != 0}
    unknown = sorted(set(normalized) - set(definitions))
    if unknown:
        raise ValueError(f"unknown talent selection: {', '.join(unknown)}")
    for talent_id, rank in normalized.items():
        talent = definitions[talent_id]
        if rank < 0 or rank > int(talent.max_rank):
            raise ValueError(f"illegal rank for {talent_id}: {rank}/{talent.max_rank}")
        rank_row = next((row for row in talent.ranks if int(row.rank) == rank), None)
        if rank_row is None:
            raise ValueError(f"rank {rank} for {talent_id} has no canonical rank record")
        if not rank_row.modifiers:
            raise ValueError(f"unsupported talent effect for {talent_id} rank {rank}; refusing no-op selection")
        prerequisite = talent.prerequisite
        if prerequisite:
            required_id = str(prerequisite.get("talent_id") or "")
            required_rank = prerequisite.get("required_rank")
            if not required_id or required_rank is None:
                raise ValueError(f"canonical prerequisite rank unresolved for {talent_id}")
            if int(normalized.get(required_id, 0)) < int(required_rank):
                raise ValueError(f"prerequisite not met for {talent_id}: {required_id} rank {required_rank}")
    # Row gates are structural: 5 points in *earlier rows of the same tree*
    # for each zero-indexed row. Points in the current row, other trees, or
    # talents with unresolved row coordinates cannot unlock a later row.
    # All positions originate in canonical SQLite, not a class-specific map.
    rule = ir_slice.provenance.get('talent_tree_rules') or {}
    for talent_id, rank in normalized.items():
        talent = definitions[talent_id]
        row = talent.metadata.get('row')
        if row is None:
            continue  # provisional candidate only; source coverage remains BLOCKED
        row = int(row)
        if row < 0:
            raise ValueError(f'invalid canonical talent row for {talent_id}: {row}')
        if row and 'points_per_row' not in rule:
            raise ValueError(f'canonical talent tree tier rule missing for {talent_id}')
        points_per_row = int(rule.get('points_per_row', 0))
        if row and points_per_row <= 0:
            raise ValueError(f'invalid canonical talent tree tier rule for {talent_id}')
        earlier = sum(other_rank for other_id, other_rank in normalized.items()
                      if definitions[other_id].tree_key == talent.tree_key
                      and definitions[other_id].metadata.get('row') is not None
                      and int(definitions[other_id].metadata['row']) < row)
        if earlier < row * points_per_row:
            raise ValueError(f'talent tree tier gate not met for {talent_id}: '
                             f'{earlier} earlier-row points < {row * points_per_row}')
    spent = sum(normalized.values())
    available = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    if spent > available:
        raise ValueError(f"talent points exceed level budget: {spent}>{available} at level {int(level)}")


def explicit_seed_selection(ir_slice: GameIRSlice, *, level: int, bonus_talent_points: int = 0) -> dict[str, int]:
    """Choose the first legal executable rank seed from the canonical roster.

    This is only a deterministic mechanics probe, not talent optimization.
    A source-sorted family can occupy a locked tree tier; never let that
    abort the whole generic backend when another source family is legal.
    """
    budget = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    for talent in ir_slice.talents:
        for rank in range(min(int(talent.max_rank), budget), 0, -1):
            selection = {talent.id: rank}
            try:
                validate_talent_selection(ir_slice, selection, level=level, bonus_talent_points=bonus_talent_points)
            except ValueError:
                continue
            return selection
    return {}


def _compile_avoidance_resource_rule(modifier, *, talent_id: str, rank: int,
                                     resource_id: str, modes) -> ResourceEventGainRule:
    """Compile one source-valued expected avoidance proc, independent of class."""
    fact = modifier.provenance
    source_url = str(fact.get('url') or '')
    source_build = str(fact.get('source_build') or '')
    gain = fact.get('gain_amount')
    chance = float(modifier.value)
    if (not source_url.startswith('https://') or not source_build
            or not isinstance(gain, (int,float)) or isinstance(gain,bool)
            or not 0. < float(gain) or not 0. <= chance <= 1.):
        raise ValueError('AVOIDANCE_PROC_SOURCE_FACTS_REQUIRED')
    mode_id = fact.get('required_mode_id')
    if mode_id is not None and str(mode_id) not in {m.id for m in modes}:
        raise ValueError('AVOIDANCE_PROC_MODE_NOT_IN_GAME_IR')
    return ResourceEventGainRule(
        id=f'talent:{talent_id}:rank{rank}:avoidance:{resource_id}',
        event_kind='incoming_dodge', event_value_field='dodge_probability',
        multiplier=chance*float(gain),
        required_mode_id=None if mode_id is None else str(mode_id),
        provenance=(dict(fact),), metadata={
            'resolution':'expected_value_dodge_proc',
            'source_build_verified':fact.get('source_build_verified'),
            'proc_distribution_verified':fact.get('proc_distribution_verified'),
        })


def apply_talent_selection(ir_slice: GameIRSlice, selection: Mapping[str, int], *, level: int, bonus_talent_points: int = 0) -> tuple[GameIRSlice, TalentApplication]:
    validate_talent_selection(ir_slice, selection, level=level, bonus_talent_points=bonus_talent_points)
    definitions = _definition_map(ir_slice)
    normalized = {str(k): int(v) for k, v in selection.items() if int(v) > 0}
    gated_families = {}
    for gated_talent in ir_slice.talents:
        for gated_rank in gated_talent.ranks:
            for gate in gated_rank.modifiers:
                if gate.kind == 'unlock_action_family':
                    if gate.target_type != 'action_family':
                        raise ValueError('UNLOCK_REQUIRES_ACTION_FAMILY')
                    prev = gated_families.setdefault(gate.target_id, gated_talent.id)
                    if prev != gated_talent.id:
                        raise ValueError('CONFLICTING_TALENT_UNLOCK_FAMILY')
    actions = list(ir_slice.actions)
    auto_attacks = list(ir_slice.auto_attacks)
    triggers = list(ir_slice.triggers)
    modes = list(ir_slice.modes)
    actor = ir_slice.actor
    resources = list(ir_slice.resources)
    applied: list[dict] = []
    unsupported = list(ir_slice.unsupported_semantics)

    # Grant sourced actions first, then apply all passive modifiers so a
    # trigger-filter talent cannot miss a newly granted event trigger.
    ordered = sorted(normalized.items(), key=lambda item: (not any(
        mod.kind in ('grant_source_action','grant_source_resource_action','grant_source_next_cast_instant_action','grant_source_active_periodic_full_heal','grant_source_spatial_charge_actions') for rr in definitions[item[0]].ranks
        if rr.rank == item[1] for mod in rr.modifiers), item[0]))
    for talent_id, rank in ordered:
        talent = definitions[talent_id]
        rank_row = next(row for row in talent.ranks if int(row.rank) == rank)
        for modifier in rank_row.modifiers:
            if modifier.kind == 'grant_source_spatial_charge_actions':
                from src.game.model.ir import SpatialChargeEffect
                fact=modifier.provenance.get('source_action_fact') or {}
                family=str(fact.get('family_key') or '')
                if (modifier.target_type!='action_family' or modifier.target_id!=family
                        or not family or len(fact.get('forms') or ())!=2
                        or fact.get('source_build_verified') is not False):
                    raise ValueError('INVALID_SOURCE_SPATIAL_CHARGE_FACT')
                if any(a.family_key==family for a in actions):
                    raise ValueError('SOURCE_SPATIAL_CHARGE_FAMILY_DUPLICATE')
                for form in fact['forms']:
                    mode_id=str(form['mode_id'])
                    if mode_id not in {m.id for m in modes}:raise ValueError('CHARGE_UNKNOWN_SOURCE_MODE')
                    r_id=str(form.get('cost_resource_id') or '')
                    if r_id and r_id not in {r.id for r in resources}:
                        raise ValueError('CHARGE_UNKNOWN_SOURCE_COST_RESOURCE')
                    source={'authority':'sourced_talent_spatial_charge_action',
                        'source_url':fact['source_url'],'source_build_verified':False,
                        'checkpoint_source_build':modifier.provenance['source_build']}
                    action_id=family+':'+str(form['id_suffix'])
                    cost=((ResourceCost(r_id,float(form['cost_amount'])),) if r_id else ())
                    effect=SpatialChargeEffect('spatial_charge','enemy',
                        float(form['minimum_range_yards']),float(form['maximum_range_yards']),
                        float(form['arrival_distance_yards']),str(form['arrival_position_kind']))
                    root=((ControlEffect('control','root','enemy',float(form['root_duration_s'])),)
                          if form.get('root_duration_s') else ())
                    granted=ActionDefinition(id=action_id,family_key=family,
                        name=str(form['name']),owner_actor_id=actor.id,
                        requirements=({'kind':'minimum_level','value':int(fact['required_level'])},
                            {'kind':'mode_is','value':mode_id}),costs=cost,
                        cast_time_s=0.,gcd_s=float(form['gcd_s']),
                        cooldown_s=float(form['cooldown_s']),effects=(effect,*root),
                        provenance=(source,),metadata={'talent_granted_action':True,
                            'range_yards':float(form['maximum_range_yards']),
                            'source_movement_action':True,
                            'source_interrupt_cast':'NOT_MODELED',
                            'source_target_orientation':'GEOMETRIC_PROXY',
                            'source_requires_2d':True})
                    actions.append(granted)
                    modes[:]=[replace(m,enabled_action_ids=tuple(dict.fromkeys(
                        (*m.enabled_action_ids,action_id))))
                        if m.id==mode_id and m.enabled_action_ids is not None else m for m in modes]
                    applied.append({'talent_id':talent_id,'rank':rank,
                        'action_id':action_id,'kind':modifier.kind,'source':source})
                continue
            if modifier.kind == 'grant_source_active_periodic_full_heal':
                from src.game.model.ir import ActivePeriodicFullHealEffect
                fact=modifier.provenance.get('source_action_fact') or {}
                family=str(fact.get('family_key') or '')
                mode_id=str(fact.get('required_mode_id') or '')
                source_families=tuple(fact.get('source_families') or ())
                if (modifier.target_type!='action_family' or modifier.target_id!=family
                        or not family or mode_id not in {m.id for m in modes}
                        or not source_families or not all(any(a.family_key==f
                            and any(isinstance(e,PeriodicHealEffect) for e in a.effects)
                            for a in actions) for f in source_families)
                        or fact.get('source_build_verified') is not False):
                    raise ValueError('INVALID_ACTIVE_PERIODIC_FULL_HEAL_GRANT')
                hot_auras=tuple(sorted({e.aura_id for a in actions
                    if a.family_key in source_families for e in a.effects
                    if isinstance(e,PeriodicHealEffect)}))
                if not hot_auras:raise ValueError('MISSING_ACTIVE_PERIODIC_HEAL_SOURCE')
                mana=next((r for r in resources if r.id=='mana'),None)
                if mana is None or not 0 < float(mana.metadata.get('base_mana',0)):
                    raise ValueError('ACTIVE_PERIODIC_HEAL_BASE_MANA_UNAVAILABLE')
                action_id=family+':'+str(fact['spell_id'])
                if any(a.id==action_id or a.family_key==family for a in actions):
                    raise ValueError('DUPLICATE_ACTIVE_PERIODIC_HEAL_GRANT')
                source={'source_url':fact['source_url'],
                        'authority':'source_index_active_periodic_heal',
                        'target_build':modifier.provenance['source_build'],
                        'client_source_build_verified':False}
                button=ActionDefinition(id=action_id,family_key=family,
                    name=str(fact['name']),owner_actor_id=actor.id,
                    requirements=({'kind':'minimum_level','value':int(fact['required_level'])},
                        {'kind':'mode_is','value':mode_id},
                        {'kind':'aura_any_present','scope':'actor','aura_ids':hot_auras}),
                    costs=(ResourceCost('mana',float(mana.metadata['base_mana'])*
                        float(fact['base_mana_cost_fraction'])),),
                    cast_time_s=0.,gcd_s=float(fact['gcd_s']),
                    cooldown_s=float(fact['cooldown_s']),
                    effects=(ActivePeriodicFullHealEffect('active_periodic_full_heal','self',
                        'health',source_families,float(fact['full_duration_multiplier'])),),
                    provenance=(source,),metadata={'talent_granted_action':True,
                        'source_build_bridge_verified':False,
                        'source_hot_preserved':True,
                        'source_multiple_hot_priority':'UNVERIFIED',
                        'source_healing_power_snapshot':'UNVERIFIED'})
                actions.append(button)
                modes[:]=[replace(m,enabled_action_ids=tuple(dict.fromkeys(
                    (*m.enabled_action_ids,action_id))))
                    if m.id==mode_id and m.enabled_action_ids is not None else m for m in modes]
                applied.append({'talent_id':talent_id,'rank':rank,
                                'action_id':action_id,'kind':modifier.kind,'source':source})
                continue
            if modifier.kind == 'grant_source_next_cast_instant_action':
                fact=modifier.provenance.get('source_action_fact') or {}
                family=str(fact.get('family_key') or '')
                mode_id=str(fact.get('required_mode_id') or '')
                if (modifier.target_type!='action_family' or modifier.target_id!=family or
                        not family or mode_id not in {m.id for m in modes} or
                        type(fact.get('spell_id')) is not int or fact['spell_id']<=0 or
                        fact.get('source_mechanics_version_verified') is not False or
                        not str(fact.get('mechanics_source_url','')).startswith('https://')):
                    raise ValueError('INVALID_NEXT_CAST_ACTION_GRANT')
                action_id=family+':'+str(fact['spell_id'])
                if any(a.id==action_id or a.family_key==family for a in actions):
                    raise ValueError('DUPLICATE_NEXT_CAST_ACTION_GRANT')
                action=ActionDefinition(id=action_id,family_key=family,
                    name=str(fact['name']),owner_actor_id=actor.id,
                    requirements=({'kind':'mode_is','value':mode_id},),costs=(),
                    cast_time_s=0.,gcd_s=float(fact['gcd_s']),
                    cooldown_s=float(fact['cooldown_s']),effects=(),
                    provenance=({'authority':'sourced_talent_next_cast_action',
                        'source_url':fact['mechanics_source_url'],
                        'mechanics_source_build':fact['mechanics_source_build'],
                        'target_build':modifier.provenance['source_build'],
                        'source_build_verified':False},),
                    metadata={'talent_granted_action':True,
                        'ignores_global_cooldown':True,
                        'source_next_cast_instant_grant':{
                        'school':str(fact['spell_school']),
                        'count':int(fact['next_cast_count']),
                        'source_url':str(fact['mechanics_source_url']),
                        'source_build_verified':False}})
                actions.append(action)
                modes[:]=[replace(m,enabled_action_ids=tuple(dict.fromkeys(
                    (*m.enabled_action_ids,action_id))))
                    if m.id==mode_id and m.enabled_action_ids is not None else m for m in modes]
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                'action_id':action_id,'source':dict(modifier.provenance)})
                continue
            if modifier.kind == 'grant_source_resource_action':
                # A typed source fact supplies all action parameters; this is
                # the same general ActionDefinition/ResourceChangeEffect used
                # for any class's resource-converting button.
                from src.game.model.ir import ResourceChangeEffect
                fact=modifier.provenance.get('source_action_fact') or {}
                mode_id=str(fact.get('required_mode_id') or '')
                resource_id=str(fact.get('resource_id') or '')
                cost_resource=str(fact.get('cost_resource_id') or '')
                family=str(fact.get('family_key') or '')
                if (modifier.target_type!='action_family' or modifier.target_id!=family
                        or not family or not any(m.id==mode_id for m in modes)
                        or resource_id not in {r.id for r in resources}
                        or cost_resource not in {r.id for r in resources}
                        or not str(fact.get('source_url','')).startswith('https://')):
                    raise ValueError('INVALID_SOURCE_RESOURCE_ACTION_GRANT')
                cost_definition=next(r for r in resources if r.id==cost_resource)
                base=cost_definition.metadata.get('base_mana')
                if base is None or not 0 < float(base):
                    raise ValueError('SOURCE_RESOURCE_ACTION_BASE_COST_UNAVAILABLE')
                action_id=family+':'+str(fact['spell_id'])
                if any(a.id==action_id or a.family_key==family for a in actions):
                    raise ValueError('SOURCE_RESOURCE_ACTION_DUPLICATE')
                source={'authority':'source_pinned_instant_resource_action',
                        'source_build':fact['source_build'],
                        'source_url':fact['source_url'],
                        'mechanics_source_url':fact['mechanics_source_url'],
                        'mechanics_source_build':fact['mechanics_source_build'],
                        **({'unsupported_build_bridge':modifier.provenance['unsupported_build_bridge']}
                           if modifier.provenance.get('unsupported_build_bridge') else {})}
                granted=ActionDefinition(id=action_id,family_key=family,
                    name=str(fact['name']),owner_actor_id=actor.id,
                    requirements=({'kind':'minimum_level','value':int(fact['required_level'])},
                        {'kind':'mode_is','value':mode_id},
                        *(({'kind':'resource_below_capacity','resource_id':resource_id},)
                          if int(fact['must_have_room']) else ())),
                    costs=(ResourceCost(cost_resource, float(base)*
                        float(fact['base_resource_cost_fraction'])),),
                    cast_time_s=0.,gcd_s=float(fact['gcd_s']),
                    cooldown_s=float(fact['cooldown_s']),
                    effects=(ResourceChangeEffect('resource_change',resource_id,
                        'actor','add',float(fact['resource_gain'])),),
                    provenance=(source,),metadata={'talent_granted_action':True,
                        'source_action_kind':'instant_resource_conversion',
                        'resource_cost_formula':'base_resource * source_fraction',
                        'resource_cost_reduction_group':str(fact['cost_reduction_group'])})
                actions.append(granted)
                modes[:]=[replace(m,enabled_action_ids=tuple(dict.fromkeys(
                    (*m.enabled_action_ids,action_id))))
                    if m.id==mode_id and m.enabled_action_ids is not None else m for m in modes]
                applied.append({'talent_id':talent_id,'rank':rank,
                    'action_id':action_id,'kind':modifier.kind,'source':source})
                continue
            if modifier.kind == 'grant_source_action':
                if modifier.target_type != 'source_action':
                    raise ValueError('grant_source_action requires source_action target')
                # A learned talent may grant a trainable *spell family* with
                # higher source ranks. The grant modifier points to the talent's
                # original spell ID; canonical rank rows declare that parent.
                # Choose the highest legal rank, never the first SQLite row.
                matching = [row for fact in ir_slice.source_facts
                    if fact.get('family') == 'talent_granted_action_facts'
                    for row in fact.get('actions', ())
                    if str(row.get('grant_parent_spell_id', row.get('spell_id'))) == modifier.target_id
                    and int(row.get('required_level', 0)) <= int(level)]
                if not matching:
                    raise ValueError('verified talent-granted action absent at level')
                highest = max(int(row['required_level']) for row in matching)
                matching = [row for row in matching if int(row['required_level']) == highest]
                if len(matching) != 1:
                    raise ValueError('ambiguous verified talent-granted rank')
                row = matching[0]
                if int(row['required_level']) > level:
                    raise ValueError('talent-granted action level not met')
                if not row.get('source_url'):
                    raise ValueError('talent-granted action source missing')
                action_id = str(row['family_key']) + ':' + str(row['spell_id'])
                if any(a.id == action_id for a in actions):
                    raise ValueError('duplicate talent-granted action')
                if row.get('action_kind') == 'timed_aura_weapon_proc':
                    from src.game.data.forever.source_timed_auras import compile_granted_timed_aura
                    action, granted_triggers = compile_granted_timed_aura(row, ir_slice=ir_slice)
                    actions.append(action)
                    triggers.extend(granted_triggers)
                    if str(row.get('proc_authority','')).startswith('CLASSIC_'):
                        unsupported.append({'code':'talent_granted_proc_server_frequency_unverified',
                            'status':'qualified_classic_proxy_not_current_forever_server',
                            'source_url':row.get('proc_source_url'),
                            'client_build':row.get('client_build'),
                            'talent_grant_spell_id':row['spell_id']})
                    applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                    'action_id':action.id,'trigger_ids':[t.id for t in granted_triggers]})
                    continue
                if row.get('action_kind') == 'periodic_damage_target_hit_debuff':
                    from src.game.model.ir import TargetStatDebuffEffect
                    from math import isfinite
                    total=float(row['periodic_total_base_damage'])
                    duration=float(row['periodic_duration_s'])
                    interval=float(row['periodic_tick_interval_s'])
                    delta=float(row['target_hit_chance_delta'])
                    if (not all(isfinite(v) for v in (total,duration,interval,delta))
                            or total <= 0 or duration <= 0 or interval <= 0
                            or abs(duration / interval - round(duration / interval)) > 1e-8
                            or not -1 <= delta < 0):
                        raise ValueError('invalid sourced periodic+hit talent grant')
                    source={'source_url':str(row['source_url']),
                        'talent_grant_spell_id':str(row.get('grant_parent_spell_id',row['spell_id'])),
                        'authority':'canonical_sqlite_verified_talent_grant'}
                    effects=(PeriodicEffect(effect_type='periodic_damage',
                        school=str(row['school']),target='enemy',
                        aura_id='source_periodic:'+str(row['spell_id']),
                        total_base_damage=total,duration_s=duration,
                        tick_interval_s=interval,
                        field_provenance={'total_base_damage':(source,)}),
                        TargetStatDebuffEffect(effect_type='target_stat_debuff',
                        aura_id='source_target_hit:'+str(row['spell_id']),
                        target_stat_id='hit_chance',delta=delta,duration_s=duration,
                        provenance=(source,)))
                    actions.append(ActionDefinition(id=action_id,
                        family_key=str(row['family_key']),name=str(row['name']),
                        owner_actor_id=actor.id,
                        requirements=({'kind':'minimum_level','value':int(row['required_level'])},
                            *(({'kind':'mode_is','value':str(row['required_mode_id'])},)
                              if row.get('required_mode_id') else ())),
                        costs=(ResourceCost('mana',float(row['mana_cost'])),),
                        cast_time_s=float(row['cast_time_s']),gcd_s=float(row['gcd_s']),
                        cooldown_s=float(row['cooldown_s']),effects=effects,
                        provenance=(source,),metadata={'source_range_yards':row.get('range_yards'),
                            'periodic_tick_interval_status':row.get('periodic_tick_interval_status'),
                            'spell_power_coefficient_status':row.get('spell_power_coefficient_status')}))
                    if row.get('required_mode_id'):
                        mode_id=str(row['required_mode_id'])
                        if not any(m.id==mode_id for m in modes):
                            raise ValueError('grant requires unknown source mode')
                        modes[:]=[replace(m,enabled_action_ids=tuple(
                            dict.fromkeys((*m.enabled_action_ids,action_id))))
                            if m.id==mode_id and m.enabled_action_ids is not None else m
                            for m in modes]
                    applied.append({'talent_id':talent_id,'rank':rank,
                        'kind':modifier.kind,'action_id':action_id,'source':dict(modifier.provenance)})
                    continue
                if row.get('action_kind') not in (None, 'direct_damage'):
                    raise ValueError('unknown canonical talent-granted action kind')
                actions.append(ActionDefinition(id=action_id, family_key=str(row['family_key']),
                    name=str(row['name']), owner_actor_id=actor.id,
                    requirements=({'kind':'minimum_level','value':int(row['required_level'])},),
                    costs=(ResourceCost('mana',float(row['mana_cost'])),),
                    cast_time_s=float(row['cast_time_s']),gcd_s=float(row['gcd_s']),
                    cooldown_s=float(row['cooldown_s']),
                    effects=(DamageEffect('damage',str(row['school']),'enemy',
                        float(row['damage_min']),float(row['damage_max']),
                        field_provenance={'base_damage':({'source_url':row['source_url']},)}),),
                    provenance=({'source_url':row['source_url'],
                        'authority':'canonical_sqlite_verified_talent_grant'},),
                    metadata={'conditional_target_control_damage_multiplier':{
                        'control_id':str(row['conditional_target_control']),
                        'multiplier':float(row['conditional_multiplier'])}}))
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                'action_id':action_id,'source':dict(modifier.provenance)})
                continue
            if modifier.kind == 'unlock_action_family':
                if (modifier.target_type != 'action_family' or
                        not any(action.family_key == modifier.target_id and
                                any(isinstance(e, WeaponDamageEffect) for e in action.effects)
                                for action in ir_slice.actions)):
                    raise ValueError('UNLOCK_MISSING_VERIFIED_WEAPON_ACTION_FAMILY')
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                'action_family':modifier.target_id,
                                'source':dict(modifier.provenance)})
                continue
            if modifier.kind == 'control_target_cap_bonus':
                prov=dict(modifier.provenance)
                if (modifier.target_type!='action_family' or
                        type(modifier.value) not in (int,float) or
                        not float(modifier.value).is_integer() or not 0 < modifier.value <= 16
                        or not str(prov.get('source_url','')).startswith('https://')):
                    raise ValueError('INVALID_SOURCE_CONTROL_TARGET_CAP_BONUS')
                control_id=str(prov.get('control_id',''))
                matched=False
                for index,action in enumerate(actions):
                    if action.family_key != modifier.target_id:continue
                    baseline=(action.metadata.get('source_control_target_caps') or {}).get(control_id)
                    if (not baseline or baseline['source_build']!=prov.get('source_build')
                            or baseline['base_source_url']!=prov.get('base_source_url')
                            or baseline['base_max_targets']!=prov.get('base_max_targets')):
                        raise ValueError('SOURCE_CONTROL_TARGET_CAP_BASELINE_MISSING')
                    cap=int(baseline['base_max_targets']+modifier.value)
                    if not 1<=cap<=16:raise ValueError('INVALID_SOURCE_CONTROL_TARGET_CAP')
                    new_spec={**baseline,'max_targets':cap,'talent_source_url':prov['source_url']}
                    actions[index]=replace(action,metadata={**dict(action.metadata),
                        'source_control_target_caps':{**dict(action.metadata['source_control_target_caps']),
                            control_id:new_spec}})
                    matched=True
                if not matched:raise ValueError('SOURCE_CONTROL_TARGET_CAP_ACTION_MISSING')
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'action_family':modifier.target_id,'control_id':control_id,
                    'max_targets':int(prov['base_max_targets']+modifier.value),'source':prov})
                continue
            if modifier.kind == 'cast_charge_exchange':
                # The source owns both action families and all charge semantics.
                # Never turn a conditional cast-time reduction into a permanent
                # static cast-time buff or apply only one half of the exchange.
                prov=dict(modifier.provenance)
                producer=str(prov.get('producer_family',''))
                consumer=str(prov.get('consumer_family',''))
                bank=str(prov.get('bank_id',''))
                if (modifier.target_type != 'action_family' or modifier.target_id != consumer
                        or not producer or not consumer or producer==consumer
                        or bank != 'source_cast_charges:'+producer+':'+consumer
                        or type(prov.get('grant_per_cast')) is not int
                        or type(prov.get('capacity')) is not int
                        or not 0 < prov['grant_per_cast'] <= prov['capacity'] <= 16
                        or not 0 < float(prov.get('duration_s',0.)) <= 120.
                        or not 0 < float(modifier.value) <= 10.
                        or not str(prov.get('source_url','')).startswith('https://')):
                    raise ValueError('INVALID_SOURCE_CAST_CHARGE_EXCHANGE')
                if not any(a.family_key==producer for a in actions) or not any(
                        a.family_key==consumer for a in actions):
                    raise ValueError('SOURCE_CAST_CHARGE_ACTION_FAMILY_MISSING')
                source={'bank_id':bank,'grant_per_cast':int(prov['grant_per_cast']),
                    'capacity':int(prov['capacity']),'duration_s':float(prov['duration_s']),
                    'source_url':prov['source_url'],'source_build':prov['source_build']}
                sink={'bank_id':bank,'reduction_s':float(modifier.value),
                    'source_url':prov['source_url'],'source_build':prov['source_build']}
                for index,action in enumerate(actions):
                    role=('source_cast_charge_producer' if action.family_key==producer else
                          'source_cast_charge_consumer' if action.family_key==consumer else None)
                    if role is None:continue
                    facts=source if role.endswith('producer') else sink
                    if role in action.metadata and action.metadata[role] != facts:
                        raise ValueError('CONFLICTING_SOURCE_CAST_CHARGE_BANK')
                    actions[index]=replace(action,metadata={**dict(action.metadata),role:facts},
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'source':prov},))
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'bank_id':bank,'producer_family':producer,'consumer_family':consumer,
                    'source':prov})
                continue
            if modifier.kind == 'incoming_dodge_resource_gain':
                from src.game.model.ir import ResourceEventGainRule
                prov=dict(modifier.provenance)
                mode=str(prov.get('required_mode_id') or '')
                amount=float(prov.get('bonus_resource_amount',0.))
                if (modifier.target_type!='resource' or not 0. < float(modifier.value) <= 1.
                        or mode not in {m.id for m in modes} or not 0. < amount <= 100.):
                    raise ValueError('INVALID_INCOMING_DODGE_RESOURCE_SOURCE')
                matches=[i for i,r in enumerate(resources) if r.id==modifier.target_id]
                if len(matches)!=1:raise ValueError('SOURCE_DODGE_RESOURCE_UNAVAILABLE')
                idx=matches[0];resource=resources[idx]
                rule=ResourceEventGainRule(
                    id=f'source_dodge_gain:{talent_id}:{resource.id}',
                    event_kind='incoming_physical_dodge',
                    event_value_field='sampled_dodge_count',
                    multiplier=amount,required_mode_id=mode,
                    provenance=(prov,),metadata={'resolution':'sampled_joint_dodge',
                        'proc_probability':float(modifier.value)})
                resources[idx]=replace(resource,event_gain_rules=(*resource.event_gain_rules,rule))
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'resource_id':resource.id,'expected_gain_per_dodge':amount*float(modifier.value),
                    'required_mode_id':mode,'source':prov})
                continue
            if modifier.kind == 'heal_crit_chance_bonus':
                if (modifier.target_type!='action_family' or not 0. < float(modifier.value) <= 1.):
                    raise ValueError('INVALID_HEAL_CRIT_MODIFIER')
                crit_multiplier=float(modifier.provenance.get('heal_crit_multiplier',0.))
                crit_url=str(modifier.provenance.get('heal_crit_multiplier_source_url') or '')
                if not (1.<crit_multiplier<=3. and crit_url.startswith('https://') and
                        modifier.provenance.get('heal_crit_multiplier_build_bridge_unverified') is True):
                    raise ValueError('HEAL_CRIT_MULTIPLIER_SOURCE_FACTS_REQUIRED')
                matched=[]
                for idx,action in enumerate(actions):
                    if action.family_key!=modifier.target_id:continue
                    effects=tuple(replace(effect,
                        crit_chance_bonus=float(effect.crit_chance_bonus)+float(modifier.value),
                        crit_multiplier=crit_multiplier,
                        field_provenance={**dict(effect.field_provenance),
                            'crit_multiplier':({'source_url':crit_url,
                                'source_build':'classic_era',
                                'build_bridge_to_forever_70338_unverified':True},)})
                        if isinstance(effect,HealEffect) else effect for effect in action.effects)
                    if effects==action.effects:continue
                    actions[idx]=replace(action,effects=effects,provenance=action.provenance+({
                        'stage':'talent_modifier','talent_id':talent_id,'rank':rank,
                        'kind':modifier.kind,'source':dict(modifier.provenance)},))
                    matched.append(action.id)
                if not matched:raise ValueError('SOURCE_HEAL_CRIT_ACTION_FAMILY_MISSING')
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'action_ids':matched,'source':dict(modifier.provenance)})
                continue
            if modifier.kind == 'critical_resource_gain':
                # Generic event-driven resource gain. No talent/class dispatch:
                # the source modifier supplies target resource, mode, amount,
                # trigger chance and whether the critical ability generates
                # this very same resource.
                from src.game.model.ir import ResourceEventGainRule
                if modifier.target_type!='resource' or not 0 < float(modifier.value) <= 1:
                    raise ValueError('INVALID_SOURCE_CRITICAL_RESOURCE_MODIFIER')
                prov=dict(modifier.provenance)
                mode=prov.get('required_mode_id')
                amount=prov.get('bonus_resource_amount')
                generator=prov.get('requires_resource_generator')
                if (mode not in {m.id for m in modes} or type(amount) not in (int,float)
                        or not 0 < float(amount) <= 100 or type(generator) is not bool):
                    raise ValueError('INCOMPLETE_CRITICAL_RESOURCE_EVENT_SOURCE')
                matches=[i for i,resource in enumerate(resources)
                         if resource.id==modifier.target_id]
                if len(matches)!=1:raise ValueError('CRITICAL_RESOURCE_TARGET_UNAVAILABLE')
                index=matches[0];resource=resources[index]
                rule=ResourceEventGainRule(id=f'source_critical_gain:{talent_id}:{modifier.target_id}',
                    event_kind='nonperiodic_melee_critical',
                    event_value_field='sampled_critical_count',
                    multiplier=float(amount),
                    required_mode_id=str(mode),
                    filters=({'required_generated_resource':modifier.target_id}
                             if generator else {}),
                    provenance=(prov,),
                    metadata={'resolution':'sampled_joint_critical',
                              'proc_probability':float(modifier.value),
                              'resource_amount_source_build':prov['resource_amount_source_build']})
                resources[index]=replace(resource,event_gain_rules=(*resource.event_gain_rules,rule))
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'resource_id':resource.id,'trigger_probability':float(modifier.value),
                    'amount_per_proc':float(amount),'required_mode_id':mode,'source':prov})
                continue
            if modifier.kind == 'timed_spell_crit_cast_haste':
                prov=dict(modifier.provenance)
                if (modifier.target_type!='actor_proc' or
                        modifier.target_id!='nonperiodic_spell_crit' or
                        not 0 < float(modifier.value) < 1 or
                        not 0 < float(prov.get('gcd_reduction_fraction',0)) < 1 or
                        not 0 < float(prov.get('duration_s',0)) <= 60 or
                        not str(prov.get('source_url','')).startswith('https://')):
                    raise ValueError('INVALID_SOURCE_TIMED_CRIT_HASTE')
                spec={'event_kind':modifier.target_id,
                    'cast_speed_fraction':float(modifier.value),
                    'gcd_reduction_fraction':float(prov['gcd_reduction_fraction']),
                    'duration_s':float(prov['duration_s']),
                    'source':prov}
                if actor.metadata.get('source_timed_spell_crit_haste') is not None:
                    raise ValueError('DUPLICATE_SOURCE_TIMED_CRIT_HASTE')
                actor=replace(actor,metadata={**dict(actor.metadata),
                    'source_timed_spell_crit_haste':spec})
                applied.append({'talent_id':talent_id,'rank':rank,
                    'kind':modifier.kind,'source':prov})
                continue
            if modifier.kind=='control_duration_delta_s' and modifier.target_type=='action_family_group':
                families=tuple(str(modifier.target_id).split(','))
                if (not families or len(set(families))!=len(families) or
                        not 0<float(modifier.value)<=60):
                    raise ValueError('INVALID_SOURCE_CONTROL_DURATION_FAMILIES')
                matched=[]
                for i,action in enumerate(actions):
                    if action.family_key not in families:continue
                    modified=[];n=0
                    for effect in action.effects:
                        if isinstance(effect,ControlEffect) and effect.control_id=='stun':
                            modified.append(replace(effect,duration_s=float(effect.duration_s)+float(modifier.value)))
                            n+=1
                        else:modified.append(effect)
                    if n:
                        actions[i]=replace(action,effects=tuple(modified),
                            provenance=action.provenance+({'stage':'talent_modifier',
                                'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                'source':dict(modifier.provenance)},))
                        matched.append(action.id)
                if not matched:raise ValueError('NO_EXECUTABLE_SOURCE_CONTROL_DURATION_ACTION')
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'action_ids':matched,'future_tier_family_unresolved':tuple(
                    family for family in families if not any(a.family_key==family for a in actions)),
                    'source':dict(modifier.provenance)})
                continue
            if modifier.target_type == 'actor_stat':
                if modifier.kind == 'healing_power_from_stat':
                    source_stat = str(modifier.provenance.get('source_stat') or '')
                    if (modifier.target_id != 'healing_power'
                            or source_stat not in actor.base_stats
                            or not 0. < float(modifier.value) <= 1.):
                        raise ValueError('INVALID_SOURCE_STAT_TO_HEALING_CONVERSION')
                    coefficients = dict(actor.metadata.get('source_healing_power_from_stats') or {})
                    before = float(coefficients.get(source_stat, 0.))
                    coefficients[source_stat] = before + float(modifier.value)
                    actor = replace(actor, metadata={**dict(actor.metadata),
                        'source_healing_power_from_stats': coefficients})
                    applied.append({'talent_id': talent_id, 'rank': rank,
                        'kind': modifier.kind, 'source_stat': source_stat,
                        'before': before, 'after': coefficients[source_stat]})
                    continue
                if modifier.kind not in ('actor_stat_pct', 'actor_stat_flat'):
                    raise ValueError(f'unsupported actor stat talent modifier: {modifier.kind}')
                if modifier.kind == 'actor_stat_pct' and modifier.target_id not in actor.base_stats:
                    raise ValueError(f'actor stat unavailable: {modifier.target_id}')
                stats = dict(actor.base_stats)
                before = float(stats.get(modifier.target_id, 0.0))
                after = (before * (1.0 + float(modifier.value))
                         if modifier.kind == 'actor_stat_pct' else before + float(modifier.value))
                stats[modifier.target_id] = after
                # Re-evaluate source-derived combat stats when a talent changes
                # a primary stat. Mode-scoped conversions remain separate and
                # use the new source stat at form entry.
                for fact in actor.metadata.get('canonical_primary_stat_conversions', ()):
                    if (fact['target_type'] == 'stat' and
                            fact['source_stat'] == modifier.target_id):
                        target = str(fact['target_id'])
                        stats[target] = float(stats.get(target, 0.0)) + (
                            after - before) * float(fact['coefficient'])
                actor = replace(actor, base_stats=stats,
                    provenance=actor.provenance + ({'stage':'talent_modifier','talent_id':talent_id,
                                                   'rank':rank,'source':dict(modifier.provenance)},))
                # Shared source-backed mana conversion is already used by gear;
                # recompute from total (possibly geared) Intellect here too.
                for idx, resource in enumerate(resources):
                    if (resource.metadata.get('base_mana') is not None and
                            str(resource.metadata.get('capacity_formula','')).startswith(
                                'base_mana + classic_mana_bonus_from_intellect(') and
                            modifier.target_id == 'intellect'):
                        from src.game.data.forever.player_state import classic_mana_bonus_from_intellect
                        capacity = float(resource.metadata['base_mana']) + classic_mana_bonus_from_intellect(after)
                        resources[idx] = replace(resource, capacity=capacity, initial_amount=capacity,
                            metadata={**dict(resource.metadata),'base_intellect':after,
                                      'intellect_mana_bonus':classic_mana_bonus_from_intellect(after),
                                      'talents_included':True})
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                                'target_stat':modifier.target_id,'before':before,'after':after})
                continue
            if modifier.target_type == "mode":
                mode_index = next((i for i, mode in enumerate(modes) if mode.id == modifier.target_id), None)
                if mode_index is None:
                    raise ValueError(f"talent modifier mode target unavailable: {modifier.target_id}")
                mode = modes[mode_index]
                if modifier.kind in ('mode_entry_expected_gain','mode_entry_restore_last'):
                    provenance = dict(modifier.provenance)
                    resource_id = str(provenance.get('resource_id') or '')
                    if not any(r.id == resource_id and r.owner_actor_id == actor.id for r in resources):
                        raise ValueError(f'mode entry talent resource unavailable: {resource_id}')
                    if modifier.kind == 'mode_entry_restore_last':
                        forbidden = tuple(str(x) for x in provenance.get('forbidden_mode_ids',()))
                        if any(x not in {m.id for m in modes} for x in forbidden):
                            raise ValueError('mode entry forbidden mode unavailable')
                        entry = ModeEntryResourceModifier(kind='restore_last_mode_resource',
                            resource_id=resource_id, value=float(modifier.value),
                            outside_regen_per_s=float(provenance['outside_regen_per_s']),
                            max_restored=float(provenance['max_restored']),
                            forbidden_mode_ids=forbidden, provenance=(provenance,))
                    else:
                        entry = ModeEntryResourceModifier(kind='expected_flat_gain',
                            resource_id=resource_id, value=float(modifier.value),
                            provenance=(provenance,))
                    modes[mode_index] = replace(mode,
                        entry_resource_modifiers=mode.entry_resource_modifiers+(entry,),
                        provenance=mode.provenance+({'stage':'talent_modifier','talent_id':talent_id,
                            'rank':rank,'kind':modifier.kind,'source':provenance},))
                    applied.append({'talent_id':talent_id,'rank':rank,'mode_id':mode.id,
                                    'kind':modifier.kind,'resource_id':resource_id,
                                    'value':float(modifier.value)})
                    continue
                if modifier.kind == "mode_armor_per_level":
                    mode_modifier = ModeStatModifier(target_stat="armor", kind="add_level_scaled",
                                                     value=float(modifier.value))
                elif modifier.kind == "mode_armor_excess_defense":
                    threshold = modifier.provenance.get('reference_level_multiplier')
                    if threshold is None:
                        raise ValueError("source threshold missing for excess-defense armor")
                    mode_modifier = ModeStatModifier(
                        target_stat="armor", kind="add_stat_above_level_scaled",
                        value=float(modifier.value), source_stat="defense",
                        reference_level_multiplier=float(threshold))
                elif modifier.kind == 'mode_stat_flat':
                    target_stat = str(modifier.provenance.get('target_stat') or '')
                    if not target_stat:
                        raise ValueError('mode flat stat source target missing')
                    mode_modifier = ModeStatModifier(target_stat=target_stat,
                        kind='add_flat',value=float(modifier.value))
                elif modifier.kind in ('mode_stat_pct','mode_derived_stat_pct'):
                    source_stat = modifier.provenance.get('source_stat')
                    target_stat = (source_stat if modifier.kind == 'mode_stat_pct'
                                   else modifier.provenance.get('target_id'))
                    if not source_stat or not target_stat:
                        raise ValueError('source stat conversion metadata missing')
                    if source_stat not in actor.base_stats:
                        raise ValueError(f'source actor stat unavailable: {source_stat}')
                    mode_modifier = ModeStatModifier(target_stat=str(target_stat),
                        kind='add_stat_scaled',source_stat=str(source_stat),value=float(modifier.value))
                elif modifier.kind == 'mode_resource_capacity_pct':
                    source_stat = modifier.provenance.get('source_stat')
                    resource_id = modifier.provenance.get('target_id')
                    if not source_stat or not resource_id or source_stat not in actor.base_stats:
                        raise ValueError('resource conversion source stat missing')
                    if not any(r.id == resource_id and r.capacity is not None for r in resources):
                        raise ValueError('resource conversion capacity target unavailable')
                    cap_modifier = ModeResourceCapacityModifier(resource_id=str(resource_id),
                        kind='add_stat_scaled',source_stat=str(source_stat),value=float(modifier.value))
                    modes[mode_index] = replace(mode,
                        resource_capacity_modifiers=mode.resource_capacity_modifiers + (cap_modifier,),
                        provenance=mode.provenance + ({'stage':'talent_modifier','talent_id':talent_id,
                            'rank':rank,'kind':modifier.kind,'source':dict(modifier.provenance)},))
                    applied.append({'talent_id':talent_id,'rank':rank,'mode_id':mode.id,
                                    'kind':modifier.kind,'value':float(modifier.value),
                                    'target_resource':str(resource_id)})
                    continue
                else:
                    raise ValueError(f"unsupported mode talent modifier kind: {modifier.kind}")
                modes[mode_index] = replace(mode, stat_modifiers=mode.stat_modifiers + (mode_modifier,),
                    provenance=mode.provenance + ({"stage": "talent_modifier", "talent_id": talent_id,
                        "rank": rank, "kind": modifier.kind, "value": float(modifier.value),
                        "provenance": dict(modifier.provenance)},))
                applied.append({"talent_id": talent_id, "rank": rank, "mode_id": mode.id,
                                "kind": modifier.kind, "value": float(modifier.value),
                                "target_stat": mode_modifier.target_stat})
                continue
            if modifier.target_type == 'trigger_filter':
                if modifier.kind != 'effect_damage_pct':
                    raise ValueError('unsupported trigger talent modifier')
                changed=[]
                for i,trigger in enumerate(triggers):
                    if trigger.metadata.get('effect_category') != modifier.target_id:
                        continue
                    effects=[]
                    for effect in trigger.effects:
                        factor=max(0.,1.+float(modifier.value))
                        if isinstance(effect,DamageEffect):
                            effects.append(replace(effect,base_min=effect.base_min*factor,
                                base_max=effect.base_max*factor,
                                spell_power_coefficient=effect.spell_power_coefficient*factor))
                        elif isinstance(effect,WeaponDamageEffect):
                            effects.append(replace(effect,weapon_damage_multiplier=effect.weapon_damage_multiplier*factor,
                                flat_damage=effect.flat_damage*factor))
                        else:
                            raise ValueError('unsupported trigger damage effect')
                    triggers[i]=replace(trigger,effects=tuple(effects),
                        provenance=trigger.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'source':dict(modifier.provenance)},))
                    changed.append(trigger.id)
                if not changed:
                    raise ValueError(f'no source triggers in category: {modifier.target_id}')
                applied.append({'talent_id':talent_id,'rank':rank,
                    'kind':modifier.kind,'trigger_ids':changed,'value':float(modifier.value)})
                continue
            if modifier.target_type == 'resource' and modifier.kind == 'avoidance_resource_proc':
                matches = [i for i,r in enumerate(resources) if
                           r.id == modifier.target_id and r.owner_actor_id == actor.id]
                if len(matches) != 1:
                    raise ValueError('AVOIDANCE_PROC_RESOURCE_NOT_IN_GAME_IR')
                idx = matches[0]
                resource = resources[idx]
                rule = _compile_avoidance_resource_rule(modifier, talent_id=talent_id,
                    rank=rank, resource_id=resource.id, modes=modes)
                resources[idx] = replace(resource,
                    event_gain_rules=resource.event_gain_rules+(rule,))
                applied.append({'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                    'resource_id':resource.id,'expected_gain_per_dodge':rule.multiplier})
                continue
            if modifier.target_type not in ('action_family', 'action_filter'):
                raise ValueError(f"unsupported talent modifier target_type: {modifier.target_type}")
            def matches_filter(action):
                if modifier.target_type == 'action_family':
                    return action.family_key == modifier.target_id
                target = modifier.target_id
                if target == 'instant_mana':
                    return action.cast_time_s == 0 and any(c.resource_id == 'mana' for c in action.costs)
                if target == 'spells_and_melee':
                    return action.owner_actor_id == actor.id and any(
                        isinstance(e, (DamageEffect, WeaponDamageEffect,
                            ResourceScaledDirectDamageEffect)) or
                        (isinstance(e, PeriodicEffect) and e.school.lower() != 'physical')
                        for e in action.effects)
                if target == 'melee_ability':
                    # Action-based melee attacks, never passive auto swings,
                    # spell schools or periodic damage streams.
                    return (action.owner_actor_id == actor.id and any(
                        isinstance(e,(WeaponDamageEffect,ResourceScaledDirectDamageEffect))
                        and e.school.lower()=='physical' or
                        isinstance(e,DamageEffect) and e.school.lower()=='physical'
                        for e in action.effects))
                if target == 'all_damage':
                    return (action.owner_actor_id == actor.id and
                        any(isinstance(e, (DamageEffect, WeaponDamageEffect,
                            PeriodicEffect, ResourceScaledPeriodicEffect,
                            ResourceScaledDirectDamageEffect)) for e in action.effects))
                if target == 'damage_spell':
                    return (any(isinstance(e, (DamageEffect, PeriodicEffect)) and
                                e.school.lower() != 'physical' for e in action.effects)
                            and any(c.resource_id == 'mana' for c in action.costs))
                if target == 'shapeshift_mana':
                    return ((any(isinstance(e, ModeChangeEffect) for e in action.effects)
                            or action.metadata.get('resource_cost_reduction_group')==target)
                            and any(c.resource_id == 'mana' for c in action.costs))
                if target == 'periodic':
                    return any(isinstance(e, (PeriodicEffect, PeriodicHealEffect,
                                              ResourceScaledPeriodicEffect)) for e in action.effects)
                if target == 'healing':
                    return any(isinstance(e, (HealEffect, PeriodicHealEffect)) for e in action.effects)
                if target.startswith('damage_schools:'):
                    schools = set(target.split(':',1)[1].split(','))
                    return any(isinstance(e, (DamageEffect, PeriodicEffect)) and
                               e.school.lower() in schools for e in action.effects)
                raise ValueError(f'unsupported source action filter: {target}')
            matched = False
            for index, action in enumerate(actions):
                if not matches_filter(action):
                    continue
                matched = True
                before: float
                after: float
                if modifier.kind == 'cast_pushback_avoidance_chance':
                    # Only actual non-instant casts can be pushed back. The
                    # source target is the spell school, not a class check.
                    if float(action.cast_time_s) <= 0.:
                        continue
                    fraction=float(modifier.value)
                    if not 0. <= fraction <= 1.:
                        raise ValueError('INVALID_SOURCE_CAST_PUSHBACK_AVOIDANCE')
                    before=float(action.metadata.get('cast_pushback_avoidance_chance',0.))
                    after=min(1.,before+fraction)
                    actions[index]=replace(action,metadata={**dict(action.metadata),
                        'cast_pushback_avoidance_chance':after,
                        'cast_pushback_avoidance_source':dict(modifier.provenance)},
                        provenance=action.provenance+({'stage':'talent_modifier',
                            'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                            'value':fraction,'before':before,'after':after},))
                elif modifier.kind == 'action_control_proc':
                    # A talent can add a source-typed proc to any damage action.
                    # Chance and duration are rank-specific facts, not engine
                    # assumptions. An action must already have a damage effect.
                    chance=float(modifier.value)
                    duration=float(modifier.provenance['duration_s'])
                    control_id=str(modifier.provenance['control_id'])
                    if (not 0. < chance <= 1. or not 0. < duration <= 60.
                            or not control_id or
                            type(modifier.provenance.get('prevents_enemy_actions')) is not bool or
                            type(modifier.provenance.get('breaks_on_damage')) is not bool or
                            not any(isinstance(e,(DamageEffect,WeaponDamageEffect,
                                ResourceScaledDirectDamageEffect)) for e in action.effects)):
                        raise ValueError('INVALID_SOURCE_ACTION_CONTROL_PROC')
                    effect=ControlEffect('control',control_id,'enemy',duration,
                        prevents_enemy_actions=modifier.provenance['prevents_enemy_actions'],
                        breaks_on_damage=modifier.provenance['breaks_on_damage'],
                        proc_chance=chance)
                    actions[index]=replace(action,effects=(*action.effects,effect),
                        provenance=action.provenance+({'stage':'talent_modifier',
                            'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                            'value':chance,'source':dict(modifier.provenance)},))
                    before=0.;after=chance
                elif modifier.kind == "cast_time_delta_s":
                    before = float(action.cast_time_s)
                    after = max(0.0, before + float(modifier.value))
                    actions[index] = replace(action, cast_time_s=after, provenance=action.provenance + ({
                        "stage": "talent_modifier", "talent_id": talent_id, "rank": rank,
                        "kind": modifier.kind, "value": float(modifier.value), "before": before, "after": after,
                        "provenance": dict(modifier.provenance),
                    },))
                elif modifier.kind == 'conditional_target_aura_damage_pct':
                    if modifier.provenance.get('condition') != 'target_has_bleed':
                        raise ValueError('UNKNOWN_SOURCE_TARGET_AURA_CONDITION')
                    before=1.0
                    after=1.0+float(modifier.value)
                    if not 1.0 < after <= 2.0:
                        raise ValueError('INVALID_CONDITIONAL_TARGET_DAMAGE_FACTOR')
                    old=tuple(action.metadata.get('conditional_target_aura_damage_multipliers',()))
                    actions[index]=replace(action,
                        metadata={**dict(action.metadata),
                            'conditional_target_aura_damage_multipliers':(*old,{
                                'aura_category':'bleed', 'multiplier':after,
                                'source':dict(modifier.provenance),
                                'talent_id':talent_id, 'rank':rank})},
                        provenance=action.provenance+({'stage':'talent_modifier',
                            'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                            'source':dict(modifier.provenance)},))
                elif modifier.kind == 'threat_factor_pct':
                    # Preserve the entire sourced compound. Solo fights with one
                    # player actor have no competing threat. The value is retained
                    # for a future multi-actor threat executor, not silently lost.
                    before=float(action.metadata.get('threat_multiplier',1.0))
                    after=before*max(0.,1.+float(modifier.value))
                    actions[index]=replace(action,metadata={**dict(action.metadata),
                        'threat_multiplier':after,'threat_source':dict(modifier.provenance),
                        'threat_execution_scope':'solo_only_no_competing_actor'},
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'before':before,'after':after,'source':dict(modifier.provenance)},))
                elif modifier.kind == 'hit_chance_bonus':
                    # The source scope is resolved before this point. Runtime
                    # consumes the action-local bonus on every damage event,
                    # including the ticks of an applied periodic spell.
                    before=float(action.metadata.get('outgoing_hit_bonus',0.0))
                    after=before+float(modifier.value)
                    if not 0.0 <= after <= 1.0:
                        raise ValueError('outgoing hit bonus outside probability bounds')
                    actions[index]=replace(action,metadata={**dict(action.metadata),
                        'outgoing_hit_bonus':after,
                        'outgoing_hit_source':dict(modifier.provenance)},
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'before':before,'after':after,
                        'source':dict(modifier.provenance)},))
                elif modifier.kind == 'cooldown_factor_pct':
                    before=float(action.cooldown_s)
                    if not 0 < before <= 7200 or not -1 < float(modifier.value) < 0:
                        raise ValueError('INVALID_SOURCE_COOLDOWN_FRACTION')
                    after=before*(1.+float(modifier.value))
                    actions[index]=replace(action,cooldown_s=after,
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'before':before,'after':after,'source':dict(modifier.provenance)},))
                elif modifier.kind == 'cooldown_delta_s':
                    before=float(action.cooldown_s)
                    after=max(0.,before+float(modifier.value))
                    actions[index]=replace(action,cooldown_s=after,
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'source':dict(modifier.provenance),'before':before,'after':after},))
                elif modifier.kind == "resource_cost_pct":
                    relevant = [cost for cost in action.costs]
                    if not relevant:
                        raise ValueError(f"talent modifier target has no resource cost: {action.id}")
                    before = float(sum(cost.amount for cost in relevant))
                    factor = max(0.0, 1.0 + float(modifier.value))
                    new_costs = tuple(ResourceCost(resource_id=cost.resource_id, amount=float(cost.amount) * factor) for cost in action.costs)
                    after = float(sum(cost.amount for cost in new_costs))
                    actions[index] = replace(action, costs=new_costs, provenance=action.provenance + ({
                        "stage": "talent_modifier", "talent_id": talent_id, "rank": rank,
                        "kind": modifier.kind, "value": float(modifier.value), "before": before, "after": after,
                        "provenance": dict(modifier.provenance),
                    },))
                elif modifier.kind == 'gcd_delta_s':
                    before=float(action.gcd_s)
                    after=max(0.0,before+float(modifier.value))
                    actions[index]=replace(action,gcd_s=after,provenance=action.provenance+({
                        'stage':'talent_modifier','talent_id':talent_id,'rank':rank,
                        'kind':modifier.kind,'before':before,'after':after,
                        'source':dict(modifier.provenance)},))
                elif modifier.kind == 'periodic_duration_delta_s':
                    delta=float(modifier.value)
                    if delta <= 0:
                        raise ValueError('periodic duration extension must be positive')
                    effects=[]; changed=[]
                    for effect in action.effects:
                        if isinstance(effect,(PeriodicEffect,PeriodicHealEffect)):
                            old_duration=float(effect.duration_s)
                            interval=float(effect.tick_interval_s)
                            if interval <= 0 or old_duration <= 0:
                                raise ValueError('invalid source periodic interval/duration')
                            old_ticks=int(round(old_duration/interval))
                            new_duration=old_duration+delta
                            new_ticks=int(round(new_duration/interval))
                            if (old_ticks < 1 or new_ticks <= old_ticks or
                                abs(old_ticks*interval-old_duration)>1e-7 or
                                abs(new_ticks*interval-new_duration)>1e-7):
                                raise ValueError('source periodic duration does not align with tick interval')
                            factor=float(new_ticks)/float(old_ticks)
                            if isinstance(effect,PeriodicEffect):
                                effect=replace(effect,duration_s=new_duration,
                                    total_base_damage=float(effect.total_base_damage)*factor)
                            else:
                                effect=replace(effect,duration_s=new_duration,
                                    total_base_heal=float(effect.total_base_heal)*factor)
                            changed.append((old_duration,new_duration))
                        effects.append(effect)
                    if not changed:
                        raise ValueError(f'periodic duration target has no periodic effect: {action.id}')
                    before=float(sum(x[0] for x in changed));after=float(sum(x[1] for x in changed))
                    actions[index]=replace(action,effects=tuple(effects),provenance=action.provenance+({
                        'stage':'talent_modifier','talent_id':talent_id,'rank':rank,
                        'kind':modifier.kind,'value':delta,'before':before,'after':after,
                        'source':dict(modifier.provenance)},))
                elif modifier.kind == "resource_cost_flat":
                    if not action.costs:
                        raise ValueError(f"talent modifier target has no resource cost: {action.id}")
                    before = float(sum(cost.amount for cost in action.costs))
                    resource_filter = modifier.provenance.get('resource_id')
                    if resource_filter and not any(cost.resource_id == resource_filter for cost in action.costs):
                        raise ValueError(f'source talent resource {resource_filter} unavailable: {action.id}')
                    new_costs = tuple(ResourceCost(resource_id=cost.resource_id,
                        amount=max(0.0, float(cost.amount) + float(modifier.value))
                        if not resource_filter or cost.resource_id == resource_filter else float(cost.amount))
                        for cost in action.costs)
                    after = float(sum(cost.amount for cost in new_costs))
                    actions[index] = replace(action, costs=new_costs, provenance=action.provenance + ({
                        "stage": "talent_modifier", "talent_id": talent_id, "rank": rank,
                        "kind": modifier.kind, "value": float(modifier.value), "before": before, "after": after,
                        "provenance": dict(modifier.provenance),
                    },))
                elif modifier.kind == 'crit_chance_pct':
                    delta=float(modifier.value)
                    effects=[]; changed=[]
                    for effect in action.effects:
                        if isinstance(effect, (DamageEffect, HealEffect)):
                            if isinstance(effect, HealEffect) and (
                                    float(effect.crit_multiplier) <= 1. or
                                    not any(str(f.get('source_url','')).startswith('https://')
                                        for f in effect.field_provenance.get('crit_multiplier',()))):
                                raise ValueError('HEAL_CRIT_MULTIPLIER_UNSOURCED')
                            old=float(effect.crit_chance_bonus)
                            effects.append(replace(effect,crit_chance_bonus=old+delta))
                            changed.append((old,old+delta))
                        elif isinstance(effect, PeriodicEffect) and effect.school.lower() != 'physical':
                            old=float(effect.crit_chance_bonus)
                            effects.append(replace(effect,crit_chance_bonus=old+delta))
                            changed.append((old,old+delta))
                        elif isinstance(effect, ResourceScaledDirectDamageEffect):
                            old=float(effect.crit_chance_bonus)
                            effects.append(replace(effect,crit_chance_bonus=old+delta))
                            changed.append((old,old+delta))
                        elif isinstance(effect, WeaponDamageEffect):
                            old=float(effect.crit_chance_on_landed_hit)
                            effects.append(replace(effect,crit_chance_on_landed_hit=min(1.0,old+delta)))
                            changed.append((old,min(1.0,old+delta)))
                        else:
                            effects.append(effect)
                    if not changed:
                        raise ValueError(f'crit chance modifier target has no supported crittable effect: {action.id}')
                    actions[index]=replace(action,effects=tuple(effects),provenance=action.provenance+({
                        'stage':'talent_modifier','talent_id':talent_id,'rank':rank,
                        'kind':modifier.kind,'value':delta,'source':dict(modifier.provenance)},))
                    before=sum(x[0] for x in changed);after=sum(x[1] for x in changed)
                elif modifier.kind == 'critical_damage_bonus_pct':
                    # The tooltip increases the crit *bonus*. A 2x base crit
                    # becomes 3x with +100% bonus; non-critical base is intact.
                    changes=[];effects=[]
                    for effect in action.effects:
                        if isinstance(effect,(DamageEffect,PeriodicEffect,
                                              WeaponDamageEffect,ResourceScaledDirectDamageEffect)):
                            if modifier.target_id == 'melee_ability' and (
                                    isinstance(effect,PeriodicEffect) or
                                    str(effect.school).lower() != 'physical'):
                                effects.append(effect);continue
                            if (modifier.target_type=='action_filter' and
                                modifier.target_id.startswith('damage_schools:') and
                                effect.school.lower() not in set(modifier.target_id.split(':',1)[1].split(','))):
                                effects.append(effect);continue
                            old=float(effect.crit_multiplier)
                            if old<1.0:raise ValueError('invalid critical damage multiplier')
                            new=1.0+(old-1.0)*(1.0+float(modifier.value))
                            effects.append(replace(effect,crit_multiplier=new))
                            changes.append((old,new))
                        else:effects.append(effect)
                    if not changes:raise ValueError(f'critical damage talent has no crittable effect: {action.id}')
                    before=sum(x[0] for x in changes);after=sum(x[1] for x in changes)
                    actions[index]=replace(action,effects=tuple(effects),
                        provenance=action.provenance+({'stage':'talent_modifier',
                        'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                        'value':float(modifier.value),'before':before,'after':after,
                        'provenance':dict(modifier.provenance)},))
                elif modifier.kind == "effect_damage_pct": 
                    factor = max(0.0, 1.0 + float(modifier.value))
                    changed = []
                    effects = []
                    for effect in action.effects:
                        if modifier.target_type == 'action_filter' and modifier.target_id.startswith('damage_schools:'):
                            allowed = set(modifier.target_id.split(':',1)[1].split(','))
                            if not hasattr(effect,'school') or effect.school.lower() not in allowed:
                                effects.append(effect)
                                continue
                        if isinstance(effect, DamageEffect):
                            changed.append((float(effect.base_min + effect.base_max)/2.0,
                                            float(effect.base_min + effect.base_max)/2.0 * factor))
                            effects.append(replace(effect, base_min=effect.base_min*factor,
                                base_max=effect.base_max*factor,
                                spell_power_coefficient=effect.spell_power_coefficient*factor))
                        elif isinstance(effect, WeaponDamageEffect):
                            # Both the weapon component and flat bonus must scale;
                            # changing only weapon_damage_multiplier would be wrong.
                            changed.append((float(effect.weapon_damage_multiplier),
                                            float(effect.weapon_damage_multiplier)*factor))
                            effects.append(replace(effect,
                                weapon_damage_multiplier=effect.weapon_damage_multiplier*factor,
                                flat_damage=effect.flat_damage*factor))
                        elif isinstance(effect, PeriodicEffect):
                            changed.append((float(effect.total_base_damage), float(effect.total_base_damage)*factor))
                            effects.append(replace(effect, total_base_damage=effect.total_base_damage*factor,
                                spell_power_coefficient_per_tick=effect.spell_power_coefficient_per_tick*factor))
                        elif isinstance(effect, ResourceScaledPeriodicEffect):
                            before_value = float(sum(effect.total_base_damage_by_resource_amount.values()))
                            changed.append((before_value,before_value*factor))
                            effects.append(replace(effect,total_base_damage_by_resource_amount={
                                k:float(v)*factor for k,v in effect.total_base_damage_by_resource_amount.items()}))
                        elif isinstance(effect, ResourceScaledDirectDamageEffect):
                            changed.append((float(sum(effect.base_min_by_resource_amount.values())),
                                            float(sum(effect.base_min_by_resource_amount.values()))*factor))
                            effects.append(replace(effect,
                                base_min_by_resource_amount={k:float(v)*factor for k,v in effect.base_min_by_resource_amount.items()},
                                base_max_by_resource_amount={k:float(v)*factor for k,v in effect.base_max_by_resource_amount.items()},
                                attack_power_coefficient_per_resource=effect.attack_power_coefficient_per_resource*factor))
                        else:
                            effects.append(effect)
                    if not changed:
                        raise ValueError(f"talent modifier target has no supported damage effect: {action.id}")
                    before = float(sum(x[0] for x in changed))
                    after = float(sum(x[1] for x in changed))
                    actions[index] = replace(action, effects=tuple(effects), provenance=action.provenance + ({
                        "stage": "talent_modifier", "talent_id": talent_id, "rank": rank,
                        "kind": modifier.kind, "value": float(modifier.value), "before": before, "after": after,
                        "provenance": dict(modifier.provenance),
                    },))
                elif modifier.kind in ('effect_periodic_pct','effect_healing_pct'):
                    factor = max(0.0,1.0+float(modifier.value))
                    before = after = 0.0
                    changed_effects = []
                    for effect in action.effects:
                        if modifier.kind == 'effect_periodic_pct' and isinstance(effect, PeriodicEffect):
                            before += effect.total_base_damage
                            after += effect.total_base_damage*factor
                            effect = replace(effect,total_base_damage=effect.total_base_damage*factor,
                                spell_power_coefficient_per_tick=effect.spell_power_coefficient_per_tick*factor)
                        elif modifier.kind == 'effect_periodic_pct' and isinstance(effect, ResourceScaledPeriodicEffect):
                            old = sum(effect.total_base_damage_by_resource_amount.values())
                            before += old; after += old*factor
                            effect = replace(effect,total_base_damage_by_resource_amount={
                                k:float(v)*factor for k,v in effect.total_base_damage_by_resource_amount.items()})
                        elif modifier.kind in ('effect_periodic_pct','effect_healing_pct') and isinstance(effect, PeriodicHealEffect):
                            before += effect.total_base_heal; after += effect.total_base_heal*factor
                            effect = replace(effect,total_base_heal=effect.total_base_heal*factor,
                                spell_power_coefficient_per_tick=effect.spell_power_coefficient_per_tick*factor)
                        elif modifier.kind == 'effect_healing_pct' and isinstance(effect, HealEffect):
                            old = (effect.base_min+effect.base_max)/2.0
                            before += old; after += old*factor
                            effect = replace(effect,base_min=effect.base_min*factor,
                                base_max=effect.base_max*factor,
                                spell_power_coefficient=effect.spell_power_coefficient*factor)
                        changed_effects.append(effect)
                    if before == 0.0 and after == 0.0:
                        raise ValueError(f'talent modifier has no matching effects: {action.id}')
                    actions[index] = replace(action,effects=tuple(changed_effects),
                        provenance=action.provenance+({'stage':'talent_modifier',
                            'talent_id':talent_id,'rank':rank,'kind':modifier.kind,
                            'value':float(modifier.value),'before':before,'after':after,
                            'provenance':dict(modifier.provenance)},))
                else:
                    raise ValueError(f"unsupported talent modifier kind: {modifier.kind}")
                applied.append({
                    "talent_id": talent_id, "rank": rank, "action_id": action.id,
                    "kind": modifier.kind, "value": float(modifier.value), "before": before, "after": after,
                })
            if (modifier.kind == 'crit_chance_pct' and modifier.target_type == 'action_filter'
                    and modifier.target_id == 'spells_and_melee'):
                for index, attack in enumerate(auto_attacks):
                    if attack.owner_actor_id != actor.id or attack.attack_type != 'melee':
                        continue
                    before=float(attack.crit_chance_on_landed_hit)
                    after=min(1.0,before+float(modifier.value))
                    auto_attacks[index]=replace(attack,crit_chance_on_landed_hit=after,
                        provenance=attack.provenance+({'stage':'talent_modifier','talent_id':talent_id,
                        'rank':rank,'kind':modifier.kind,'source':dict(modifier.provenance)},))
                    applied.append({'talent_id':talent_id,'rank':rank,'auto_attack_id':attack.id,
                        'kind':modifier.kind,'before':before,'after':after})
                    matched=True
            # "All damage you deal" includes auto-attacks, not just button
            # actions. Scale the source DPS and AP components together via the
            # generic damage multiplier; don't double-count in the scorer.
            if (modifier.target_type == 'action_filter' and
                    modifier.target_id == 'all_damage' and
                    modifier.kind == 'effect_damage_pct'):
                factor = max(0.0, 1.0 + float(modifier.value))
                for index, attack in enumerate(auto_attacks):
                    if attack.owner_actor_id != actor.id:
                        continue  # A player's modifier is not a pet/group buff.
                    before = float(attack.damage_source.damage_multiplier)
                    auto_attacks[index] = replace(attack,
                        damage_source=replace(attack.damage_source,
                            damage_multiplier=before*factor),
                        provenance=attack.provenance + ({
                            'stage':'talent_modifier','talent_id':talent_id,
                            'rank':rank,'kind':modifier.kind,'value':float(modifier.value),
                            'before':before,'after':before*factor,
                            'source':dict(modifier.provenance)},))
                    applied.append({'talent_id':talent_id,'rank':rank,
                        'auto_attack_id':attack.id,'kind':modifier.kind,
                        'before':before,'after':before*factor})
                    matched = True
            if not matched:
                raise ValueError(f"talent modifier target action family not present: {modifier.target_id}")

    # Every action controlled by a sourced talent remains represented in
    # canonical IR but is executable only when that talent is selected.
    locked = {family for family, tid in gated_families.items()
              if int(normalized.get(tid, 0)) == 0}
    if locked:
        actions = [a for a in actions if a.family_key not in locked]
        ids = {a.id for a in actions}
        modes = [replace(mode, enabled_action_ids=tuple(
            action_id for action_id in mode.enabled_action_ids if action_id in ids))
            for mode in modes]

    application = TalentApplication(
        selection=normalized,
        available_points=available_talent_points(level, bonus_talent_points=bonus_talent_points),
        spent_points=sum(normalized.values()),
        applied_modifiers=tuple(applied),
    )
    return replace(
        ir_slice,
        id=f"{ir_slice.id}:talents",
        actor=actor, resources=tuple(resources), actions=tuple(actions),
        auto_attacks=tuple(auto_attacks), triggers=tuple(triggers), modes=tuple(modes),
        unsupported_semantics=tuple(unsupported),
        provenance={**dict(ir_slice.provenance), "talent_application": application.as_dict()},
    ), application

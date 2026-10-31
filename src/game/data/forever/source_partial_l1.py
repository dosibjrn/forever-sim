"""Isolated L1-partial source-atom execution THROUGH the existing Game CombatRuntime.

Not a second combat model: derive an incomplete ActionDefinition from source atoms
and execute it with the same generic runtime, explicitly in an isolated probe.
The action is NEVER attached to the production GameIRSlice or legal L2 search.
Unknown SP coefficients, secondary effects, acquisition, mode and GCD remain
blockers. These L1 measurements are **isolated effect fragments**, never s/mob.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import re
import sqlite3
from typing import Any

from src.game.data.forever.source_effect_atoms import read_effect_atom_coverage
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import ActionDefinition, DamageEffect, HealEffect, ResourceChangeEffect, ResourceCost, WeaponDamageEffect, PeriodicEffect
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import execute_action

_NUMBER = r'(\d+(?:\.\d+)?)'
_COST = re.compile(r'^' + _NUMBER + r' (Mana|Rage|Energy|Focus)$', re.I)
_CAST = re.compile(r'^' + _NUMBER + r' sec cast$', re.I)
_INDEX_AURA_DURATION = re.compile(r'\b(?:for|Lasts)\s+(\d+(?:\.\d+)?)\s+(sec(?:onds?)?|min(?:utes?)?|hours?)\b',re.I)
_ABSORB_DURATION = re.compile(r'\bLasts\s+(\d+(?:\.\d+)?)\s+(sec(?:onds?)?|min(?:utes?)?)\b',re.I)


class PartialSourceEvidenceError(ValueError):
    pass


def partial_source_action(ir, *, class_key: str, spell_id: int, db_path: Path | str = DEFAULT_DB,
                          execution_tier: str = 'L1', fragment_kind: str = 'direct_damage') -> tuple[ActionDefinition, dict[str, Any]]:
    """Compile one selected *fragment*. L2 is forbidden even for full-looking text.

    Caller-supplied IR must be the project's existing source IR. A missing or
    stale source, absent cost/cast, insufficient actor resource or ambiguous
    effects produces a blocker; it must never be treated as a free attack.
    """
    if execution_tier != 'L1':
        raise PartialSourceEvidenceError('PARTIAL_SOURCE_ACTION_FORBIDDEN_AT_L2_OR_L3')
    if ir is None:
        raise PartialSourceEvidenceError('NO_EXISTING_GAME_IR_SLICE')
    db = Path(db_path)
    with sqlite3.connect(f'file:{db.resolve()}?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        row = con.execute('''SELECT class_key,spell_id,name,level_hint,source_url,raw_listview_json
            FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities' ''',
            (str(class_key).lower(),int(spell_id))).fetchone()
        if row is None:
            raise PartialSourceEvidenceError('UNKNOWN_SOURCE_ABILITY_ID')
        proof = read_effect_atom_coverage(con,class_key=str(class_key).lower(),spell_id=spell_id)
        if proof is None or not proof['atoms']:
            raise PartialSourceEvidenceError('NO_VERIFIED_SOURCE_FRAGMENT')
        if proof['execution_status'] != 'BLOCKED_PARTIAL_EFFECT_EVIDENCE' or not proof['not_legal_for_L2']:
            raise PartialSourceEvidenceError('SOURCE_FRAGMENT_PROOF_STATUS_MISMATCH')
        raw=json.loads(row['raw_listview_json'])
        tooltip=(raw.get('envChange') or {}).get('after') or {}
        cost_text=str(tooltip.get('cost') or '').strip()
        cast_text=str(tooltip.get('cast') or '').strip()
        cost=_COST.fullmatch(cost_text)
        cast=_CAST.fullmatch(cast_text)
        cast_s=(0.0 if cast_text.lower()=='instant' else float(cast.group(1)) if cast else None)
        cost_amount=(float(cost.group(1)) if cost else None)
        cost_resource=(cost.group(2).lower() if cost else None)
        header_authority='source_index_listview'
        if cast_s is None or cost_amount is None:
            # Missing listview tooltip is NOT a zero-cost or instant spell.
            # Reuse the existing SHA-verified structured detail ledger when
            # present; otherwise block rather than inventing a source fact.
            from .source_verified_detail_effects import read_current_effects
            from .source_verified_detail_headers import read_current_header
            verified_header=read_current_header(con,class_key=str(class_key).lower(),spell_id=int(spell_id))
            verified_effects=read_current_effects(con,class_key=str(class_key).lower(),spell_id=int(spell_id))
            if verified_header is None or verified_effects is None:
                raise PartialSourceEvidenceError('UNSUPPORTED_OR_MISSING_SOURCE_COST_CAST')
            verified_cost=verified_effects['headers'].get('Cost','')
            verified_cast=verified_effects['headers'].get('Cast time','')
            parsed_cost=_COST.fullmatch(verified_cost)
            if verified_cost=='None':
                cost_amount=0.0;cost_resource=None
            elif parsed_cost is not None:
                cost_amount=float(parsed_cost.group(1))
                cost_resource=parsed_cost.group(2).lower()
            else:
                raise PartialSourceEvidenceError('UNSUPPORTED_VERIFIED_RESOURCE_COST')
            if verified_cast=='Instant':cast_s=0.0
            else:
                parsed_cast=re.fullmatch(r'(\d+(?:\.\d+)?) seconds?',verified_cast)
                if parsed_cast is None:
                    raise PartialSourceEvidenceError('UNSUPPORTED_VERIFIED_CAST_TIME')
                cast_s=float(parsed_cast.group(1))
            header_authority='verified_spell_detail_sha256:'+verified_effects['detail_html_sha256']
        if row['level_hint'] is None or int(row['level_hint']) < 1:
            raise PartialSourceEvidenceError('UNKNOWN_INDEXED_LEVEL')
        if int(row['level_hint']) > int(ir.actor.metadata.get('level', -1)):
            raise PartialSourceEvidenceError('SOURCE_RANK_EXCEEDS_ACTOR_LEVEL')
        owned={x.id for x in ir.resources if x.owner_actor_id == ir.actor.id}
        if cost_resource is not None and cost_resource not in owned:
            raise PartialSourceEvidenceError('SOURCE_RESOURCE_NOT_PRESENT_IN_IR')
        # The selector chooses a source-observed *fragment*, not a spell type.
        # A source action can contain several independent effects; all other
        # atoms and the residual remain explicit blockers for L2/L3.
        atom_kinds={
            'direct_damage':('school_damage_range','school_damage_fixed'),
            'direct_heal':('healing_range',),
            'resource_gain':('resource_gain',),
            'weapon_multiplier':('weapon_damage_multiplier',),
            'periodic_total':('periodic_school_damage','periodic_damage'),
            'damage_absorption':('damage_absorption',),
            'actor_attack_power_aura':('actor_attack_power_increase',),
            'target_armor_debuff':('target_armor_reduction',),
            'weapon_flat_bonus':('weapon_damage_plus','weapon_multiplier_plus'),
        }
        if fragment_kind not in atom_kinds:
            raise PartialSourceEvidenceError('UNSUPPORTED_L1_FRAGMENT_KIND')
        hits=[a for a in proof['atoms'] if a['kind'] in atom_kinds[fragment_kind]]
        if len(hits)!=1:
            raise PartialSourceEvidenceError('REQUIRES_EXACTLY_ONE_SELECTED_SOURCE_FRAGMENT')
        hit=hits[0]
        vals=hit['values']
        source={'source_spell_id':int(spell_id),'url':row['source_url'],
                'source_authority':proof['source_authority'],
                'listview_sha256':hashlib.sha256(row['raw_listview_json'].encode()).hexdigest(),
                'fragment_text':hit['source_text'],
                'cost_cast_authority':header_authority}
        unknown=({'semantic':'spell_power_coefficient','status':'unknown_not_zero'},
                 {'semantic':'crit_hit_armor_resistance_and_other_effects','status':'unknown'},
                 {'semantic':'gcd_mode_and_acquisition','status':'unknown'},
                 {'semantic':'remaining_tooltip','status':'incomplete','value':proof['residual_text']},
                 {'semantic':'absorb_school_scope_and_interrupt_immunity',
                  'status':'unknown_for_listview_only'} if fragment_kind=='damage_absorption' else
                 {'semantic':'remaining_source_mechanics','status':'incomplete'})
        if fragment_kind == 'direct_damage':
            low=float(vals['min'] if hit['kind']=='school_damage_range' else vals['amount'])
            high=float(vals['max'] if hit['kind']=='school_damage_range' else vals['amount'])
            effect=DamageEffect(effect_type='damage',school=vals['school'],target='enemy',
                base_min=low,base_max=high,spell_power_coefficient=0.0,
                field_provenance={'source':(source,)},unsupported_semantics=unknown)
        elif fragment_kind == 'direct_heal':
            if 'health' not in owned:
                raise PartialSourceEvidenceError('SOURCE_IR_HAS_NO_HEALTH_RESOURCE')
            # Isolated self-heal probe. Actual target selection, overheal,
            # spell coefficient and secondary mechanics remain unknown.
            effect=HealEffect(effect_type='heal',target='self',resource_id='health',
                base_min=float(vals['min']),base_max=float(vals['max']),
                spell_power_coefficient=0.0,
                field_provenance={'source':(source,)},unsupported_semantics=unknown)
        elif fragment_kind == 'damage_absorption':
            from src.game.model.ir import StatusAuraEffect
            tooltip_text=str(tooltip.get('text') or '')
            duration_match=_ABSORB_DURATION.search(tooltip_text)
            duration=(float(duration_match[1])*(60 if duration_match[2].lower().startswith('min') else 1)
                      if duration_match is not None else None)
            amount=float(vals['amount'])
            # Structured, independently verified spell detail supersedes an
            # index-change tooltip (which can contain older/different values).
            # The fallback is still L1-only, never an acquisition assertion.
            from .source_verified_detail_effects import read_current_effects
            detailed=read_current_effects(con,class_key=str(class_key).lower(),spell_id=int(spell_id))
            if detailed is not None:
                matches=[e for e in detailed['effects'] if e['kind']=='absorb_all_schools']
                if len(matches)!=1:
                    raise PartialSourceEvidenceError('VERIFIED_ABSORB_EFFECT_MISSING_OR_AMBIGUOUS')
                amount=float(matches[0]['values']['amount'])
                duration=float(matches[0]['values']['duration_s'])
                source['absorb_capacity_authority']='verified_detail_sha256:'+detailed['detail_html_sha256']
            elif duration is None:
                raise PartialSourceEvidenceError('SOURCE_ABSORB_DURATION_NOT_OBSERVED')
            else:
                source['absorb_capacity_authority']='source_index_listview_only'
            if not (0<duration<=3600 and amount>=0):
                raise PartialSourceEvidenceError('INVALID_SOURCE_ABSORB_VALUE_OR_DURATION')
            effect=StatusAuraEffect(effect_type='status_aura',
                aura_id=f'L1_INDEX_ABSORB:{class_key}:{spell_id}',target='self',
                duration_s=duration,actor_absorb_amount=amount)
        elif fragment_kind in ('actor_attack_power_aura','target_armor_debuff'):
            # Duration must be explicitly present in the source text, never
            # guessed from rank, spell name or a class-specific duration.
            # More than one duration is ambiguous and fails closed.
            from src.game.model.ir import StatusAuraEffect, TargetStatDebuffEffect
            duration_hits=_INDEX_AURA_DURATION.findall(str(tooltip.get('text') or ''))
            unique_durations=set((float(n),u.lower()) for n,u in duration_hits)
            if len(unique_durations)!=1:
                raise PartialSourceEvidenceError('SOURCE_INDEX_AURA_DURATION_MISSING_OR_AMBIGUOUS')
            n,unit=next(iter(unique_durations))
            duration=n*(3600 if unit.startswith('hour') else 60 if unit.startswith('min') else 1)
            if duration<=0 or float(vals['amount'])<=0:
                raise PartialSourceEvidenceError('INVALID_SOURCE_INDEX_AURA_VALUE_OR_DURATION')
            if fragment_kind=='actor_attack_power_aura':
                # The source may describe a party/weapon/target buff, not
                # guaranteed self-buff. Actor is an explicit L1 probe target.
                effect=StatusAuraEffect(effect_type='status_aura',
                    aura_id=f'L1_INDEX_AP:{class_key}:{spell_id}',target='self',
                    duration_s=duration,actor_stat_deltas={'attack_power':float(vals['amount'])})
            else:
                # First application only: stacking, armor floor and hit
                # probability remain outside this partial fragment probe.
                effect=TargetStatDebuffEffect(effect_type='target_stat_debuff',
                    aura_id=f'L1_INDEX_ARMOR:{class_key}:{spell_id}',
                    target_stat_id='armor',delta=-float(vals['amount']),
                    duration_s=duration,provenance=(source,))
        elif fragment_kind == 'weapon_flat_bonus':
            # The source supplies the FLAT bonus only. The weapon baseline
            # is an existing IR scenario, not claimed to be acquired gear.
            attacks=[a for a in ir.auto_attacks if a.owner_actor_id==ir.actor.id
                     and a.school=='physical']
            if len(attacks)!=1:
                raise PartialSourceEvidenceError('AMBIGUOUS_SOURCE_IR_WEAPON_FOR_L1_PROBE')
            weapon=attacks[0]
            effect=WeaponDamageEffect(effect_type='weapon_damage',school='physical',
                target='enemy',damage_source=weapon.damage_source,
                weapon_damage_time_s=float(weapon.swing_time_s),
                weapon_damage_multiplier=float(vals.get('percent',100))/100.0,flat_damage=float(vals['amount']),
                provenance=({**source,'source_ir_weapon_id':weapon.id,
                    'weapon_base_is_qualified_provider_scenario_not_named_gear':True},),
                metadata={'L1_ONLY_UNVERIFIED_WEAPON_REQUIREMENTS':True})
        elif fragment_kind == 'periodic_total':
            # Only total damage and duration are source-observed. Tick interval,
            # scaling, refresh behavior, target legality and school (if absent)
            # are unknown. A ONE-terminal-tick integral probe is NOT game DoT
            # timing and must never be used by L2/L3 or policy optimization.
            duration=float(vals['duration_s'])
            if duration<=0:
                raise PartialSourceEvidenceError('INVALID_SOURCE_PERIODIC_DURATION')
            school=str(vals.get('school') or 'unverified')
            effect=PeriodicEffect(effect_type='periodic_damage',school=school,target='enemy',
                aura_id=f'L1_INTEGRAL_ONLY:{class_key}:{spell_id}',
                total_base_damage=float(vals['amount']),duration_s=duration,
                tick_interval_s=duration,spell_power_coefficient_per_tick=0.0,
                field_provenance={'source':(source,)},unsupported_semantics=unknown+(
                    {'semantic':'periodic_tick_interval_and_distribution',
                     'status':'UNKNOWN_ONE_TERMINAL_TICK_L1_PROXY_NOT_GAME_FACT'},
                    {'semantic':'periodic_school',
                     'status':('source_explicit' if 'school' in vals else 'UNKNOWN_PHYSICAL_L1_PROXY')},))
        elif fragment_kind == 'resource_gain':
            gain_resource=str(vals['resource'])
            if gain_resource not in owned:
                raise PartialSourceEvidenceError('SOURCE_GAIN_RESOURCE_NOT_PRESENT_IN_IR')
            # Only the isolated gain event is probed. Trigger conditions and
            # action legality are not inferred from the atom.
            effect=ResourceChangeEffect(effect_type='resource_change',
                resource_id=gain_resource,target='self',operation='add',
                amount=float(vals['amount']))
        else:
            # A sourced percent alone cannot establish a named weapon, behind
            # target requirement, equipped dagger, swing normalization or hit.
            # A single player-owned source-IR auto attack supplies ONLY an
            # explicitly qualified L1 base-damage probe. Multiple possible
            # forms/weapons are ambiguous and are never guessed.
            attacks=[a for a in ir.auto_attacks if a.owner_actor_id==ir.actor.id]
            if len(attacks)!=1:
                raise PartialSourceEvidenceError('AMBIGUOUS_SOURCE_IR_WEAPON_FOR_L1_PROBE')
            weapon=attacks[0]
            if weapon.school!='physical':
                raise PartialSourceEvidenceError('SOURCE_IR_WEAPON_SCHOOL_NOT_PHYSICAL')
            effect=WeaponDamageEffect(effect_type='weapon_damage',school='physical',
                target='enemy',damage_source=weapon.damage_source,
                weapon_damage_time_s=float(weapon.swing_time_s),
                weapon_damage_multiplier=float(vals['percent'])/100.0,
                provenance=({**source,'source_ir_weapon_id':weapon.id,
                    'weapon_base_is_qualified_provider_scenario_not_named_gear':True},),
                metadata={'L1_ONLY_UNVERIFIED_WEAPON_REQUIREMENTS':True})
        action=ActionDefinition(id=f'L1_PARTIAL_SOURCE:{spell_id}:{fragment_kind}',family_key=f'source_partial:{spell_id}',
            name=row['name'],owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(row['level_hint'])},),
            costs=(() if cost_resource is None else (ResourceCost(resource_id=cost_resource,amount=cost_amount),)),
            cast_time_s=cast_s,gcd_s=0.0,cooldown_s=0.0,effects=(effect,),
            provenance=(source,),metadata={'execution_tier':'L1_PARTIAL_ONLY',
                'source_spell_id':int(spell_id),'never_l2_legal':True,
                'fragment_kind':fragment_kind,
                'gcd_is_unknown_probed_zero_only':'not_source_game_fact',
                'spell_power_is_zero_probe_only':'not_source_game_fact',
                'all_remaining_mechanics_blocked':True,
                'weapon_base_is_proxy':fragment_kind in ('weapon_multiplier','weapon_flat_bonus'),
                'periodic_timing_is_proxy':fragment_kind=='periodic_total',
                'periodic_total_is_source_observed':fragment_kind=='periodic_total',
            'absorb_capacity_source_observed_duration_listview_only':fragment_kind=='damage_absorption',
                'stat_target_and_stacking_are_L1_proxies':fragment_kind in ('actor_attack_power_aura','target_armor_debuff')})
        return action,{'source_spell_id':int(spell_id),'class_key':str(class_key).lower(),
            'source_authority':proof['source_authority'],'unknown_mechanics':unknown,
            'source_fragment':hit['source_text'],'partial_not_l2':True,
            'fragment_kind':fragment_kind,'source_atom_kind':hit['kind'],
            'rank_required_level':int(row['level_hint'])}


def probe_l1_source_fragment(ir, *, class_key: str, spell_id: int,
                             db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1',
                             fragment_kind: str = 'direct_damage') -> dict:
    """Isolated zero-SP base-value probe, using existing CombatRuntime.

    Deliberately ignores mode permissions/acquisition, *never* feeds result to
    legal gear/policy/routing. An IR resource and sufficient mana are required.
    """
    action,evidence=partial_source_action(ir,class_key=class_key,spell_id=spell_id,
        db_path=db_path,execution_tier=execution_tier,fragment_kind=fragment_kind)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    # Probe resource availability must be real according to source IR, not
    # created from thin air or balanced around the chosen spell.
    for cost in action.costs:
        if not actor.can_spend(cost.resource_id,cost.amount):
            raise PartialSourceEvidenceError('NOT_ENOUGH_CANONICAL_IR_RESOURCE_FOR_ISOLATED_PROBE')
    target=TargetState.with_health('L1_partial_probe_target',1_000_000.0,
        **({'armor':1000.0,'spell_hit':1.0} if fragment_kind=='target_armor_debuff' else {}))
    result=execute_action(action=action,actor=actor,target=target,
        spell_power=0.0,allow_source_partial_l1=True)
    heals=[e for e in result.events if e.kind=='Heal']
    gains=[e for e in result.events if e.kind=='ResourceChanged']
    return {**evidence,'action_id':action.id,'result_tier':'L1_PARTIAL_BASE_FRAGMENT_ONLY',
            'base_damage_observed':result.total_damage,
            'periodic_total_integral_proxy':fragment_kind=='periodic_total',
            'periodic_tick_count_not_source_verified':fragment_kind=='periodic_total',
            'base_healing_requested':sum(float(e.payload['amount']) for e in heals),
            'base_healing_restored':sum(float(e.payload['restored']) for e in heals),
            'base_resource_gain_requested':sum(float(e.payload['amount']) for e in gains),
            'base_resource_gain_actual':sum(float(e.payload['after'])-float(e.payload['before']) for e in gains),
            'events':len(result.events),
            'l1_actor_attack_power_delta':float(action.effects[0].actor_stat_deltas.get('attack_power',0)) if fragment_kind=='actor_attack_power_aura' else None,
            'l1_target_armor_delta':float(action.effects[0].delta) if fragment_kind=='target_armor_debuff' else None,
            'l1_weapon_flat_bonus':float(action.effects[0].flat_damage) if fragment_kind=='weapon_flat_bonus' else None,
            'runtime_kind':'existing_game_combat_runtime',
            'elapsed_s_excludes_unknown_GCD':result.elapsed_s,
            'resource_remaining':({c.resource_id:result.resources_after.get(c.resource_id) for c in action.costs}),
            'valid_for_l2_score':False,'accepted_checkpoints':0}


def bounded_actor_l1_probe_ir(*, class_key: str, level: int,
        db_path: Path | str = DEFAULT_DB):
    """Build an explicitly synthetic, L1-only rank-probe actor once per class.

    NEVER use this IR in L2/L3, gear/talent optimization or a world route.
    Resource quantities/stats are from the bounded provider level, not the
    requested level. This helper does not alter the production provider.
    """
    from src.game.data.forever.registry import (
        build_game_ir_slice, generic_source_level_bounds)
    if type(level) is not int or not 1 <= level <= 60:
        raise PartialSourceEvidenceError('INVALID_REQUESTED_SOURCE_RANK_LEVEL')
    ir=build_game_ir_slice(class_key=class_key,level=level,ability_db_path=db_path)
    if ir is not None:
        return ir,level,False
    bounds=generic_source_level_bounds(class_key)
    if bounds is None:
        raise PartialSourceEvidenceError('NO_REGISTERED_CLASS_SOURCE_PROVIDER')
    template_level=min(max(level,bounds[0]),bounds[1])
    ir=build_game_ir_slice(class_key=class_key,level=template_level,
                           ability_db_path=db_path)
    if ir is None:
        raise PartialSourceEvidenceError('NO_BOUNDED_SOURCE_ACTOR_TEMPLATE')
    ir=replace(ir,actor=replace(ir.actor,metadata={
        **ir.actor.metadata,'level':level,
        'L1_ONLY_ACTOR_LEVEL_PROXY_FROM':template_level,
        'L1_NOT_SOURCE_VALIDATED_ACTOR_AT_LEVEL':True}))
    return ir,template_level,True


def probe_l1_indexed_rank_with_bounded_actor(*, class_key: str, level: int,
        spell_id: int, fragment_kind: str = 'direct_damage',
        db_path: Path | str = DEFAULT_DB) -> dict:
    """Execute one partial source atom against a labeled bounded actor proxy.

    Rank's source level is checked, but acquisition and character-level stats
    are not established. No L2 or checkpoint eligibility is implied.
    """
    ir,template_level,proxy=bounded_actor_l1_probe_ir(
        class_key=class_key,level=level,db_path=db_path)
    r=probe_l1_source_fragment(ir,class_key=class_key,spell_id=spell_id,
                               fragment_kind=fragment_kind,db_path=db_path)
    return {**r,'requested_rank_level':level,
            'bounded_actor_template_level':template_level,
            'bounded_actor_level_proxy':proxy,
            'actor_resources_and_stats_not_level_validated':proxy,
            'valid_for_l2_score':False,'accepted_checkpoints':0}


def partial_verified_detail_action(ir, *, class_key: str, spell_id: int,
        slot: int, db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1'):
    """Run ONE SHA-verified spell-detail slot through the existing executor.

    Unlike listview's periodic-total proxy, this uses actual observed tick
    spacing and duration. Other effect slots, proc/crit/target/mode/gear,
    acquisition and refresh semantics remain explicit L2 blockers. No spell
    name or class-specific dispatch and no production IR action insertion.
    """
    from .source_verified_detail_effects import read_current_effects
    from .source_verified_detail_headers import read_current_header
    from src.game.model.ir import PeriodicHealEffect
    if execution_tier != 'L1':
        raise PartialSourceEvidenceError('VERIFIED_SLOT_L2_L3_FORBIDDEN')
    if ir is None:raise PartialSourceEvidenceError('NO_EXISTING_GAME_IR_SLICE')
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        source=read_current_effects(db,class_key=class_key,spell_id=spell_id)
        if source is None:raise PartialSourceEvidenceError('NO_VERIFIED_DETAIL_EFFECT_SLOTS')
        matching=[e for e in source['effects'] if e['slot']==slot]
        if len(matching)!=1:raise PartialSourceEvidenceError('UNKNOWN_VERIFIED_EFFECT_SLOT')
        chosen=matching[0];kind=chosen['kind']
        if kind not in ('periodic_damage','periodic_heal','direct_damage','resource_gain',
                        'absorb_all_schools','root_control','movement_slow','weapon_base',
                        'weapon_multiplier','weapon_bonus','normalized_weapon_bonus'):
            raise PartialSourceEvidenceError('UNSUPPORTED_VERIFIED_EFFECT_SLOT')
        header=read_current_header(db,class_key=class_key,spell_id=spell_id)
        if header is None:raise PartialSourceEvidenceError('NO_VERIFIED_SPELL_HEADER')
        raw=db.execute('SELECT name,level_hint FROM spell_index WHERE class_key=? AND spell_id=? AND kind=\'abilities\'',
                       (class_key,spell_id)).fetchone()
        if raw is None or raw['level_hint'] is None:
            raise PartialSourceEvidenceError('MISSING_VERIFIED_SOURCE_LEVEL')
        if int(raw['level_hint']) > int(ir.actor.metadata.get('level', -1)):
            raise PartialSourceEvidenceError('VERIFIED_RANK_EXCEEDS_ACTOR_LEVEL')
        cost=source['headers']['Cost']
        if cost=='None':resource=None;amount=0.0
        else:
            match=_COST.fullmatch(cost)
            if match is None:raise PartialSourceEvidenceError('UNKNOWN_VERIFIED_RESOURCE_COST')
            amount=float(match[1]);resource=match[2].lower()
        cast=source['headers']['Cast time']
        if cast=='Instant':cast_s=0.0
        else:
            match=re.fullmatch(r'(\d+(?:\.\d+)?) seconds?',cast)
            if match is None:raise PartialSourceEvidenceError('UNSUPPORTED_VERIFIED_CAST_TIME')
            cast_s=float(match[1])
        from .source_verified_detail_effects import _time as verified_time
        def observed_ready(value: str) -> float:
            if value in ('n/a','None'):return 0.0
            if re.fullmatch(r'0(?:\.0+)? seconds?',value):return 0.0
            parsed=verified_time(value)
            if parsed is None:raise PartialSourceEvidenceError('UNKNOWN_VERIFIED_READY_TIME')
            return parsed
        gcd_s=observed_ready(source['headers'].get('GCD',''))
        cooldown_s=observed_ready(source['headers'].get('Cooldown',''))
        owned={r.id for r in ir.resources if r.owner_actor_id==ir.actor.id}
        if resource is not None and resource not in owned:
            raise PartialSourceEvidenceError('MISSING_IR_COST_RESOURCE')
        if kind=='periodic_heal' and 'health' not in owned:
            raise PartialSourceEvidenceError('MISSING_IR_HEALTH_RESOURCE')
        if kind=='resource_gain' and chosen['values']['resource'] not in owned:
            raise PartialSourceEvidenceError('MISSING_IR_GAIN_RESOURCE')
        vals=chosen['values']
        proof={'source_spell_id':spell_id,'source_url':source['source_url'],
               'detail_html_sha256':source['detail_html_sha256'],
               'verified_effect_slot':slot,'effect_text':chosen['effect_text']}
        unknown=({'semantic':'other_effect_slots','status':'unmodeled',
                  'count':len(source['effects'])-1},
                 {'semantic':'acquisition_target_legality_mode_hit_crit_resist',
                  'status':'unknown'},
                 {'semantic':'level_scaling_and_refresh',
                  'status':'not_fully_source_verified_for_L2'})
        if kind in ('weapon_base','weapon_multiplier','weapon_bonus','normalized_weapon_bonus'):
            # This is an L1 source-IR weapon probe, not evidence of equipped
            # source-legal gear or normalized swing timing. Never select one
            # of several eligible attacks arbitrarily.
            attacks=[a for a in ir.auto_attacks if a.owner_actor_id==ir.actor.id
                     and a.school=='physical']
            if len(attacks)!=1:
                raise PartialSourceEvidenceError('AMBIGUOUS_SOURCE_IR_WEAPON_FOR_VERIFIED_L1')
            weapon=attacks[0]
            multiplier=(float(vals['percent'])/100 if kind=='weapon_multiplier' else
                        0.0 if kind=='normalized_weapon_bonus' else 1.0)
            bonus=float(vals.get('flat_bonus',0))
            effect=WeaponDamageEffect(effect_type='weapon_damage',school='physical',
                target='enemy',damage_source=weapon.damage_source,
                weapon_damage_time_s=float(weapon.swing_time_s),
                weapon_damage_multiplier=multiplier,flat_damage=bonus,
                provenance=({**proof,'source_ir_weapon_id':weapon.id,
                    'weapon_baseline_and_normalization_unverified_L1_proxy':True},),
                metadata={'L1_ONLY_UNVERIFIED_WEAPON_REQUIREMENTS':True})
        elif kind=='absorb_all_schools':
            from src.game.model.ir import StatusAuraEffect
            effect=StatusAuraEffect(effect_type='status_aura',
                aura_id=f'L1_VERIFIED:{class_key}:{spell_id}:{slot}',
                target='self',duration_s=vals['duration_s'],
                actor_absorb_amount=vals['amount'],
                actor_absorb_spell_power_coefficient=float(vals.get('spell_power_coefficient_per_tick_or_effect',0.0)))
        elif kind=='root_control':
            from src.game.model.ir import ControlEffect
            effect=ControlEffect(effect_type='control',control_id=vals['control_id'],
                target='enemy',duration_s=vals['duration_s'])
        elif kind=='movement_slow':
            from src.game.model.ir import TargetStatDebuffEffect
            effect=TargetStatDebuffEffect(effect_type='target_stat_debuff',
                aura_id=f'L1_VERIFIED_SLOW:{class_key}:{spell_id}:{slot}',
                target_stat_id='movement_speed',delta=vals['fractional_delta'],
                duration_s=vals['duration_s'],provenance=(proof,))
        elif kind=='resource_gain':
            effect=ResourceChangeEffect(effect_type='resource_change',
                resource_id=vals['resource'],target='self',operation='add',
                amount=vals['amount'])
        elif kind=='periodic_damage':
            effect=PeriodicEffect(effect_type='periodic_damage',
                school=vals['school'],target='enemy',
                aura_id=f'L1_VERIFIED:{class_key}:{spell_id}:{slot}',
                total_base_damage=vals['total_base'],duration_s=vals['duration_s'],
                tick_interval_s=vals['tick_interval_s'],
                spell_power_coefficient_per_tick=float(vals.get('spell_power_coefficient_per_tick_or_effect',0.0)),
                field_provenance={'source':(proof,)},unsupported_semantics=unknown)
        elif kind=='periodic_heal':
            effect=PeriodicHealEffect(effect_type='periodic_heal',
                target='self',resource_id='health',
                aura_id=f'L1_VERIFIED:{class_key}:{spell_id}:{slot}',
                total_base_heal=vals['total_base'],duration_s=vals['duration_s'],
                tick_interval_s=vals['tick_interval_s'],
                spell_power_coefficient_per_tick=float(vals.get('spell_power_coefficient_per_tick_or_effect',0.0)),
                field_provenance={'source':(proof,)},unsupported_semantics=unknown)
        else:
            effect=DamageEffect(effect_type='damage',school=vals['school'],target='enemy',
                base_min=vals['amount'],base_max=vals['amount'],
                spell_power_coefficient=float(vals.get('spell_power_coefficient_per_tick_or_effect',0.0)),
                field_provenance={'source':(proof,)},unsupported_semantics=unknown)
        action=ActionDefinition(id=f'L1_VERIFIED_SLOT:{class_key}:{spell_id}:{slot}',
            family_key=f'L1_verified:{spell_id}',name=raw['name'],
            owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(raw['level_hint'])},),
            costs=(() if resource is None else (ResourceCost(resource_id=resource,amount=amount),)),
            cast_time_s=cast_s,gcd_s=gcd_s,cooldown_s=cooldown_s,effects=(effect,),
            provenance=(proof,),metadata={'execution_tier':'L1_PARTIAL_ONLY',
                'never_l2_legal':True,'all_remaining_mechanics_blocked':True,
                'verified_source_effect_kind':kind,
                'verified_periodic_timing_not_integral_proxy':kind.startswith('periodic')})
        return action,{'source':proof,'kind':kind,'verified_tick_interval_s':vals.get('tick_interval_s'),
                       'verified_tick_count':vals.get('tick_count'),
                       'partial_not_l2':True,'source_gcd_s':gcd_s,
                       'source_cooldown_s':cooldown_s,'unknown_mechanics':unknown}


def probe_verified_detail_l1(ir, *, class_key: str, spell_id: int,
        slot: int, db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1') -> dict:
    action,evidence=partial_verified_detail_action(ir,class_key=class_key,
        spell_id=spell_id,slot=slot,db_path=db_path,execution_tier=execution_tier)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    for cost in action.costs:
        if not actor.can_spend(cost.resource_id,cost.amount):
            raise PartialSourceEvidenceError('INSUFFICIENT_SOURCE_IR_RESOURCE')
    result=execute_action(action=action,actor=actor,
        target=TargetState.with_health('L1_verified_detail_probe',1_000_000,
            **({'movement_speed':1.0,'spell_hit':1.0} if action.effects[0].effect_type=='target_stat_debuff' else {})),
        spell_power=0.0,allow_source_partial_l1=True)
    return {**evidence,'result_tier':'L1_PARTIAL_VERIFIED_SLOT_ONLY',
        'total_damage':result.total_damage,'events':len(result.events),
        'damage_event_times':[e.time_s for e in result.events if e.kind=='Damage'],
        'heal_event_times':[e.time_s for e in result.events if e.kind=='Heal'],
        'control_applied_count':sum(e.kind=='ControlApplied' for e in result.events),
        'movement_slow_L1_delta_at_application':sum(float(e.payload.get('effective_delta',0))
            for e in result.events if e.kind=='TargetStatDebuffApplied'
            and e.payload.get('applied') and e.payload.get('effective_delta',0)<0),
        'absorb_granted_amount':sum(float(e.payload['amount']) for e in result.events
                                     if e.kind=='AbsorbShieldGranted'),
        'valid_for_l2_score':False,'accepted_checkpoints':0}


def complete_verified_detail_l1_action(ir, *, class_key: str, spell_id: int,
        db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1'):
    """Compose *all* source-verified effect slots into ONE paid L1 cast.

    This is a generic, fail-closed bridge between WF311's source-slot ledger
    and the existing multi-effect ActionDefinition/CombatRuntime. A spell with
    even one unsupported slot is not partially executed under a complete
    action name. Costs, GCD and cast time are charged exactly once. Complete
    typed slots are NOT complete acquisition, hit, target or coefficient facts,
    so production L2/L3 and policy search remain explicitly prohibited.
    """
    if execution_tier != 'L1':
        raise PartialSourceEvidenceError('VERIFIED_COMPOSITE_L2_L3_FORBIDDEN')
    if ir is None:
        raise PartialSourceEvidenceError('NO_EXISTING_GAME_IR_SLICE')
    from .source_verified_detail_effects import read_current_effects
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        source=read_current_effects(db,class_key=class_key,spell_id=spell_id)
    if source is None:
        raise PartialSourceEvidenceError('NO_VERIFIED_DETAIL_EFFECT_SLOTS')
    weapon_kinds=frozenset(('weapon_base','weapon_multiplier','weapon_bonus','normalized_weapon_bonus'))
    missing=[(e['slot'],e['kind']) for e in source['effects']
             if e['kind'] not in ('direct_damage','periodic_damage','periodic_heal','resource_gain',
                                  'absorb_all_schools','root_control','movement_slow',*weapon_kinds)]
    if missing:
        raise PartialSourceEvidenceError('UNSUPPORTED_VERIFIED_COMPOSITE_SLOTS:'+repr(missing))
    if not source['effects']:
        raise PartialSourceEvidenceError('EMPTY_VERIFIED_COMPOSITE_SLOTS')
    # Delegate all atom compilation, SHA validation and legality checks to
    # WF311's established compiler. Never maintain a second effect dispatcher.
    compiled=[partial_verified_detail_action(ir,class_key=class_key,
              spell_id=spell_id,slot=e['slot'],db_path=db_path,
              execution_tier='L1') for e in source['effects']]
    base=compiled[0][0]
    for action,_ in compiled[1:]:
        if (action.owner_actor_id!=base.owner_actor_id or
            action.costs!=base.costs or action.cast_time_s!=base.cast_time_s or
            action.gcd_s!=base.gcd_s or action.cooldown_s!=base.cooldown_s or
            action.requirements!=base.requirements):
            raise PartialSourceEvidenceError('CONTRADICTORY_VERIFIED_COMPOSITE_HEADER')
    # Several structured weapon slots describe ONE hit. Summing each slot as
    # a separate damage event would double-charge weapon damage and overstate
    # combo-point attacks. Reduce by opcode role, independent of spell name.
    weapon_actions=[action for action,_ in compiled
                    if action.metadata.get('verified_source_effect_kind') in weapon_kinds]
    non_weapon=[effect for action,_ in compiled
                if action.metadata.get('verified_source_effect_kind') not in weapon_kinds
                for effect in action.effects]
    if weapon_actions:
        roles=[a.metadata['verified_source_effect_kind'] for a in weapon_actions]
        if (len(roles)!=len(set(roles)) or
            (len(roles)>1 and set(roles) != {'weapon_multiplier','normalized_weapon_bonus'})):
            raise PartialSourceEvidenceError('AMBIGUOUS_VERIFIED_WEAPON_SLOT_COMPOSITION')
        if roles==['normalized_weapon_bonus']:
            raise PartialSourceEvidenceError('MISSING_VERIFIED_WEAPON_BASELINE')
        weapons=[a.effects[0] for a in weapon_actions]
        if any(w.damage_source!=weapons[0].damage_source or
               w.weapon_damage_time_s!=weapons[0].weapon_damage_time_s
               for w in weapons[1:]):
            raise PartialSourceEvidenceError('CONTRADICTORY_VERIFIED_WEAPON_BASELINE')
        merged=replace(weapons[0],
            weapon_damage_multiplier=sum(w.weapon_damage_multiplier for w in weapons),
            flat_damage=sum(w.flat_damage for w in weapons),
            provenance=tuple(p for w in weapons for p in w.provenance),
            metadata={**weapons[0].metadata,
                'verified_weapon_slots_folded_into_one_hit':len(weapons)})
        # Preserve source ordering: weapon slot position, then other effects.
        first_weapon_index=next(i for i,(a,_) in enumerate(compiled)
                                if a.metadata.get('verified_source_effect_kind') in weapon_kinds)
        ordered=[]
        for i,(a,_) in enumerate(compiled):
            if i==first_weapon_index:ordered.append(merged)
            elif a.metadata.get('verified_source_effect_kind') not in weapon_kinds:
                ordered.extend(a.effects)
        effects=tuple(ordered)
    else:
        effects=tuple(non_weapon)
    proof={'source_spell_id':int(spell_id),'source_url':source['source_url'],
           'detail_html_sha256':source['detail_html_sha256'],
           'verified_slots':tuple(e['slot'] for e in source['effects']),
           'all_source_effect_slots_typed':True,
           'acquisition_target_coefficients_and_combat_legality':'UNVERIFIED'}
    action=replace(base,id=f'L1_VERIFIED_COMPOSITE:{class_key}:{spell_id}',
        effects=effects,provenance=(proof,),metadata={
            **base.metadata,'execution_tier':'L1_PARTIAL_ONLY',
            'never_l2_legal':True,'all_remaining_mechanics_blocked':True,
            'composite_effect_slots':len(effects),
            'one_cast_one_cost_one_gcd':True})
    return action,proof


def probe_verified_detail_composite_l1(ir, *, class_key: str, spell_id: int,
        db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1',
        spell_power: float = 0.0) -> dict:
    """Measured multi-slot L1 source cast, never a policy/L2 checkpoint."""
    from math import isfinite
    if not isfinite(float(spell_power)) or spell_power < 0:
        raise PartialSourceEvidenceError('INVALID_L1_PROBE_SPELL_POWER')
    action,proof=complete_verified_detail_l1_action(ir,class_key=class_key,
        spell_id=spell_id,db_path=db_path,execution_tier=execution_tier)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    for cost in action.costs:
        if not actor.can_spend(cost.resource_id,cost.amount):
            raise PartialSourceEvidenceError('INSUFFICIENT_SOURCE_IR_RESOURCE')
    result=execute_action(action=action,actor=actor,
        target=TargetState.with_health('L1_verified_composite_probe',1_000_000,
            **({'movement_speed':1.0,'spell_hit':1.0} if any(
                e.effect_type=='target_stat_debuff' for e in action.effects) else {})),
        spell_power=spell_power,allow_source_partial_l1=True)
    return {**proof,'result_tier':'L1_ALL_VERIFIED_SLOTS_ONE_CAST_NOT_L2',
        'total_damage':result.total_damage,'events':len(result.events),
        'damage_event_times':[e.time_s for e in result.events if e.kind=='Damage'],
        'heal_event_times':[e.time_s for e in result.events if e.kind=='Heal'],
        'control_applied_count':sum(e.kind=='ControlApplied' for e in result.events),
        'movement_slow_L1_delta_at_application':sum(float(e.payload.get('effective_delta',0))
            for e in result.events if e.kind=='TargetStatDebuffApplied'
            and e.payload.get('applied') and e.payload.get('effective_delta',0)<0),
        'absorb_granted_amount':sum(float(e.payload['amount']) for e in result.events
                                     if e.kind=='AbsorbShieldGranted'),
        'declared_cast_cost_once':{c.resource_id:c.amount for c in action.costs},
        'net_resource_delta_including_regen':{c.resource_id:result.resources_before.get(c.resource_id,0)-result.resources_after.get(c.resource_id,0)
                          for c in action.costs},
        'resource_after':dict(result.resources_after),
        'valid_for_l2_score':False,'accepted_checkpoints':0}

"""Generic canonical-SQLite-backed native class action compiler.

This module contains no class/spell/rank tables. A provider is only executable
where a versioned source row and a clearly qualified actor scenario exist.
Uncaptured actions remain coverage gaps, never implied no-ops.
"""
from __future__ import annotations
from dataclasses import replace
import json, sqlite3
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model import (ActionDefinition, ActorDefinition, AutoAttackDamageSource,
    AutoAttackDefinition, DamageEffect, GameIRSlice, HealEffect, ModeDefinition,
    PeriodicEffect, PolicyDefinition, PolicyRuleDefinition, PolicyCondition,
    ResourceCost, ResourceDefinition, WeaponDamageEffect)
from src.rulesets.forever.shared.defense import representative_player_hp


def build_source_slice(class_key: str, level: int):
    key=str(class_key).lower();level=int(level)
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM verified_native_class_scenarios WHERE class_key=?',(key,)).fetchone()
        if row is None or not int(row['min_level'])<=level<=int(row['max_level']):
            return None
        actions=db.execute('SELECT * FROM verified_native_class_actions WHERE class_key=? AND min_level<=? ORDER BY family_key,min_level DESC',(key,level)).fetchall()
        indexed=db.execute("SELECT COUNT(*) FROM spell_index WHERE class_key=? AND kind='abilities' AND (level_hint IS NULL OR level_hint<=?)",(key,level)).fetchone()[0]
    scenario=json.loads(row['mana_scenario_json']); auto=json.loads(row['auto_json'])
    if scenario['kind']=='pinned_class_level_fixture':
        from pathlib import Path
        p=Path(__file__).resolve().parents[4] / scenario['fixture']
        levels=json.loads(p.read_text())['classes'][key]['rows']
        matched=[x for x in levels if int(x['level'])==level]
        if len(matched)!=1:raise ValueError('missing pinned mana level')
        mana=float(matched[0]['base_mana'])
    elif scenario['kind']=='explicit_proxy':
        mana=float(scenario['base'])+level*float(scenario['per_level'])
    else:raise ValueError('unrecognized actor scenario')
    hp=float(representative_player_hp(level,0.))
    # A zero base attribute is NOT an assertion about a real naked character.
    # It allows source-backed equipment deltas to be executed without making
    # up a race-specific base stat.
    stats={'strength':0.,'agility':0.,'stamina':0.,'intellect':0.,'spell_power':0.,
           'attack_power':0.,'damage_multiplier':1.,'critical_strike_chance':0.}
    weapon_dps=float(auto['dps_proxy_base'])+level*float(auto['dps_proxy_per_level'])
    actor=ActorDefinition(id='player',actor_type='player',base_stats=stats,
        state_status='qualified_native_class_actor_scenario_not_final',
        provenance=({'authority':'scenario_proxy_not_source_backed','capture_id':row['capture_id']},),
        metadata={'class_key':key,'level':level,'race_key':None,
                  'weapon_speed_s':float(auto['swing_time_s']),
                  'base_stats_are_zero_proxy':True})
    resources=(ResourceDefinition(id='health',name='Health',owner_actor_id='player',
                    initial_amount=hp,capacity=hp,state_status='qualified_proxy_starting_state'),
               ResourceDefinition(id='mana',name='Mana',owner_actor_id='player',
                    initial_amount=mana,capacity=mana,
                    regeneration_per_s=float(scenario['regen_per_s']),
                    state_status='qualified_proxy_starting_state',
                    provenance=({'authority':scenario['authority']},),
                    metadata={'base_mana':mana,'mana_source_status':scenario['authority']}))
    mode=ModeDefinition(id='ordinary',label='Ordinary Weapon',initial=True,
        provenance=({'authority':'qualified_ordinary_weapon_mode','source_url':auto['source_url']},))
    source=AutoAttackDamageSource(kind='equipped_weapon_dps_plus_attack_power',
        flat_dps=weapon_dps,dps_stat_id=None,attack_power_stat_id='attack_power')
    attack=AutoAttackDefinition(id=f'{key}:auto:weapon',name='Qualified ordinary weapon auto',
        owner_actor_id='player',attack_type=auto['kind'],school='physical',
        required_mode_id='ordinary',swing_time_s=float(auto['swing_time_s']),
        damage_source=source,hit_chance=1.,exclusive_with_casts=bool(auto['exclusive_with_casts']),
        provenance=({'source_url':auto['source_url'],'capture_id':row['capture_id'],
                     'caveat':auto['caveat']},))
    newest={}
    for a in actions:
        if a['family_key'] not in newest:newest[a['family_key']]=a
    compiled=[]
    for family,a in sorted(newest.items()):
        effects=[]; ref=({'source_url':a['source_url'],'capture_id':a['capture_id'],
                         'caveats':json.loads(a['caveats_json'])},)
        for e in json.loads(a['effect_json']):
            if e['kind']=='direct_damage':
                effects.append(DamageEffect('damage',e['school'],'enemy',float(e['min']),float(e['max']),
                    spell_power_coefficient=float(e['spell_power_coefficient']),
                    field_provenance={'base_damage':ref}))
            elif e['kind']=='periodic_damage':
                effects.append(PeriodicEffect('periodic_damage',e['school'],'enemy',
                    f'{family}:{a["spell_id"]}:dot',float(e['total']),float(e['duration']),
                    float(e['tick']),field_provenance={'total_base_damage':ref},
                    unsupported_semantics=({'semantic':'periodic_can_crit','status':'not_verified'},)))
            elif e['kind']=='heal':
                effects.append(HealEffect('heal','actor','health',float(e['min']),float(e['max']),
                    spell_power_coefficient=float(e['spell_power_coefficient']),
                    field_provenance={'base_heal':ref}))
            elif e['kind']=='weapon_plus_holy':
                # Weapon and spell bonus are separate effects so SP scaling is
                # executable without conflating the weapon-damage coefficient.
                effects.append(WeaponDamageEffect('weapon_damage',e['school'],'enemy',
                    damage_source=source,weapon_damage_time_s=float(auto['swing_time_s']),
                    weapon_damage_multiplier=float(e['multiplier']),provenance=ref,
                    metadata={'normalized_weapon_speed_unverified':True}))
                effects.append(DamageEffect('damage',e['school'],'enemy',float(e['min']),float(e['max']),
                    spell_power_coefficient=float(e['spell_power_coefficient']),
                    field_provenance={'base_damage':ref,'spell_power_coefficient':ref}))
            else:raise ValueError(f'unimplemented canonical effect kind {e["kind"]}')
        compiled.append(ActionDefinition(id=f'{family}:{a["spell_id"]}',family_key=family,
            name=family.replace('_',' ').title(),owner_actor_id='player',
            requirements=({'kind':'minimum_level','value':int(a['min_level'])},
                          {'kind':'mode_is','value':'ordinary'}),
            costs=(ResourceCost('mana',float(a['cost'])),),
            cast_time_s=float(a['cast_s']),gcd_s=float(a['gcd_s']),cooldown_s=float(a['cooldown_s']),
            effects=tuple(effects),provenance=ref,
            metadata={'source_status':'verified_rank_with_explicit_caveats'}))
    if not compiled:raise ValueError('no verified executable source actions for native provider')
    damage_actions=[a for a in compiled if any(isinstance(e,(DamageEffect,PeriodicEffect,WeaponDamageEffect)) for e in a.effects)]
    if not damage_actions:raise ValueError('no source combat action')
    policies=(PolicyDefinition(id=f'{key}:source_seed',label='Sourced bounded priority seed',
        rules=tuple(PolicyRuleDefinition(f'seed:{a.family_key}',a.id) for a in damage_actions),
        provenance={'authority':'bounded_generic_source_seed_not_optimal'}),)
    base_ir=GameIRSlice(id=f'forever:{key}:L{level}:wf251',ruleset='forever',
        actor=actor,resources=resources,modes=(mode,),auto_attacks=(attack,),
        actions=tuple(compiled),policies=policies,
        source_facts=({'family':'native_sqlite_verified_actions','capture_id':row['capture_id'],
            'executed_families':sorted(newest),'indexed_actions_at_level':indexed,
            'indexed_unexecuted_count_at_least':max(0,indexed-len(actions))},),
        unsupported_semantics=({'code':'indexed_source_actions_not_yet_executable',
              'indexed_count':indexed,'verified_rank_rows':len(actions)},
             {'code':'pet_or_seal_and_other_class_mechanics_not_implemented',
              'status':'not_source_complete'},
             {'code':'starting_stats_and_weapon_speed','status':'qualified_proxy'}),
        provenance={'provider':'generic_sqlite_native_class_adapter',
            'capture_id':row['capture_id'],'source_coverage_complete':False,
            'numeric_scope':'bounded_native_source_level_with_proxy_state_not_leveling_authority'})

    from .source_companions import source_enrich_companions
    from .source_timed_auras import source_enrich_timed_auras
    return source_enrich_timed_auras(source_enrich_companions(base_ir))

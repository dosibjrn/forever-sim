"""Canonical SQLite -> reusable permanent companion Actor/Action/Auto/Link IR.

No class, spell, pet family or rank constants: a sourced family row is the
only way a pet can enter a source slice. Pet presence before each pull is an
explicit scenario assumption, not a proven free Call Pet or tame acquisition.
"""
from __future__ import annotations
from dataclasses import replace
import sqlite3
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model import (ActorDefinition,ActorLinkModifier,AutoAttackDefinition,
    AutoAttackDamageSource,ActionDefinition,DamageEffect,ResourceCost,
    ResourceDefinition,PolicyDefinition,PolicyRuleDefinition)


def source_enrich_companions(ir, *, db_path=DEFAULT_DB):
    key=str(ir.actor.metadata.get('class_key') or '')
    level=int(ir.actor.metadata['level'])
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        try:
            families=db.execute('''SELECT * FROM companion_family_source_facts
                WHERE class_key=? AND min_level<=? AND max_level>=? ORDER BY family_key''',
                (key,level,level)).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError('canonical companion family table missing') from exc
        if not families:return ir
        companion_rows=[];resources=[];actions=[];autos=[];links=[];policies=[];coverage=[]
        for row in families:
            family=row['family_key'];pet_id=f'{ir.actor.id}:companion:{family}'
            source=({'source_url':row['source_url'],'capture_id':row['capture_id'],
                     'captured_at':row['captured_at'],'status':row['proxy_status']},)
            if not (0<row['attack_speed_s'] and 0<row['focus_capacity'] and 0<=row['focus_initial']<=row['focus_capacity']):
                raise ValueError('invalid sourced companion scenario')
            companion_rows.append(ActorDefinition(id=pet_id,actor_type='pet',
                base_stats={'attack_power':0.,'critical_strike_chance':0.,'damage_multiplier':1.},
                state_status=row['proxy_status'],provenance=source,
                metadata={'family':family,'pre_summoned_scenario':True,
                          'pet_aggro_and_survivability_unmodeled':True}))
            resources.append(ResourceDefinition(id='focus',name='Focus',owner_actor_id=pet_id,
                initial_amount=float(row['focus_initial']),capacity=float(row['focus_capacity']),
                regeneration_per_s=float(row['focus_regen_s']),
                state_status='qualified_source_focus_regeneration',provenance=source))
            white=(float(row['base_white_dps'])+level*float(row['white_dps_per_level']))*float(row['damage_multiplier'])
            autos.append(AutoAttackDefinition(id=f'{pet_id}:auto',name=f'{family} natural melee',
                owner_actor_id=pet_id,attack_type='melee',school='physical',
                swing_time_s=float(row['attack_speed_s']),
                damage_source=AutoAttackDamageSource(kind='qualified_companion_white_dps',
                    flat_dps=white,attack_power_stat_id='attack_power'),
                hit_chance=1.,crit_chance_stat_id='critical_strike_chance',provenance=source))
            links.append(ActorLinkModifier(f'{pet_id}:ap',ir.actor.id,pet_id,
                ('attack_power',),'attack_power',float(row['ap_link_coefficient']),
                'add_scaled',pet_id,source))
            links.append(ActorLinkModifier(f'{pet_id}:crit',ir.actor.id,pet_id,
                ('critical_strike_chance',),'critical_strike_chance',
                float(row['crit_link_coefficient']),'set_scaled',pet_id,source))
            rows=db.execute('''SELECT * FROM companion_skill_source_facts WHERE class_key=?
                AND family_key=? AND min_level<=? ORDER BY skill_key,min_level DESC''',
                (key,family,level)).fetchall()
            latest={}
            for skill in rows:latest.setdefault(skill['skill_key'],skill)
            for name,skill in sorted(latest.items()):
                if not (skill['damage_min']>0 and skill['damage_max']>=skill['damage_min']
                        and skill['focus_cost']>=0 and skill['gcd_s']>=0 and skill['cooldown_s']>=0):
                    raise ValueError('invalid sourced companion rank')
                fact=({'source_url':skill['source_url'],'crosscheck_url':skill['crosscheck_url'],
                       'capture_id':skill['capture_id'],'rank':int(skill['rank'])},)
                actions.append(ActionDefinition(id=f'{pet_id}:{name}:{skill["spell_id"]}',
                    family_key=f'companion:{family}:{name}',name=f'{family} {name}',
                    owner_actor_id=pet_id,requirements=(),
                    costs=(ResourceCost('focus',float(skill['focus_cost'])),),
                    cast_time_s=0.,gcd_s=float(skill['gcd_s']),cooldown_s=float(skill['cooldown_s']),
                    effects=(DamageEffect('damage',skill['school'],'enemy',
                        float(skill['damage_min']),float(skill['damage_max'])),),provenance=fact))
            owned=tuple(a for a in actions if a.owner_actor_id==pet_id)
            if not owned:
                raise ValueError(f'no source-executable companion skill ranks for {pet_id}')
            policies.append(PolicyDefinition(id=f'{pet_id}:source_priority',
                label='All sourced pet attacks, source-order priority',
                rules=tuple(PolicyRuleDefinition(f'pet:{a.family_key}',a.id) for a in owned),
                provenance={'companion_policy':True,'owner_actor_id':pet_id,
                            'source_url':row['source_url'],'scope':'bounded_pet_priority_not_optimal'}))
            coverage.append({'family':family,'pet_actor_id':pet_id,'executed_skills':list(latest),
                             'source_capture':row['capture_id'],'pet_summoned_before_pull':True,
                             'pet_white_damage_authority':row['proxy_status']})
        return replace(ir,companions=(*ir.companions,*companion_rows),
            actor_links=(*ir.actor_links,*links),resources=(*ir.resources,*resources),
            auto_attacks=(*ir.auto_attacks,*autos),actions=(*ir.actions,*actions),
            policies=(*ir.policies,*policies),source_facts=(*ir.source_facts,
                {'family':'source_companions','rows':coverage}),
            unsupported_semantics=(*ir.unsupported_semantics,
                {'code':'pet_tame_train_recall_position_threat_survivability_unverified',
                 'status':'qualified_scenario','families':list(x['family'] for x in coverage)}))

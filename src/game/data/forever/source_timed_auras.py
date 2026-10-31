"""Generic canonical SQLite -> timed aura, swing proc, and aura consumer IR.

No game-specific names, ranks or coefficients live in this adapter.
"""
from __future__ import annotations
from dataclasses import replace
import sqlite3,json
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model import (ActionDefinition,ResourceCost,DamageEffect,TriggerDefinition,
                            StatusAuraEffect,EventEmitEffect,WeaponDamageEffect,TargetSchoolPowerEffect)

def source_enrich_timed_auras(ir,*,db_path=DEFAULT_DB):
    key=str(ir.actor.metadata.get('class_key') or '')
    level=int(ir.actor.metadata['level'])
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT * FROM sourced_timed_aura_actions
             WHERE class_key=? AND min_level<=? ORDER BY family_key,min_level DESC''',(key,level)).fetchall()
        grants = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='verified_talent_granted_action_facts'").fetchone():
            grants = [json.loads(row[0]) for row in db.execute(
                'SELECT action_json FROM verified_talent_granted_action_facts WHERE class_key=?',(key,))]
        consumers=db.execute('''SELECT * FROM sourced_aura_consumers
             WHERE class_key=? AND min_level<=? ORDER BY family_key,min_level DESC''',(key,level)).fetchall()
    if not rows and not consumers:return ir
    newest={}
    for r in rows:newest.setdefault(r['family_key'],r)
    actions=[];triggers=[];facts=[]
    aura_keys={r['aura_id'] for r in newest.values()}
    # A talent-granted aura is not executable until selected, but its identity
    # is a valid possible consumer target for the shared Judgement button.
    aura_keys.update(str(g['aura_id']) for g in grants if g.get('action_kind')=='timed_aura_weapon_proc')
    for r in newest.values():
        caveats=json.loads(r['caveats_json'])
        mechanic = r['mechanic_kind'] if 'mechanic_kind' in r.keys() else 'swing_damage'
        if (r['duration_s']<=0 or mechanic not in ('swing_damage','attack_rate_buff') or
            (mechanic=='swing_damage' and (r['swing_min']<=0 or r['swing_max']<r['swing_min'] or r['proc_reference_speed_s']<=0)) or
            (mechanic=='attack_rate_buff' and (r['attack_rate_multiplier'] is None or r['attack_rate_multiplier']<=0))):
            raise ValueError('invalid canonical timed aura rank')
        ref=({'source_url':r['source_url'],'crosscheck_url':r['crosscheck_url'],
              'client_build':r['client_build'],'capture_id':r['capture_id'],'caveats':caveats},)
        actions.append(ActionDefinition(id=f'{r["family_key"]}:{r["spell_id"]}',
            family_key=r['family_key'],name=r['family_key'].replace('_',' ').title(),
            owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(r['min_level'])},
                          {'kind':'mode_is','value':'ordinary'}),
            costs=(ResourceCost('mana',float(r['mana_cost'])),),cast_time_s=0.,
            gcd_s=float(r['gcd_s']),cooldown_s=0.,
            effects=(StatusAuraEffect('status_aura',r['aura_id'],'actor',float(r['duration_s']),
                exclusive_group=r['exclusive_group'] if 'exclusive_group' in r.keys() else None,
                actor_stat_deltas=({'attack_power':float(r['actor_attack_power_delta'])}
                    if 'actor_attack_power_delta' in r.keys() and r['actor_attack_power_delta'] else {}),
                auto_attack_speed_multiplier=(float(r['attack_rate_multiplier'])
                    if 'attack_rate_multiplier' in r.keys() and r['attack_rate_multiplier'] else 1.0)),),
            provenance=ref,metadata={'source_status':'qualified_timed_aura'}))
        if mechanic == 'swing_damage':
            triggers.append(TriggerDefinition(id=f'{r["family_key"]}:swing:{r["spell_id"]}',
                name='Sourced aura swing effect',owner_actor_id=ir.actor.id,
                event_kind='auto_attack_swing',
                effects=(DamageEffect('damage',r['school'],'enemy',float(r['swing_min']),float(r['swing_max']),
                    spell_power_coefficient=float(r['proc_sp_coefficient']),
                    self_absorb_fraction=float(r['swing_absorb_fraction'] or 0.0) if 'swing_absorb_fraction' in r.keys() else 0.0,
                    self_absorb_requires_stat=r['swing_absorb_requires_stat'] if 'swing_absorb_requires_stat' in r.keys() else None,
                    self_absorb_shield_id=r['swing_absorb_id'] if 'swing_absorb_id' in r.keys() else None),),
                required_aura_id=r['aura_id'],event_probability_field='landed_hit_probability',
                event_scale_field=('swing_time_s' if 'swing_speed_scaled' not in r.keys() or r['swing_speed_scaled'] else None),
                event_scale_reference=float(r['proc_reference_speed_s']),
                provenance=ref,metadata={'source_status':'qualified_server_script_proxy',
                          'effect_category':'seal_damage'}))
        if 'judge_school_power_bonus' in r.keys() and r['judge_school_power_bonus'] is not None:
            if not (r['judge_duration_s'] and r['judge_duration_s']>0 and r['judge_exclusive_group']):
                raise ValueError('invalid sourced judgement target debuff')
            triggers.append(TriggerDefinition(id=f'{r["family_key"]}:judgement:{r["spell_id"]}',
                name='Sourced judgement school power',owner_actor_id=ir.actor.id,
                event_kind='judgement_seal',
                effects=(TargetSchoolPowerEffect('target_school_power',
                    f'judgement:{r["family_key"]}',r['school'],float(r['judge_school_power_bonus']),
                    float(r['judge_duration_s']),r['judge_exclusive_group']),),
                required_aura_id=r['aura_id'],event_probability_field='landed_hit_probability',
                provenance=ref,metadata={'source_status':'client_verified_bonus_classic_coeff_interpretation',
                    'effect_category':'seal_utility'}))
        if r['judgement_min'] is not None:
            triggers.append(TriggerDefinition(id=f'{r["family_key"]}:judgement:{r["spell_id"]}',
                name='Sourced aura consumer damage',owner_actor_id=ir.actor.id,
                event_kind='judgement_seal',
                effects=(DamageEffect('damage',r['school'],'enemy',float(r['judgement_min']),
                    float(r['judgement_max']),spell_power_coefficient=float(r['judge_sp_coefficient'])),),
                required_aura_id=r['aura_id'],event_probability_field='landed_hit_probability',
                provenance=ref,metadata={'source_status':'qualified_judgement_server_script',
                          'effect_category':'seal_damage'}))
        facts.append({'family':r['family_key'],'spell_id':int(r['spell_id']),
                      'capture_id':r['capture_id'],'client_build':r['client_build'],
                      'qualified_server_formula':caveats})
    latest_consumer={}
    for r in consumers:latest_consumer.setdefault(r['family_key'],r)
    for r in latest_consumer.values():
        if r['required_aura_id'] not in aura_keys:
            raise ValueError('source consumer has no executable active aura')
        if r['consumes_aura']:
            raise ValueError('consuming aura mechanic not yet executable')
        if r['cost_kind']!='base_mana_fraction':
            raise ValueError('unknown canonical consumer cost kind')
        mana=next((res for res in ir.resources if res.id=='mana' and res.owner_actor_id==ir.actor.id),None)
        if mana is None or mana.capacity is None:
            raise ValueError('consumer requires sourced actor base mana')
        ref=({'source_url':r['source_url'],'client_build':r['client_build'],
              'capture_id':r['capture_id']},)
        actions.append(ActionDefinition(id=f'{r["family_key"]}:{r["spell_id"]}',
            family_key=r['family_key'],name=r['family_key'].replace('_',' ').title(),
            owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(r['min_level'])},
                          {'kind':'mode_is','value':'ordinary'},
                          {'kind':'aura_any_present','scope':'actor','aura_ids':sorted(aura_keys)}),
            costs=(ResourceCost('mana',float(r['cost_value'])*float(mana.metadata['base_mana'])),),
            cast_time_s=0.,gcd_s=float(r['gcd_s']),cooldown_s=float(r['cooldown_s']),
            effects=(EventEmitEffect('event_emit',r['event_kind'],
                clears_target_exclusive_group=(r['judge_exclusive_group'] if 'judge_exclusive_group' in r.keys() else None)),),
            provenance=ref,metadata={'source_status':'sourced_non_consuming_aura_judgement'}))
    return replace(ir,id=ir.id+':timed_aura:'+'_'.join(sorted({r['capture_id'] for r in newest.values()})),
        actions=(*ir.actions,*actions),triggers=(*ir.triggers,*triggers),
        source_facts=(*ir.source_facts,{'family':'source_timed_aura_trigger',
            'executed':facts,'consumer_count':len(latest_consumer)}),
        unsupported_semantics=(*ir.unsupported_semantics,{'code':'server_script_swing_speed_and_judgement_sp_coefficient_proxy',
            'status':'qualified_not_fully_verified'}))


def compile_granted_timed_aura(row, *, ir_slice):
    """Compile a verified talent-granted weapon proc without class dispatch.

    The canonical action row owns all numbers, IDs, source URLs and its
    qualified PPM assumption. The already-geared auto-attack owns actual
    weapon DPS and speed; this avoids inventing a second weapon model.
    """
    if row.get('action_kind') != 'timed_aura_weapon_proc':
        raise ValueError('expected sourced timed aura grant')
    required=('spell_id','family_key','name','required_level','mana_cost',
              'aura_id','duration_s','gcd_s','exclusive_group','weapon_damage_multiplier',
              'proc_reference_speed_s','school','source_url','client_build','capture_id','judge_damage_base')
    if any(row.get(key) is None for key in required):
        raise ValueError('incomplete canonical timed aura grant')
    if (float(row['duration_s'])<=0 or float(row['proc_reference_speed_s'])<=0 or
        float(row['weapon_damage_multiplier'])<=0 or float(row['mana_cost'])<0 or
        not row['exclusive_group'] or not str(row['source_url']).startswith('https://')):
        raise ValueError('invalid canonical timed aura grant')
    autos=[a for a in ir_slice.auto_attacks if a.owner_actor_id==ir_slice.actor.id
           and a.required_mode_id=='ordinary' and a.attack_type=='melee']
    if len(autos)!=1:
        raise ValueError('talent-granted weapon proc requires unique equipped melee auto')
    auto=autos[0]
    ref=({'source_url':row['source_url'],'client_build':row['client_build'],
          'capture_id':row['capture_id'],'server_proc_authority':row.get('proc_authority')},)
    action=ActionDefinition(id=f"{row['family_key']}:{row['spell_id']}",
        family_key=str(row['family_key']),name=str(row['name']),owner_actor_id=ir_slice.actor.id,
        requirements=({'kind':'minimum_level','value':int(row['required_level'])},
                      {'kind':'mode_is','value':str(auto.required_mode_id)}),
        costs=(ResourceCost('mana',float(row['mana_cost'])),),cast_time_s=0.,
        gcd_s=float(row['gcd_s']),cooldown_s=0.,
        effects=(StatusAuraEffect('status_aura',str(row['aura_id']),'actor',
            float(row['duration_s']),exclusive_group=str(row['exclusive_group'])),),
        provenance=ref,metadata={'source_status':'client_verified_aura_classic_ppm_proxy'})
    trigger=TriggerDefinition(id=f"{row['family_key']}:swing:{row['spell_id']}",
        name='Sourced weapon-damage proc',owner_actor_id=ir_slice.actor.id,
        event_kind='auto_attack_swing',
        effects=(WeaponDamageEffect('weapon_damage',str(row['school']),'enemy',
            damage_source=auto.damage_source,weapon_damage_time_s=float(auto.swing_time_s),
            weapon_damage_multiplier=float(row['weapon_damage_multiplier']),
            provenance=ref),),
        required_aura_id=str(row['aura_id']),event_probability_field='landed_hit_probability',
        event_scale_field='swing_time_s',event_scale_reference=float(row['proc_reference_speed_s']),
        provenance=ref,metadata={'source_status':'classic_ppm_proxy_not_forever_server_verified',
            'effect_category':'seal_damage'})
    judgement=TriggerDefinition(id=f"{row['family_key']}:judgement:{row['spell_id']}",
        name='Sourced talent-granted Judgement',owner_actor_id=ir_slice.actor.id,
        event_kind='judgement_seal',
        effects=(DamageEffect('damage',str(row['school']),'enemy',
            float(row.get('judge_damage_min',row['judge_damage_base'])),
            float(row.get('judge_damage_max',row['judge_damage_base']))),),
        required_aura_id=str(row['aura_id']),event_probability_field='landed_hit_probability',
        provenance=ref,metadata={'source_status':'client_verified_base_damage_sp_coefficient_unverified',
            'effect_category':'seal_damage'})
    return action,(trigger,judgement)

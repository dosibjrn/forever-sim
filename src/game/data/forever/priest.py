from __future__ import annotations
"""G40 Forever Priest L10–20: source-backed spells; qualified wand/mana scenario.

Ordinary Game IR only: wand is a ranged AutoAttack, no Priest runtime branch.
"""
from src.game.model import (ActionDefinition, ActorDefinition, AutoAttackDamageSource,
    AutoAttackDefinition, DamageEffect, GameIRSlice, HealEffect, PeriodicEffect,
    PeriodicHealEffect, PolicyCondition, PolicyDefinition, PolicyRuleDefinition,
    ResourceCost, ResourceDefinition)
from src.rulesets.forever.shared.defense import representative_player_hp

SMITE = ((6,591,30.,28.,34.,2.),(14,598,60.,47.,53.,2.5))
PAIN = ((10,594,50.,60.),(18,970,95.,108.))
RENEW = ((14,425269,65.,100.),(20,6075,105.,125.))

def _src(spell, name):
    return ({'authority':'current_public_forever_tooltip','provider':'wowhead',
             'url':f'https://www.wowhead.com/forever/spell={spell}/{name}',
             'checked_at':'2026-10-08'},)

def build_source_slice(level: int) -> GameIRSlice | None:
    level=int(level)
    if not 10 <= level <= 20: return None
    hp=float(representative_player_hp(level,0.))
    mana=180.+16.*level  # explicit proxy, not the canonical base mana
    wand_dps=6.+.40*level  # explicit representative scenario, not a claimed item
    actor=ActorDefinition(id='player',actor_type='player',
        state_status='explicit_qualified_priest_scenario_proxy',
        base_stats={'wand_dps':wand_dps,'spell_power':0.,'damage_multiplier':1.},
        provenance=({'authority':'scenario_proxy_not_source_backed',
          'note':'No named equipped wand, exact base mana/Spirit or spell hit table'},),
        metadata={'class_key':'priest','level':level,'wand_speed_s':2.,'wand_dps_proxy':wand_dps})
    resources=(ResourceDefinition(id='health',name='Health',owner_actor_id='player',
        initial_amount=hp,capacity=hp,state_status='qualified_proxy_starting_state'),
        ResourceDefinition(id='mana',name='Mana',owner_actor_id='player',
        initial_amount=mana,capacity=mana,regeneration_per_s=3.,
        state_status='qualified_proxy_starting_state',
        provenance=({'authority':'scenario_proxy_not_source_backed','note':'Mana pool and passive regen proxy'},)))
    smlevel,smid,smcost,smmin,smmax,cast=max(x for x in SMITE if x[0]<=level)
    plevel,pid,pcost,pdamage=max(x for x in PAIN if x[0]<=level)
    actions=[ActionDefinition(id=f'smite:{smid}',family_key='smite',name='Smite',
        owner_actor_id='player',requirements=({'kind':'minimum_level','value':smlevel},),
        costs=(ResourceCost('mana',smcost),),cast_time_s=cast,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect('damage','holy','enemy',smmin,smmax),),
        provenance=_src(smid,'smite')),
      ActionDefinition(id=f'shadow_word_pain:{pid}',family_key='shadow_word_pain',
        name='Shadow Word: Pain',owner_actor_id='player',
        requirements=({'kind':'minimum_level','value':plevel},),
        costs=(ResourceCost('mana',pcost),),cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
        effects=(PeriodicEffect('periodic_damage','shadow','enemy',f'swp:{pid}',
            pdamage,18.,3.,unsupported_semantics=({'semantic':'periodic_crit',
                'status':'not_resolved','note':'Forever DoTs can crit'},)),),
        provenance=_src(pid,'shadow-word-pain'))]
    if level>=14:
        rlevel,rid,rcost,rheal=max(x for x in RENEW if x[0]<=level)
        actions.append(ActionDefinition(id=f'renew:{rid}',family_key='renew',name='Renew',
            owner_actor_id='player',requirements=({'kind':'minimum_level','value':rlevel},),
            costs=(ResourceCost('mana',rcost),),cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
            effects=(PeriodicHealEffect('periodic_heal','actor','health',f'renew:{rid}:hot',
                rheal,15.,3.),),provenance=_src(rid,'renew')))
    if level>=16:
        actions.append(ActionDefinition(id='heal:2054',family_key='heal',name='Heal',
            owner_actor_id='player',requirements=({'kind':'minimum_level','value':16},),
            costs=(ResourceCost('mana',155.),),cast_time_s=3.,gcd_s=1.5,cooldown_s=0.,
            effects=(HealEffect('heal','actor','health',282.,324.),),provenance=_src(2054,'heal')))
    auto=AutoAttackDefinition(id='priest:auto:wand',name='Priest wand (qualified proxy)',
        owner_actor_id='player',attack_type='ranged',swing_time_s=2.,school='arcane',
        damage_source=AutoAttackDamageSource(kind='qualified_wand_dps_proxy',
            dps_stat_id='wand_dps',attack_power_stat_id=None),
        hit_chance=1.,crit_chance_on_landed_hit=0.,exclusive_with_casts=True,
        provenance=({'authority':'explicit_scenario_proxy_not_a_named_item'},))
    policy=PolicyDefinition(id=f'forever:priest:caster-wand@{level}',
        label='Shadow Word: Pain opener, Smite and wand autoattack',rules=(
            PolicyRuleDefinition('priest_swp',actions[1].id,conditions=(
                PolicyCondition('target_state',field='alive',operator='eq',value=True),)),
            PolicyRuleDefinition('priest_smite',actions[0].id,conditions=(
                PolicyCondition('target_state',field='alive',operator='eq',value=True),)),),
        provenance={'authority':'source_actions_qualified_wand_scenario',
            'g40_scope':'priest_L10_20_caster_wand'})
    return GameIRSlice(id=f'forever:priest:L{level}:g40',ruleset='forever',
        actor=actor,resources=resources,actions=tuple(actions),policies=(policy,),
        auto_attacks=(auto,),source_facts=({'family':'priest_L10_20',
            'spell_ids':[smid,pid]+[int(a.id.split(':')[-1]) for a in actions[2:]],
            'wand_gear':'explicit_proxy_not_canonical'},),
        unsupported_semantics=({'code':'priest_wand_named_item_and_combat_outcome','status':'proxy'},
            {'code':'priest_exact_mana_spirit_base_and_5sr','status':'proxy'},
            {'code':'dot_crit_spell_scaling_and_resists','status':'not_resolved'},
            {'code':'incoming_attacks_and_defensive_healing_policy','status':'not_resolved'},
            {'code':'full_talent_gear_route_and_travel','status':'not_resolved'}),
        provenance={'provider':'forever_priest_source_adapter',
            'g40_proof_scope':'generic_priest_caster_wand_L10_20',
            'numeric_scope':'bounded_source_spells_proxy_wand_mana_not_final_leveling'})

from __future__ import annotations
"""G43 bounded Warlock/Imp proof; source spells + qualified pet firebolt proxy.

The generic timed-Actor and periodic machinery own combat execution. Imp
Firebolt mana and cast AI are explicitly not represented by its ranged auto.
"""
from src.game.model import (ActionDefinition, ActorDefinition, AutoAttackDefinition,
    AutoAttackDamageSource, DamageEffect, GameIRSlice, PeriodicEffect, PeriodicHealEffect, ResourceChangeEffect, PolicyCondition,
    PolicyDefinition, PolicyRuleDefinition, ResourceCost, ResourceDefinition,
    SummonEffect, TimedSummonDefinition)
from src.rulesets.forever.shared.defense import representative_player_hp


def _fact(spell_id: int, label: str):
    return ({'authority':'current_public_forever_tooltip','provider':'wowhead',
        'url':f'https://www.wowhead.com/forever/spell={spell_id}/{label}',
        'checked_at':'2026-10-08'},)


def build_source_slice(level: int) -> GameIRSlice | None:
    level=int(level)
    if not 10 <= level <= 20: return None
    health=float(representative_player_hp(level,0.))
    mana=200.+20.*level
    player=ActorDefinition(id='player',actor_type='player',
        state_status='qualified_warlock_leveling_proxy',
        base_stats={'spell_power':0.},
        provenance=({'authority':'explicit_scenario_proxy_not_canonical_character_stats'},),
        metadata={'class_key':'warlock','level':level})
    imp=ActorDefinition(id='warlock:imp',actor_type='pet',
        state_status='source_firebolt_with_qualified_ai_proxy',
        provenance=_fact(3110,'firebolt'))
    resources=(ResourceDefinition(id='health',name='Health',owner_actor_id='player',
        initial_amount=health,capacity=health,state_status='qualified_proxy_starting_state'),
        ResourceDefinition(id='mana',name='Mana',owner_actor_id='player',
        initial_amount=mana,capacity=mana,regeneration_per_s=3.,
        state_status='qualified_proxy_starting_state'))
    bolt_id=705 if level>=12 else 695
    bolt_mana,bolt_low,bolt_high,bolt_cast=(70.,41.,48.,2.8) if level>=12 else (40.,25.,31.,2.2)
    bolt=ActionDefinition(id=f'shadow_bolt:{bolt_id}',family_key='shadow_bolt',
        name='Shadow Bolt',owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',bolt_mana),),
        cast_time_s=bolt_cast,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect('damage','shadow','enemy',bolt_low,bolt_high),),
        provenance=_fact(bolt_id,'shadow-bolt'))
    corruption=ActionDefinition(id='corruption:172',family_key='corruption',
        name='Corruption',owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',35.),),
        cast_time_s=2.,gcd_s=1.5,cooldown_s=0.,
        effects=(PeriodicEffect('periodic_damage','shadow','enemy','warlock:corruption:172',
            40.,12.,3.,unsupported_semantics=({'semantic':'periodic_crit',
            'status':'not_resolved','note':'Forever DoTs may crit'},)),),
        provenance=_fact(172,'corruption'))
    summon_def=TimedSummonDefinition(id='warlock:imp:spawn',owner_actor_id='player',
        summoned_actor_id=imp.id,duration_s=3600.,provenance=_fact(688,'summon-imp'),
        metadata={'duration_s':'scenario_lifetime_not_source_despawn','pet_mana_ai':'not_modelled'})
    summon=ActionDefinition(id='summon_imp:688',family_key='summon_imp',name='Summon Imp',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',mana*.8),),
        cast_time_s=10.,gcd_s=1.5,cooldown_s=0.,
        effects=(SummonEffect('summon',summon_def.id),),provenance=_fact(688,'summon-imp'))
    imp_auto=AutoAttackDefinition(id='warlock:imp:firebolt:3110',
        name='Imp Firebolt R1 (qualified 2s pet auto proxy)',owner_actor_id=imp.id,
        attack_type='ranged',swing_time_s=2.,school='fire',
        damage_source=AutoAttackDamageSource(kind='imp_firebolt_proxy',flat_dps=2.25,
            attack_power_stat_id=None),provenance=_fact(3110,'firebolt'))
    # Reusable conversion: health is a true spend, mana is restored up to capacity.
    tap=ActionDefinition(id='life_tap:1454',family_key='life_tap',name='Life Tap',
        owner_actor_id='player',requirements=({'kind':'resource_min','resource_id':'health','value':45.},),
        costs=(ResourceCost('health',30.),),cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
        effects=(ResourceChangeEffect('resource_change','mana','actor','add',30.),),
        provenance=({'authority':'g44_qualified_value_proxy','spell_id':1454},),
        metadata={'fidelity':'health_mana_amounts_qualified_proxy'})
    drain=ActionDefinition(id='drain_life:689',family_key='drain_life',name='Drain Life',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',55.),),
        cast_time_s=5.,gcd_s=1.5,cooldown_s=0.,
        effects=(PeriodicEffect('periodic_damage','shadow','enemy','warlock:drain:689',
            50.,5.,1.),),
        provenance=({'authority':'g44_qualified_channel_proxy','spell_id':689},),
        metadata={'channel':True,'leech':{'resource_id':'health','ratio':1.},'fidelity':'spellpower_and_resist_not_resolved'})
    policy=PolicyDefinition(id=f'forever:warlock:imp-dot@{level}',
        label='Summon Imp, Corruption, Shadow Bolt',rules=(
          PolicyRuleDefinition('summon_imp',summon.id),
          PolicyRuleDefinition('life_tap',tap.id,conditions=(
            PolicyCondition(kind='resource_threshold',resource_id='mana',operator='lte',value=75.),
            PolicyCondition(kind='resource_threshold',resource_id='health',operator='gte',value=90.),)),
          *((PolicyRuleDefinition('drain_life',drain.id,conditions=(
            PolicyCondition(kind='resource_threshold',resource_id='health',operator='lte',value=health*.65),
            PolicyCondition(kind='resource_threshold',resource_id='mana',operator='gte',value=55.),)),) if level>=14 else ()),
          PolicyRuleDefinition('corruption',corruption.id,conditions=(
            PolicyCondition(kind='aura_missing',scope='target',aura_id='warlock:corruption:172'),)),
          PolicyRuleDefinition('shadow_bolt',bolt.id)),
        provenance={'authority':'bounded_generic_policy','g43_scope':'warlock_imp_dot'})
    return GameIRSlice(id=f'forever:warlock:L{level}:g43',ruleset='forever',actor=player,
        resources=resources,actions=(summon,corruption,bolt,tap,drain) if level>=14 else (summon,corruption,bolt,tap),policies=(policy,),
        companions=(imp,),timed_summons=(summon_def,),auto_attacks=(imp_auto,),
        source_facts=({'spell_ids':[688,172,bolt_id,3110],
            'pet_damage':'4-5 every 2 sec proxy','base_mana':'not_canonical'},),
        unsupported_semantics=({'code':'imp_firebolt_mana_and_cast_ai','status':'proxy_auto_attack'},
            {'code':'imp_lifetime_recast_and_pet_stances','status':'not_modelled'},
            {'code':'base_mana_and_pet_stats','status':'proxy'},
            {'code':'dot_crit_resists_and_spell_scaling','status':'not_resolved'},
            {'code':'other_ranks_talents_gear_pet_quests','status':'not_covered'}),
        provenance={'provider':'forever_warlock_g43',
            'numeric_scope':'bounded_source_spells_qualified_imp_proxy_not_final_leveling'})

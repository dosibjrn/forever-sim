from __future__ import annotations

"""G41 Forever Shaman L10–20: one shared caster/melee Mode+Action+AutoAttack slice.

Rockbiter is a weapon-only temporary modifier represented by an existing Mode
for this bounded one-imbue proof. Multiple simultaneous stance/weapon slots and
natural expiration are deliberately not claimed.
"""
from src.game.model import (
    ActionDefinition, ActorDefinition, AutoAttackDamageSource, AutoAttackDefinition,
    DamageEffect, GameIRSlice, ModeChangeEffect, ModeDefinition, ModeStatModifier,
    PolicyDefinition, PolicyRuleDefinition, ResourceCost, ResourceDefinition,
    TimedSummonDefinition, SummonEffect,
)
from src.rulesets.forever.shared.defense import representative_player_hp

ROCKBITER = ((8, 8018, 25., 79.), (16, 8019, 50., 118.))
LIGHTNING = (8, 529, 30., 29., 34., 2.0)
EARTH_SHOCK = (4, 8042, 30., 20., 22., 6.0)


def _fact(spell_id, name):
    return ({'authority':'current_public_forever_tooltip','provider':'wowhead',
             'url':f'https://www.wowhead.com/forever/spell={spell_id}/{name}',
             'checked_at':'2026-10-08'},)


def build_source_slice(level: int) -> GameIRSlice | None:
    level = int(level)
    if not 10 <= level <= 20:
        return None
    rlevel, rid, rcost, bonus_ap = max(row for row in ROCKBITER if row[0] <= level)
    actor = ActorDefinition(id='player',actor_type='player',
        state_status='qualified_shaman_proxy_weapon_stats',
        base_stats={'attack_power':20.+2.*level,'weapon_dps':7.+0.5*level,'spell_power':0.},
        provenance=({'authority':'scenario_proxy_not_canonical_gear_or_stats'},),
        metadata={'class_key':'shaman','level':level,'weapon_speed_s':2.7})
    hp = float(representative_player_hp(level, 0.))
    resources=(
        ResourceDefinition(id='health',name='Health',owner_actor_id='player',
            initial_amount=hp,capacity=hp,state_status='qualified_proxy_starting_state'),
        ResourceDefinition(id='mana',name='Mana',owner_actor_id='player',
            initial_amount=220.+20*level,capacity=220.+20*level,
            regeneration_per_s=3.,state_status='qualified_proxy_starting_state',
            provenance=({'authority':'explicit_scenario_proxy_not_canonical_mana_or_spirit'},)),
    )
    modes=(ModeDefinition(id='unimbued',label='No weapon imbue',initial=True),
        ModeDefinition(id='rockbiter',label='Rockbiter Weapon (1 h maintenance)',
            stat_modifiers=(ModeStatModifier('attack_power','add_flat',bonus_ap),),
            provenance=_fact(rid,'rockbiter-weapon'),
            metadata={'qualified_model':'single_temporary_weapon_imbue_slot',
                      'source_duration_s':3600.,'expiration_not_scheduled':True}),)
    lb=ActionDefinition(id='lightning_bolt:529',family_key='lightning_bolt',name='Lightning Bolt',
        owner_actor_id='player',requirements=({'kind':'minimum_level','value':8},),
        costs=(ResourceCost('mana',30.),),cast_time_s=2.,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect('damage','nature','enemy',29.,34.),),provenance=_fact(529,'lightning-bolt'))
    shock=ActionDefinition(id='earth_shock:8042',family_key='earth_shock',name='Earth Shock',
        owner_actor_id='player',requirements=({'kind':'minimum_level','value':4},),
        costs=(ResourceCost('mana',30.),),cast_time_s=0.,gcd_s=1.5,cooldown_s=6.,
        effects=(DamageEffect('damage','nature','enemy',20.,22.),),provenance=_fact(8042,'earth-shock'),
        metadata={'interrupt_and_threat':'not_modelled_no_enemy_spellcast'})
    rock=ActionDefinition(id=f'rockbiter:{rid}',family_key='rockbiter_imbue',name='Rockbiter Weapon',
        owner_actor_id='player',requirements=({'kind':'mode_is','value':'unimbued'},),
        costs=(ResourceCost('mana',rcost),),cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
        effects=(ModeChangeEffect('mode_change','rockbiter'),),provenance=_fact(rid,'rockbiter-weapon'))
    auto=AutoAttackDefinition(id='shaman:auto:mainhand',name='Shaman main-hand autoattack',
        owner_actor_id='player',attack_type='melee',swing_time_s=2.7,school='physical',
        damage_source=AutoAttackDamageSource(kind='qualified_weapon_proxy',
            dps_stat_id='weapon_dps',attack_power_stat_id='attack_power'),
        provenance=({'authority':'explicit_scenario_proxy_not_equipped_gear'},))
    # G42: source-backed rank-1 Searing Totem; repeated attacks have an
    # explicitly qualified 2 s interval proxy until a dated Forever cadence is verified.
    totem_actor = ActorDefinition(id='shaman:searing_totem', actor_type='summon',
        state_status='source_backed_damage_proxy_attack_interval',
        provenance=_fact(3599, 'searing-totem'))
    totem = TimedSummonDefinition(id='shaman:searing_totem:spawn',
        owner_actor_id='player', summoned_actor_id=totem_actor.id, duration_s=30.,
        provenance=_fact(3599, 'searing-totem'),
        metadata={'spell_id':3599,'range_yards':20,'health':5,'attack_interval_s':'unverified_proxy_2s'})
    totem_attack=AutoAttackDefinition(id='shaman:searing_totem:fire',
        name='Searing Totem fire bolt (expected-value emitter)',
        owner_actor_id=totem_actor.id,attack_type='ranged',swing_time_s=2.,school='fire',
        damage_source=AutoAttackDamageSource(kind='source_damage_proxy_interval',
            flat_dps=5.,attack_power_stat_id=None),provenance=_fact(3599,'searing-totem'))
    summon_action=ActionDefinition(id='searing_totem:3599',family_key='searing_totem',
        name='Searing Totem',owner_actor_id='player',
        requirements=({'kind':'minimum_level','value':10},),
        costs=(ResourceCost('mana',25.),),cast_time_s=0.,gcd_s=1.,cooldown_s=30.,
        effects=(SummonEffect('summon','shaman:searing_totem:spawn'),),
        provenance=_fact(3599,'searing-totem'),
        metadata={'range_yards':20,'emitter_attack_interval':'proxy_2s_not_verified'})
    policy=PolicyDefinition(id=f'forever:shaman:hybrid@{level}',label='Rockbiter + Earth Shock + Lightning Bolt',
        rules=(PolicyRuleDefinition('maintain_rockbiter',rock.id),
               PolicyRuleDefinition('summon_searing_totem',summon_action.id),
               PolicyRuleDefinition('shock',shock.id),
               PolicyRuleDefinition('bolt',lb.id)),
        provenance={'authority':'bounded_generic_policy','g41':'hybrid'})
    return GameIRSlice(id=f'forever:shaman:L{level}:g42',ruleset='forever',actor=actor,
        resources=resources,modes=modes,actions=(rock,shock,lb,summon_action),policies=(policy,),
        companions=(totem_actor,),timed_summons=(totem,),
        auto_attacks=(auto,totem_attack),source_facts=({'rockbiter_spell_id':rid,'rockbiter_ap_bonus':bonus_ap,
            'lightning_bolt_spell_id':529,'earth_shock_spell_id':8042},),
        unsupported_semantics=({'code':'named_weapon_and_canonical_shaman_stats','status':'proxy'},
            {'code':'simultaneous_weapon_imbue_and_other_modes','status':'not_supported'},
            {'code':'weapon_imbue_expiration_after_3600s','status':'not_supported'},
            {'code':'searing_totem_attack_interval_proxy','status':'not_source_verified'},
            {'code':'searing_totem_placement_range_targeting','status':'not_supported'},
            {'code':'other_spell_ranks_and_heals','status':'not_covered'},
            {'code':'full_talent_gear_route_and_travel','status':'not_covered'},
            {'code':'hit_resist_and_enemy_attack_schedule','status':'proxy'}),
        provenance={'provider':'forever_shaman_source_adapter',
            'g41_proof_scope':'generic_shaman_hybrid_rockbiter_L10_20',
            'numeric_scope':'bounded_spell_ranks_proxy_equipment_not_final_leveling'})

from __future__ import annotations
"""G45 bounded Mage native generic caster/wand proof, not legacy optimizer.

L10-30 starts from bounded rank-one actions; canonical SQLite rank promotion handles verified upgrades; missing effects and gear
are explicit limitations rather than fabricated tooltip statistics.
"""
from src.game.model import (ActionDefinition, ActorDefinition, AutoAttackDefinition,
    AutoAttackDamageSource, ControlEffect, DamageEffect, GameIRSlice, PeriodicEffect, PeriodicResourceEffect,
    PolicyDefinition, PolicyRuleDefinition, PolicyCondition, ResourceCost, ResourceDefinition)
from src.rulesets.forever.shared.defense import representative_player_hp


def _src(spell: int, name: str):
    return ({'authority':'current_public_forever_tooltip','provider':'wowhead',
             'url':f'https://www.wowhead.com/forever/spell={spell}/{name}',
             'checked_at':'2026-10-08'},)


def build_source_slice(level: int, *, arcane_intellect_maintenance: bool = True) -> GameIRSlice | None:
    level = int(level)
    if level < 10 or level > 30:
        return None
    hp = float(representative_player_hp(level, 0.))
    # Maintenance Arcane Intellect R1 (1459): +2 Intellect, 30 minutes.
    # Shared Classic stat conversion: +15 mana per Intellect. The long-lived
    # 60 mana cast is NOT silently charged once per combat encounter.
    intellect_bonus = 2. if arcane_intellect_maintenance else 0.
    mana = 180. + 18. * level + 15. * intellect_bonus  # explicit base scenario proxy
    actor = ActorDefinition(id='player', actor_type='player',
        state_status='qualified_mage_leveling_scenario',
        base_stats={'wand_dps':6.+0.4*level,'spell_power':0.,'damage_multiplier':1.,'intellect':intellect_bonus,
                    'spirit':30. + level},
        provenance=({'authority':'scenario_proxy_not_source_backed'},),
        metadata={'class_key':'mage','level':level})
    resources = (ResourceDefinition(id='health',name='Health',owner_actor_id='player',
        initial_amount=hp,capacity=hp,state_status='qualified_proxy_starting_state'),
        ResourceDefinition(id='mana',name='Mana',owner_actor_id='player',
        initial_amount=mana,capacity=mana,regeneration_per_s=0.,
        state_status='qualified_proxy_starting_state'))
    frostbolt = ActionDefinition(id='frostbolt:116',family_key='frostbolt',name='Frostbolt R1',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',25.),),
        cast_time_s=1.5,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect('damage','frost','enemy',20.,22.),),
        provenance=_src(116,'frostbolt'))
    fireball = ActionDefinition(id='fireball:133',family_key='fireball',name='Fireball R1',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',30.),),
        cast_time_s=1.5,gcd_s=1.5,cooldown_s=0.,
        effects=(DamageEffect('damage','fire','enemy',16.,24.),
                 PeriodicEffect('periodic_damage','fire','enemy','mage:fireball:133',2.,4.,2.)),
        provenance=_src(133,'fireball'))
    fire_blast = ActionDefinition(id='fire_blast:2136',family_key='fire_blast',name='Fire Blast R1',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',40.),),
        cast_time_s=0.,gcd_s=1.5,cooldown_s=8.,
        effects=(DamageEffect('damage','fire','enemy',27.,35.),),
        provenance=_src(2136,'fire-blast'))
    # Forever spell #12051: +1500% *on top of* ordinary Spirit regen, even
    # inside the five-second rule. Mage's unverified character Spirit at this
    # level remains a qualified scenario proxy. Formula is carried in the IR
    # and resolved against the ACTUAL geared/talented actor at every 2s tick.
    evocation = ActionDefinition(id='evocation:12051',family_key='evocation',name='Evocation',
        owner_actor_id='player',requirements=(),costs=(),cast_time_s=8.,gcd_s=1.5,
        cooldown_s=480.,effects=(PeriodicResourceEffect('periodic_resource','mana',
            'actor','mage:evocation:12051',16.*(12.5+(30.+level)/4.),8.,2.,
            metadata={'resource_gain_model':'stat_linear_tick',
                'stat_id':'spirit','base_per_tick':12.5,
                'stat_per_tick':0.25,'multiplier':16.,
                'ignore_five_second_rule':True,'stop_channel_on_full':True}),),
        provenance=_src(12051,'evocation'),
        metadata={'channel':True,'fidelity':'source_1500pct_spirit_2s_ticks_5sr_override',
                  'spirit_fidelity':'qualified_scenario_proxy_not_level30_source_certified'})
    # Source: Forever Wowhead spell 118, checked 2026-10-14. This is a
    # control, NOT 20 seconds of automatic DPS. Animal-type restrictions,
    # sheep regeneration and break-on-damage require explicit runtime tests.
    polymorph = ActionDefinition(id='polymorph:118',family_key='polymorph',name='Polymorph',
        owner_actor_id='player',requirements=(),costs=(ResourceCost('mana',60.),),
        cast_time_s=1.5,gcd_s=1.5,cooldown_s=0.,
        effects=(ControlEffect('control','polymorph','enemy',20.,prevents_enemy_actions=True,breaks_on_damage=True),),
        provenance=({'authority':'current_public_forever_tooltip','provider':'wowhead',
            'url':'https://www.wowhead.com/forever/spell=118/polymorph',
            'checked_at':'2026-10-14'},),
        metadata={'range_yards':30.,'single_target_control':True,
            'missing_fidelity':['target_creature_type','heartbeat_resist','regeneration_while_controlled']})
    frost_nova = ActionDefinition(id='frost_nova:122', family_key='frost_nova', name='Frost Nova R1',
        owner_actor_id='player', requirements=(), costs=(ResourceCost('mana',55.),),
        cast_time_s=0., gcd_s=1.5, cooldown_s=25.,
        effects=(DamageEffect('damage','frost','enemy',21.5,23.5),
                 ControlEffect('control','root','enemy',8.),
                 ControlEffect('control','frozen','enemy',8.)),
        provenance=_src(122,'frost-nova'),
        metadata={'root_break_on_damage':'not_modelled','enemy_range_and_AI':'not_modelled'})
    wand=AutoAttackDefinition(id='mage:auto:wand',name='Mage wand (qualified proxy)',
        owner_actor_id='player',attack_type='ranged',swing_time_s=2.,school='arcane',
        damage_source=AutoAttackDamageSource(kind='qualified_wand_dps_proxy',
            dps_stat_id='wand_dps',attack_power_stat_id=None),hit_chance=1.,
        crit_chance_on_landed_hit=0.,exclusive_with_casts=True,
        provenance=({'authority':'scenario_proxy_not_named_equipped_item'},))
    policy=PolicyDefinition(id=f'forever:mage:caster-wand@{level}',
        label='Frostbolt filler and wand (bounded rank-one proof)',
        rules=(*((PolicyRuleDefinition('mage_evocation','evocation:12051',conditions=(
            PolicyCondition(kind='resource_threshold',resource_id='mana',operator='lte',value=mana*.35),)),) if level>=20 else ()),
            PolicyRuleDefinition('mage_fire_blast','fire_blast:2136',conditions=(
            PolicyCondition(kind='resource_threshold',resource_id='mana',operator='gte',value=mana*.85),)),
            PolicyRuleDefinition('mage_frostbolt','frostbolt:116',conditions=(
            PolicyCondition(kind='resource_threshold',resource_id='mana',operator='gte',value=mana*.85),)),),
        provenance={'authority':'bounded_source_spell_qualified_wand_scenario','g45_scope':'mage_L10_30_qualified_proxy'})
    return GameIRSlice(id=f'forever:mage:L{level}:g46',ruleset='forever',
        actor=actor,resources=resources,actions=(frostbolt,fireball,fire_blast,frost_nova,polymorph)+((evocation,) if level>=20 else ()),
        policies=(policy,),auto_attacks=(wand,),
        source_facts=({'family':'mage_L10_30_qualified_proxy','spell_ids':[116,133,2136,122,118]+([12051] if level>=20 else []),
                       'spell_ranks':'rank_one_only_not_final_leveling'},
            {'family':'arcane_intellect_maintenance','spell_id':1459,'bonus_intellect':2,'duration_s':1800,'cast_mana':60,'enabled':arcane_intellect_maintenance,'amortization':'outside_single_combat_not_free_on_long_route','source_url':'https://www.wowhead.com/forever/spell=1459/arcane-intellect'},),
        unsupported_semantics=({'code':'mage_rank_upgrades_gear_talents','status':'not_modelled'},
            {'code':'mage_exact_base_mana_spirit_5sr','status':'proxy'},
            {'code':'mage_named_wand_and_hit_resist','status':'proxy'},
            {'code':'frostbolt_slow_projectile_travel_fireball_crit','status':'not_modelled'},
            {'code':'mage_evocation_exact_spirit_regen_ticks_5sr','status':'source_formula_with_proxy_base_spirit'},
            {'code':'mage_arcane_intellect_maintenance_cast_renewal','status':'amortized_outside_single_combat'},
            {'code':'mage_frost_nova_root_break_on_damage_and_enemy_pathing','status':'not_modelled'},
            {'code':'mage_polymorph_creature_family_break_and_heartbeat_resist','status':'partially_modelled'},
            {'code':'mage_frost_armor_slow_and_other_procs','status':'not_modelled'},
            {'code':'mob_AI_and_route_travel','status':'not_modelled'}),
        provenance={'provider':'forever_mage_g45',
            'g45_proof_scope':'mage_L10_20_caster_wand',
            'g46_proof_scope':'fire_blast_cooldown_evocation_channel_arcane_intellect_maintenance',
            'numeric_scope':'bounded_rank_one_spells_proxy_mana_wand_not_final_leveling_not_checkpoint_accepted'})

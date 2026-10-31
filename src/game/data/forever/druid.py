from __future__ import annotations

from dataclasses import replace
import re

"""Druid source providers for the Forever Game IR registry.

This module is source adaptation only. It may know the source is Druid-shaped;
the generic model/backend/runtime must not grow Druid combat branches.
"""

from src.game.data.forever.direct_spells import DirectSpellSourceFact, normalize_direct_spell_slice
from src.game.data.forever.player_state import PlayerStartingStateSourceFact, normalize_player_starting_state
from src.game.data.forever.periodic_spells import DirectPeriodicSpellSourceFact, normalize_direct_periodic_action
from src.game.data.forever.healing_spells import (
    DirectHealSourceFact, PeriodicHealSourceFact,
    normalize_direct_heal_action, normalize_periodic_heal_action,
)
from src.game.data.forever.tuning_overlays import direct_damage_overlays
from src.game.data.forever.source_index_rank_parity import indexed_rank_fact, indexed_rank_identity
from src.game.data.forever.sqlite_talents import load_sqlite_talents
from src.game.model import (
    ActionDefinition, ArmorMitigationDefinition, AutoAttackDamageSource, AutoAttackDefinition, DamageEffect, IncomingAttackDefinition, IncomingEventProjection,
    ModeChangeEffect, ModeDefinition, ModeResourceRule, ModeStatModifier, PolicyCondition, PolicyDefinition, PolicyRuleDefinition, PeriodicEffect,
    PeriodicResourceEffect, ResourceChangeEffect, ResourceCost, ResourceDefinition, ResourceEventGainRule, ResourceScaledPeriodicEffect, TriggerDefinition, WeaponDamageEffect, StatusAuraEffect,
)
from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.classes.druid import rage as rage_rules
from src.rulesets.forever.classes.druid.weapon import BEAR_FORM_SWING_S, CAT_FORM_SWING_S, weapon_for_level
from src.rulesets.forever.data.catalogue import default_catalogue
from src.rulesets.forever.data.provenance import wowhead_id_from_url
from src.rulesets.forever.shared.base_stats import base_primary_stats, primary_stats_provenance
from src.rulesets.forever.shared.defense import armor_constant, representative_player_hp
from src.rulesets.forever.shared.mobs import normal_world_raw_dps
from src.game.data.forever.armor_conversions import source_enrich_armor


def _source_backed_player_state(level: int):
    level = int(level)
    race_key = "tauren"
    catalogue = default_catalogue()
    stat_row = catalogue.class_level_stat("druid", level)
    mana_source = catalogue.class_level_stats_source()
    fact = PlayerStartingStateSourceFact(
        class_key="druid",
        race_key=race_key,
        level=level,
        base_stats=base_primary_stats("druid", level, race=race_key),
        base_mana=float(stat_row["base_mana"]),
        stat_provenance=primary_stats_provenance("druid", level, race=race_key),
        mana_provenance={
            "authority": "pinned_class_level_stats",
            "provider": mana_source.get("provider"),
            "dataset": mana_source.get("dataset"),
            "ruleset_basis": mana_source.get("ruleset_basis"),
            "snapshot": catalogue.snapshot_id,
            "source": dict(mana_source.get("source") or {}),
            "class_key": "druid",
            "level": level,
            "base_mana": float(stat_row["base_mana"]),
        },
        health_capacity=float(representative_player_hp(level, 0.0)),
        health_provenance={
            "authority": "forever_shared_defense_proxy",
            "source_module": "src.rulesets.forever.shared.defense.representative_player_hp",
            "status": "qualified_classic_proxy",
            "level": level,
            "capacity": float(representative_player_hp(level, 0.0)),
            "note": "Player base-health source table is not yet in Canonical Game IR; shared leveling HP proxy retained explicitly until that authority lands.",
        },
    )
    return normalize_player_starting_state(fact)


def build_source_slice(level: int, *, ability_db_path=None):
    level = int(level)
    # Caller-supplied immutable source staging must control *all* indexed core
    # action facts as well as the generic source compiler; no mixed databases.
    from .sqlite_talents import DEFAULT_DB
    from .source_db_scope import active_ability_db
    selected_rank_db = ability_db_path if ability_db_path is not None else active_ability_db(DEFAULT_DB)
    def _index_fact(**kw):
        return indexed_rank_fact(**kw, db_path=selected_rank_db)
    catalogue = default_catalogue()
    eligible = [row for row in wh.WRATH_RAW_TOOLTIP_RANKS if int(row[0]) <= level]
    if not eligible:
        return None
    learn_level, mana, cast_s, damage_min, damage_max, coefficient = eligible[-1]
    source_url = wh.WRATH_CURRENT_SOURCE_URLS[int(learn_level)]
    wrath_index = _index_fact(class_key='druid', name='Wrath',
        required_level=int(learn_level), effect_kind='direct_damage')
    if wrath_index is not None:
        mana, cast_s = wrath_index['mana'], wrath_index['cast_s']
        damage_min, damage_max = wrath_index['low'], wrath_index['high']
        source_url = wrath_index['source_url']
    actor, mana_resource, health_resource = _source_backed_player_state(level)
    fact = DirectSpellSourceFact(
        family_key="wrath",
        name="Wrath",
        source_id=int(wowhead_id_from_url(source_url)),
        required_level=int(learn_level),
        resource_id="mana",
        resource_cost=float(mana),
        cast_time_s=float(cast_s),
        damage_min=float(damage_min),
        damage_max=float(damage_max),
        spell_power_coefficient=float(coefficient),
        school="Nature",
        source_url=source_url,
        provenance={
            "ruleset": "forever",
            "source_kind": "current_public_forever_tooltip_fact",
            "source_module": "src.rulesets.forever.classes.druid.wowhead_facts",
            "confidence": "high",
            "indexed_rank_fact": wrath_index,
            "numeric_authority": wrath_index["source_authority"] if wrath_index else "legacy_tooltip_not_index_verified",
            "tuning_status": ("INDEX_AFTER_VS_APPROX_BETA_TUNING_UNRESOLVED"
                              if wrath_index else "HISTORICAL_APPROX_OVERLAY"),
        },
    )
    # The index snapshot postdates the September tuning note, but lacks a
    # client-build stamp proving whether the after-tooltip already includes the
    # approximate +50% server adjustment. This indexed arm deliberately does
    # NOT multiply it again: a separate same-build sensitivity arm retains the
    # historical overlay. Neither arm proves current-build authority or DONE.
    overlays = () if wrath_index else direct_damage_overlays(class_key="druid", family_key=fact.family_key)
    base_slice = normalize_direct_spell_slice(
        ruleset="forever",
        class_key="druid",
        fact=fact,
        actor=actor,
        resource=mana_resource,
        overlays=overlays,
    )
    base_slice = replace(
        base_slice, resources=(mana_resource, health_resource), talents=(),
        provenance={
            **dict(base_slice.provenance),
            "talent_source_families": [],
            "talent_authority": "pending_canonical_sqlite_adapter",
        },
    )
    moon_eligible = [row for row in wh.MOONFIRE_RANKS if int(row[0]) <= level]
    if not moon_eligible:
        return _with_sqlite_talents(source_enrich_armor(base_slice))
    (moon_level, moon_mana, moon_direct_min, moon_direct_max, moon_dot_total,
     moon_duration_s, moon_direct_coeff, moon_tick_coeff) = moon_eligible[-1]
    moon_source_url = wh.MOONFIRE_CURRENT_SOURCE_URLS[int(moon_level)]
    moon_index = _index_fact(class_key='druid', name='Moonfire',
        required_level=int(moon_level), effect_kind='direct_periodic_damage')
    if moon_index is not None:
        moon_mana = moon_index['mana']
        moon_direct_min, moon_direct_max = moon_index['low'], moon_index['high']
        moon_dot_total, moon_duration_s = moon_index['periodic_total'], moon_index['duration_s']
        moon_source_url = moon_index['source_url']
    moonfire_fact = DirectPeriodicSpellSourceFact(
        family_key="moonfire",
        name="Moonfire",
        source_id=int(wowhead_id_from_url(moon_source_url)),
        required_level=int(moon_level),
        resource_id="mana",
        resource_cost=float(moon_mana),
        direct_min=float(moon_direct_min),
        direct_max=float(moon_direct_max),
        direct_spell_power_coefficient=float(moon_direct_coeff),
        periodic_total=float(moon_dot_total),
        periodic_duration_s=float(moon_duration_s),
        tick_interval_s=float(wh.MOONFIRE_TICK_INTERVAL_S),
        periodic_spell_power_coefficient_per_tick=float(moon_tick_coeff),
        school="Arcane",
        source_url=moon_source_url,
        provenance={
            "ruleset": "forever",
            "source_kind": "current_public_forever_tooltip_fact",
            "source_module": "src.rulesets.forever.classes.druid.wowhead_facts",
            "confidence": "high",
            "indexed_rank_fact": moon_index,
            "numeric_authority": moon_index["source_authority"] if moon_index else "legacy_tooltip_not_index_verified",
        },
        refresh_rule="replace",
    )
    moonfire_action, moonfire_raw = normalize_direct_periodic_action(
        fact=moonfire_fact, actor=actor, resource=mana_resource
    )
    maintenance_facts = []
    triggers = ()
    # Source-ranked long-lived stat aura. Every numeric value comes from the
    # canonical Forever source-index after-tooltip, not the obsolete fixed L20
    # anchor. Derived stat/capacity coefficients are the separately sourced
    # primary-stat conversion records carried by the actor IR.
    from src.game.data.forever.source_maintenance_ranks import latest_stat_maintenance_rank
    mark_rank = latest_stat_maintenance_rank('druid', 'Mark of the Wild', level)
    mark_action = None
    if mark_rank is not None:
        bonus=float(mark_rank['attributes'])
        deltas={'armor':float(mark_rank['armor'])}
        for stat in ('strength','agility','stamina','intellect','spirit'):
            if bonus:
                deltas[stat]=bonus
        if mark_rank['resistances']:
            for school in ('holy','fire','nature','frost','shadow','arcane'):
                deltas[f'resistance_{school}']=float(mark_rank['resistances'])
        # Derived stats and capacity are resolved at cast time from the
        # canonical source conversion rules on the geared actor. This avoids
        # applying threshold curves to naked stats before gear is selected.
        mark_aura_id=f"source_maintenance:mark_of_the_wild:{mark_rank['spell_id']}"
        mark_action=ActionDefinition(
            id=f"source_spell:{mark_rank['spell_id']}",family_key='mark_of_the_wild',
            name='Mark of the Wild',owner_actor_id=actor.id,
            requirements=({'kind':'minimum_level','value':int(mark_rank['level'])},
                          {'kind':'mode_is','value':'caster'}),
            costs=(ResourceCost(resource_id='mana',amount=float(mark_rank['mana_cost'])),),
            cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
            effects=(StatusAuraEffect('status_aura',mark_aura_id,'actor',
                float(mark_rank['duration_s']), actor_stat_deltas=deltas,
                apply_primary_stat_conversions=True),),
            provenance=({'authority':'canonical_forever_spell_index_after_tooltip',
                         'source_spell_id':int(mark_rank['spell_id']),
                         'url':mark_rank['source_url'],
                         'acquisition_status':mark_rank['acquisition_status']},),
            metadata={'maintenance_aura_id':mark_aura_id,
                      'source_fact_status':'source_backed_raw_tooltip',
                      'derived_stat_conversion_status':'sourced_primary_stat_facts',
                      'derived_stat_status':'runtime_source_conversion_including_mana_capacity',
                      'remaining_gap':'forever_specific_spirit_regen_and_spell_crit_fidelity_not_verified'},
        )
        maintenance_facts.append({
            'fact_kind':'maintenance_aura','family_key':'mark_of_the_wild',
            'name':'Mark of the Wild','policy_phase':'maintenance',
            'required_level':int(mark_rank['level']),
            'resource_id':'mana','resource_cost':float(mark_rank['mana_cost']),
            'duration_s':float(mark_rank['duration_s']),
            'effect':{'armor':mark_rank['armor'],'all_attributes':mark_rank['attributes'],
                      'all_resistances':mark_rank['resistances']},
            'source':{'provider':'wowhead','url':mark_rank['source_url'],
                      'source_status':'canonical_forever_spell_index_after_tooltip'},
            'execution_status':'executable_actor_stat_and_source_derived_health_mana_capacity',
            'maintenance_action_id':mark_action.id,'aura_id':mark_aura_id,
            'amortization':'actual_cast_on_persistent_actor',
        })
    from src.game.data.forever.source_maintenance_ranks import latest_reactive_maintenance_rank
    thorns_rank = latest_reactive_maintenance_rank('druid', 'Thorns', level)
    thorns_action = None
    if thorns_rank is not None:
        thorns_aura_id=f"source_maintenance:thorns:{thorns_rank['spell_id']}"
        thorns_action=ActionDefinition(
            id=f"source_spell:{thorns_rank['spell_id']}",family_key='thorns',name='Thorns',
            owner_actor_id=actor.id,
            requirements=({'kind':'minimum_level','value':int(thorns_rank['level'])},
                          {'kind':'mode_is','value':'caster'}),
            costs=(ResourceCost(resource_id='mana',amount=float(thorns_rank['mana_cost'])),),
            cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
            effects=(StatusAuraEffect('status_aura',thorns_aura_id,'actor',
                float(thorns_rank['duration_s'])),),
            provenance=({'authority':'canonical_forever_spell_index_after_tooltip',
                         'provider':'wowhead','source_spell_id':int(thorns_rank['spell_id']),
                         'url':thorns_rank['source_url'],
                         'acquisition_status':thorns_rank['acquisition_status']},),
            metadata={'maintenance_aura_id':thorns_aura_id,
                      'source_fact_status':'source_backed_raw_tooltip',
                      'maintenance_cost_scoped_to_real_100_mob_runtime':True},
        )
        thorns_trigger_id = f"thorns:{thorns_rank['spell_id']}:reactive"
        maintenance_facts.append({
            "fact_kind": "maintenance_aura", "family_key": "thorns",
            "name": "Thorns", "policy_phase": "maintenance",
            "required_level": int(thorns_rank['level']),
            "resource_id": "mana", "resource_cost": float(thorns_rank['mana_cost']),
            "duration_s": float(thorns_rank['duration_s']),
            "effect": {"reactive_nature_damage": int(thorns_rank['reactive_damage'])},
            "source": {"provider": "wowhead", "url": thorns_rank['source_url'],
                       "source_status": "source_backed_public_forever_anchor"},
            "execution_status": "executable_generic_event_trigger_runtime",
            "trigger_id": thorns_trigger_id,
            "maintenance_action_id": thorns_action.id,
            "aura_id": thorns_aura_id,
            "amortization": "long_lived_maintenance_not_charged_per_pull",
        })
        triggers = (TriggerDefinition(
            id=thorns_trigger_id, name="Thorns reactive damage", owner_actor_id=actor.id,
            event_kind="damage_taken", active_by_default=True, required_aura_id=thorns_aura_id, event_probability_field="hit_chance",
            effects=(DamageEffect(
                effect_type="damage", school="Nature", target="enemy",
                base_min=float(thorns_rank['reactive_damage']),
                base_max=float(thorns_rank['reactive_damage']),
                spell_power_coefficient=0.0,
                field_provenance={
                    "base_damage": ({
                        "authority": "canonical_forever_spell_index_after_tooltip",
                        "provider": "wowhead", "url": thorns_rank['source_url'],
                    },),
                },
            ),),
            provenance=({
                "authority": "canonical_game_ir", "provider": "wowhead",
                "url": thorns_rank['source_url'], "g31_scope": "generic_event_trigger_damage",
            },),
            metadata={
                "g31_scope": "generic_event_trigger_damage", "maintenance_family": "thorns",
                "activation": "long_lived_maintenance_assumed_active_per_pull",
                "amortization": "maintenance_cast_cost_not_charged_per_pull",
            },
        ),)
    healing_actions = []
    healing_facts = []
    ht_eligible = [row for row in wh.HEALING_TOUCH_RANKS if int(row[0]) <= level]
    if ht_eligible:
        ht_level, ht_mana, ht_cast, ht_min, ht_max, ht_coeff = ht_eligible[-1]
        ht_index = _index_fact(class_key='druid', name='Healing Touch',
            required_level=int(ht_level), effect_kind='direct_heal')
        if ht_index is not None:
            ht_mana, ht_cast = ht_index['mana'], ht_index['cast_s']
            ht_min, ht_max = ht_index['low'], ht_index['high']
        ht_identity = indexed_rank_identity(class_key='druid', name='Healing Touch',
            required_level=int(ht_level), db_path=selected_rank_db)
        ht_action, ht_raw = normalize_direct_heal_action(
            fact=DirectHealSourceFact(
                family_key="healing_touch", name="Healing Touch", rank_level=int(ht_level),
                resource_id="mana", resource_cost=float(ht_mana), cast_time_s=float(ht_cast),
                heal_min=float(ht_min), heal_max=float(ht_max), spell_power_coefficient=float(ht_coeff),
                source_url=ht_identity['source_url'] if ht_identity else wh.HEALING_TOUCH_SOURCE,
                provenance={
                    "ruleset": "forever", "source_kind": ht_index["source_authority"] if ht_index else "legacy_tooltip_unverified_index",
                    "source_module": "src.rulesets.forever.classes.druid.wowhead_facts", "confidence": "high",
                    "indexed_rank_fact": ht_index,
                    **(ht_identity or {}),
                },
            ),
            actor=actor, mana_resource=mana_resource, health_resource=health_resource,
        )
        healing_actions.append(ht_action)
        healing_facts.append(ht_raw)
    rejuv_eligible = [row for row in wh.REJUVENATION_RANKS if int(row[0]) <= level]
    if rejuv_eligible:
        r_level, r_mana, r_total, r_duration, r_tick_coeff = rejuv_eligible[-1]
        rejuv_index = _index_fact(class_key='druid', name='Rejuvenation',
            required_level=int(r_level), effect_kind='periodic_heal')
        if rejuv_index is not None:
            r_mana, r_total, r_duration = (rejuv_index['mana'], rejuv_index['total'],
                                           rejuv_index['duration_s'])
        r_identity = indexed_rank_identity(class_key='druid', name='Rejuvenation',
            required_level=int(r_level), db_path=selected_rank_db)
        r_action, r_raw = normalize_periodic_heal_action(
            fact=PeriodicHealSourceFact(
                family_key="rejuvenation", name="Rejuvenation", rank_level=int(r_level),
                resource_id="mana", resource_cost=float(r_mana), total_heal=float(r_total),
                duration_s=float(r_duration), tick_interval_s=float(wh.REJUVENATION_TICK_INTERVAL_S),
                spell_power_coefficient_per_tick=float(r_tick_coeff),
                source_url=r_identity['source_url'] if r_identity else wh.REJUVENATION_SOURCE,
                provenance={
                    "ruleset": "forever", "source_kind": rejuv_index["source_authority"] if rejuv_index else "legacy_tooltip_unverified_index",
                    "source_module": "src.rulesets.forever.classes.druid.wowhead_facts", "confidence": "high",
                    "indexed_rank_fact": rejuv_index,
                    **(r_identity or {}),
                },
                refresh_rule="replace",
            ),
            actor=actor, mana_resource=mana_resource, health_resource=health_resource,
        )
        healing_actions.append(r_action)
        healing_facts.append(r_raw)

    moonfire_aura_id = next(
        effect.aura_id for effect in moonfire_action.effects if isinstance(effect, PeriodicEffect)
    )
    policy = PolicyDefinition(
        id=f"forever:druid:caster-priority@{level}",
        label=f"{moonfire_action.name} if missing; {base_slice.actions[0].name} filler",
        rules=(
            PolicyRuleDefinition(
                id="periodic_if_missing", action_id=moonfire_action.id,
                conditions=(
                    PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),
                    PolicyCondition(kind="aura_missing", scope="target", aura_id=moonfire_aura_id),
                    PolicyCondition(kind="resource_threshold", resource_id="mana", operator="gte", threshold_source="action_cost"),
                ),
                provenance={"authority": "forever_source_adapter", "selection": "highest_source_backed_rank_at_or_below_level"},
            ),
            PolicyRuleDefinition(
                id="direct_filler", action_id=base_slice.actions[0].id,
                conditions=(
                    PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),
                    PolicyCondition(kind="resource_threshold", resource_id="mana", operator="gte", threshold_source="action_cost"),
                ),
                provenance={"authority": "forever_source_adapter", "selection": "highest_source_backed_rank_at_or_below_level"},
            ),
        ),
        maintenance=tuple(maintenance_facts),
        provenance={
            "authority": "canonical_game_ir",
            "producer": "forever_druid_source_adapter",
            "search_performed": False,
            "maintenance_semantics": "long_lived_auras_amortized_outside_per_pull_combat_evaluation",
        },
    )
    actions = (base_slice.actions + (moonfire_action,) + tuple(healing_actions)
               + ((thorns_action,) if thorns_action else ())
               + ((mark_action,) if mark_action else ()))
    resources = base_slice.resources
    rage_source_facts = ()
    mitigation_rules = ()
    incoming_attacks = ()
    incoming_source_facts = ()
    if level >= 10:
        rage_per_formula_damage = float(rage_rules.rage_from_damage_taken(level, 1.0))
        rage_resource = ResourceDefinition(
            id="rage", name="Rage", owner_actor_id=actor.id, scope="actor",
            state_status="event_driven_resource_definition", initial_amount=0.0, capacity=100.0,
            active_by_default=False, regeneration_per_s=0.0,
            event_gain_rules=(ResourceEventGainRule(
                id=f"forever:druid:rage:damage_taken_basis@{level}",
                event_kind="damage_taken_rage_basis", event_value_field="amount",
                multiplier=rage_per_formula_damage, flat_amount=0.0, required_mode_id="bear",
                provenance=({
                    **rage_rules.provenance(),
                    "g27_scope": "generic_event_resource_gain_formula_input",
                    "g28_scope": "incoming attack projection supplies damage_taken_rage_basis",
                },),
                metadata={
                    "formula_input": "damage_taken_rage_basis",
                    "raw_incoming_conversion": "incoming_event_projection:landed_raw_damage_x_fixed_armor_fraction",
                },
            ),),
            provenance=({
                **rage_rules.provenance(),
                "g27_scope": "generic_event_driven_rage_resource",
            },),
            metadata={
                "g27_scope": "event_driven_resource_gain_and_spend",
                "activation": "bear_mode_managed_by_generic_mode_runtime",
                "incoming_damage_basis": "g28_incoming_event_projection",
                "capacity": 100.0,
            },
        )
        resources = resources + (rage_resource,)
        rage_source_facts = ({
            "fact_kind": "event_driven_resource", "family_key": "rage", "name": "Rage",
            "required_level": 10, "capacity": 100.0,
            "event_kind": "damage_taken_rage_basis",
            "gain_per_formula_damage": rage_per_formula_damage,
            "source": rage_rules.provenance(),
            "g28_scope": "raw incoming attack/armor conversion represented by generic incoming attack projection",
        },)
        attacker_level = int(level) + 2
        mitigation = ArmorMitigationDefinition(
            id=f"forever:physical-armor-mitigation:attacker-l{attacker_level}",
            school="physical", armor_stat_id="armor",
            armor_constant=float(armor_constant(attacker_level)), reduction_cap=0.75,
            provenance=({
                "authority": "qualified_classic_proxy",
                "source_module": "src.rulesets.forever.shared.defense.armor_constant",
                "attacker_level": attacker_level,
                "note": "Forever has not published a replacement physical Armor curve; generic runtime executes the explicit source-compiled constant.",
            },),
            metadata={"g28_scope": "generic_armor_mitigation", "formula": "armor/(armor+constant)_capped"},
        )
        raw_dps = float(normal_world_raw_dps(attacker_level))
        incoming = IncomingAttackDefinition(
            id=f"forever:ordinary-world-melee@{level}", name="Ordinary world melee",
            source_actor_id="ordinary_world_mob", target_actor_id=actor.id, school="physical",
            raw_damage=raw_dps * 2.0, hit_chance=1.0, health_resource_id="health",
            mitigation_rule_id=mitigation.id,
            event_projections=(IncomingEventProjection(
                id=f"forever:druid:incoming-rage-fixed-armor-basis@{level}",
                event_kind="damage_taken_rage_basis", source_value_field="landed_raw_damage",
                event_value_field="amount",
                multiplier=0.5,
                provenance=({**rage_rules.provenance(), "g28_scope": "generic_incoming_event_projection"},),
                metadata={
                    "semantics": "Forever Rage ignores real Armor; project landed pre-mitigation damage through fixed 50% Armor assumption",
                    "real_armor_affects": "health_damage_only",
                    "absorbs_affect_rage_basis": False,
                },
            ),),
            provenance=({
                "authority": "forever_shared_world_mob_proxy",
                "source_module": "src.rulesets.forever.shared.mobs.normal_world_raw_dps",
                "attacker_level": attacker_level, "raw_dps": raw_dps, "representative_swing_s": 2.0,
            },),
            metadata={
                "g28_scope": "generic_incoming_attack_mitigation_survivability_and_resource_trigger_basis",
                "attack_schedule": "source-declared representative cadence consumed by G29 generic mode-policy orchestrator",
                "representative_swing_s": 2.0,
                "avoidance": "explicit hit_chance field; canonical derived avoidance not yet wired",
            },
        )
        mitigation_rules = (mitigation,)
        incoming_attacks = (incoming,)
        incoming_source_facts = ({
            "fact_kind": "incoming_attack_and_mitigation", "family_key": "ordinary_world_melee",
            "required_level": 10, "attacker_level": attacker_level, "raw_dps": raw_dps,
            "representative_swing_s": 2.0, "armor_constant": float(mitigation.armor_constant),
            "rage_basis": "landed_raw_damage * 0.5; independent of real Armor",
            "health_damage": "landed_raw_damage * (1 - real armor reduction)",
        },)
    modes = ()
    auto_attacks = ()
    mode_source_facts = ()
    auto_attack_source_facts = ()
    cat_source_facts = ()
    cat_policy = None
    bear_source_facts = ()
    bear_policy = None
    cross_mode_policy = None
    bear_mode = None
    bear_auto_attack = None
    if level >= int(wh.BEAR_FORM_LEVEL):
        base_mana = float(mana_resource.metadata.get("base_mana", 0.0))
        bear_form_cost = base_mana * float(wh.FERAL_FORM_BASE_MANA_PCT)
        enter_bear = ActionDefinition(
            id="bear_form:5487", family_key="bear_form", name="Bear Form", owner_actor_id=actor.id,
            requirements=(
                {"kind": "minimum_level", "value": int(wh.BEAR_FORM_LEVEL)},
                {"kind": "mode_is", "value": "caster"},
            ),
            costs=(ResourceCost(resource_id="mana", amount=bear_form_cost),),
            cast_time_s=0.0, gcd_s=float(wh.FERAL_FORM_GCD_S), cooldown_s=0.0,
            effects=(ModeChangeEffect(effect_type="mode_change", target_mode_id="bear"),),
            provenance=({
                "authority": "current_public_forever_tooltip_fact", "provider": "wowhead",
                "url": wh.SOURCES["bear_form"], "checked_at": "2026-10-08", "confidence": "high",
            },),
            metadata={
                "g29_scope": "bear_mode_entry",
                "mode_transition": "enter", "resource_cost_formula": "base_mana * 0.55",
                "base_mana": base_mana, "base_mana_pct": float(wh.FERAL_FORM_BASE_MANA_PCT),
            },
        )
        exit_bear = ActionDefinition(
            id="cancel_mode:bear", family_key="cancel_mode", name="Cancel Bear Form", owner_actor_id=actor.id,
            requirements=({"kind": "mode_is", "value": "bear"},), costs=(),
            cast_time_s=0.0, gcd_s=0.0, cooldown_s=0.0,
            effects=(ModeChangeEffect(effect_type="mode_change", target_mode_id="caster"),),
            provenance=({"authority": "generic_mode_control_semantic", "derived_from_mode": "bear", "confidence": "high"},),
            metadata={"g29_scope": "bear_mode_exit", "mode_transition": "exit"},
        )
        enrage_action = None
        if level >= int(wh.ENRAGE_LEVEL):
            enrage_action = ActionDefinition(
                id="enrage:5229", family_key="enrage", name="Enrage", owner_actor_id=actor.id,
                requirements=(
                    {"kind": "minimum_level", "value": int(wh.ENRAGE_LEVEL)},
                    {"kind": "mode_is", "value": "bear"},
                ),
                costs=(), cast_time_s=0.0, gcd_s=0.0, cooldown_s=float(wh.ENRAGE_COOLDOWN_S),
                effects=(
                    ResourceChangeEffect(
                        effect_type="resource_change", resource_id="rage", target="self",
                        operation="add", amount=float(wh.ENRAGE_INITIAL_RAGE),
                    ),
                    PeriodicResourceEffect(
                        effect_type="periodic_resource", resource_id="rage", target="self",
                        aura_id="enrage:5229:rage", amount_per_tick=float(wh.ENRAGE_PERIODIC_RAGE_PER_S),
                        duration_s=float(wh.ENRAGE_DURATION_S), tick_interval_s=1.0,
                        operation="add", refresh_rule="replace",
                        provenance=({
                            "authority": "current_public_forever_tooltip_fact", "provider": "wowhead",
                            "url": wh.SOURCES["enrage"], "checked_at": "2026-10-08", "confidence": "high",
                        },),
                        metadata={"g29_scope": "generic_periodic_resource_gain"},
                    ),
                ),
                provenance=({
                    "authority": "dated_blizzard_plus_current_public_forever_tooltip",
                    "blizzard": "https://worldofwarcraft.blizzard.com/en-us/news/24301515",
                    "wowhead": wh.SOURCES["enrage"], "checked_at": "2026-10-08", "confidence": "high",
                },),
                metadata={
                    "g29_scope": "bear_rage_generator",
                    "initial_rage": float(wh.ENRAGE_INITIAL_RAGE),
                    "periodic_rage_per_s": float(wh.ENRAGE_PERIODIC_RAGE_PER_S),
                    "duration_s": float(wh.ENRAGE_DURATION_S),
                    "armor_penalty": "explicit_fidelity_gap; resource generation executable first",
                },
            )

        swipe_action = None
        swipe_rank = max((row for row in wh.SWIPE_RANKS if int(row[0]) <= int(level)), default=None, key=lambda row: int(row[0]))
        if swipe_rank is not None:
            swipe_level, swipe_rage, swipe_damage, swipe_targets = swipe_rank
            swipe_action = ActionDefinition(
                id=f"swipe:{int(swipe_level)}", family_key="swipe", name="Swipe", owner_actor_id=actor.id,
                requirements=(
                    {"kind": "minimum_level", "value": int(swipe_level)},
                    {"kind": "mode_is", "value": "bear"},
                ),
                costs=(ResourceCost(resource_id="rage", amount=float(swipe_rage)),),
                cast_time_s=0.0, gcd_s=1.5, cooldown_s=0.0,
                effects=(DamageEffect(
                    effect_type="direct_damage", school="physical", target="enemy",
                    base_min=float(swipe_damage), base_max=float(swipe_damage), spell_power_coefficient=0.0,
                    field_provenance={
                        "base_damage": ({"provider": "wowhead", "url": wh.SOURCES["swipe_r1"], "checked_at": "2026-10-08"},),
                    },
                    unsupported_semantics=({
                        "semantic": "attack_power_scaling", "status": "explicit_gap",
                        "note": "Blizzard says Forever Swipe gains AP scaling; normalized coefficient deferred to fidelity sweep",
                    },),
                ),),
                provenance=({
                    "authority": "existing_forever_rank_fact", "provider": "wowhead",
                    "url": wh.SOURCES["swipe_r1"], "checked_at": "2026-10-08", "confidence": "high_for_rank_cost_flat_damage",
                },),
                metadata={
                    "g29_scope": "bear_action_policy_candidate", "max_targets": int(swipe_targets),
                    "attack_power_scaling": "explicit_gap",
                },
            )

        feral_weapon = weapon_for_level(level)
        primal_bite_action = None
        primal_rank = max((row for row in wh.PRIMAL_BITE_RANKS if int(row[0]) <= int(level)), default=None, key=lambda row: int(row[0]))
        if feral_weapon is not None and primal_rank is not None:
            primal_level, primal_rage, primal_mult, primal_flat = primal_rank
            primal_bite_action = ActionDefinition(
                id=f"primal_bite:{int(primal_level)}", family_key="primal_bite", name="Primal Bite", owner_actor_id=actor.id,
                requirements=(
                    {"kind": "minimum_level", "value": int(primal_level)},
                    {"kind": "mode_is", "value": "bear"},
                ),
                costs=(ResourceCost(resource_id="rage", amount=float(primal_rage)),),
                cast_time_s=0.0, gcd_s=1.5, cooldown_s=float(wh.PRIMAL_BITE_PUBLIC_FACT["cooldown_s"]),
                effects=(WeaponDamageEffect(
                    effect_type="weapon_damage", school="physical", target="enemy",
                    damage_source=AutoAttackDamageSource(
                        kind="equipped_weapon_dps_plus_attack_power", flat_dps=float(feral_weapon.weapon_dps),
                        attack_power_stat_id="attack_power", attack_power_per_dps=14.0,
                    ),
                    weapon_damage_time_s=float(BEAR_FORM_SWING_S), weapon_damage_multiplier=float(primal_mult),
                    flat_damage=float(primal_flat), hit_chance=1.0, crit_chance_on_landed_hit=0.0, crit_multiplier=2.0,
                    provenance=({
                        "authority": "current_public_forever_tooltip_fact", "provider": "wowhead",
                        "url": wh.SOURCES["primal_bite_r1"], "checked_at": "2026-10-08", "confidence": "high",
                    },),
                    metadata={"attack_table_fidelity": "declared_100pct_hit_0pct_crit_until_canonical_attack_table"},
                ),),
                provenance=({
                    "authority": "current_public_forever_tooltip_fact", "provider": "wowhead",
                    "url": wh.SOURCES["primal_bite_r1"], "checked_at": "2026-10-08", "confidence": "high",
                },),
                metadata={"g29_scope": "bear_action_policy_candidate", "high_threat": True},
            )

        bear_enabled = (exit_bear.id,) + (() if enrage_action is None else (enrage_action.id,)) + (() if swipe_action is None else (swipe_action.id,)) + (() if primal_bite_action is None else (primal_bite_action.id,))
        bear_mode = ModeDefinition(
            id="bear", label="Bear Form", initial=False, enabled_action_ids=bear_enabled,
            # Current public Bear tooltip exposes a level-scaled AP display, but
            # G29 deliberately does not freeze the level-60 display value into
            # every level. Canonical derived AP is a later fidelity primitive.
            stat_modifiers=(),
            resource_rules=(
                ModeResourceRule(resource_id="mana", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="health", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="rage", active=True, on_enter="preserve", on_exit="preserve"),
            ),
            provenance=({
                "authority": "current_public_forever_tooltip_fact", "provider": "wowhead",
                "url": wh.SOURCES["bear_form"], "checked_at": "2026-10-08", "confidence": "high",
            },),
            metadata={
                "g29_scope": "bear_mode_resource_action_runtime",
                "derived_attack_power": "explicit_gap_pending_canonical_primary_stat_conversion",
                "item_armor_multiplier": "explicit_gap", "health_bonus": "explicit_gap",
            },
        )
        if feral_weapon is not None:
            bear_auto_attack = AutoAttackDefinition(
                id="auto_attack:bear", name="Bear Form melee", owner_actor_id=actor.id,
                attack_type="melee", swing_time_s=float(BEAR_FORM_SWING_S), school="physical",
                damage_source=AutoAttackDamageSource(
                    kind="equipped_weapon_dps_plus_attack_power", flat_dps=float(feral_weapon.weapon_dps),
                    attack_power_stat_id="attack_power", attack_power_per_dps=14.0,
                ),
                required_mode_id="bear", hit_chance=1.0, crit_chance_on_landed_hit=0.0, crit_multiplier=2.0,
                provenance=({
                    "authority": "existing_forever_feral_weapon_source_fact", "source_url": feral_weapon.source_url,
                    "weapon_name": feral_weapon.name, "required_level": int(feral_weapon.required_level),
                    "weapon_dps": float(feral_weapon.weapon_dps), "form_swing_s": float(BEAR_FORM_SWING_S),
                    "confidence": "medium_for_weapon_dps_low_for_fixed_form_swing",
                },),
                metadata={"g29_scope": "bear_generic_auto_attack", "attack_table_fidelity": "declared_100pct_hit_0pct_crit"},
            )
            auto_attack_source_facts = ({
                "fact_kind": "auto_attack", "family_key": "bear_form_melee", "name": "Bear Form melee",
                "required_level": int(wh.BEAR_FORM_LEVEL), "swing_time_s": float(BEAR_FORM_SWING_S),
                "weapon_name": feral_weapon.name, "weapon_dps": float(feral_weapon.weapon_dps),
                "damage_formula": "(weapon_dps + attack_power / 14) * swing_time",
                "source": {"url": feral_weapon.source_url, "form_speed_status": "explicit_existing_parameter_pending_target_server_probe"},
            },)

        if enrage_action is not None and swipe_action is not None and primal_bite_action is not None:
            bear_policy = PolicyDefinition(
                id=f"forever:druid:bear-action-seed@{level}", label="Enrage; Swipe/Primal Bite searched",
                rules=(
                    PolicyRuleDefinition(
                        id="bear_enrage", action_id=enrage_action.id,
                        conditions=(PolicyCondition(kind="resource_threshold", resource_id="rage", operator="lt", value=20.0),),
                        provenance={"authority": "canonical_game_ir", "g29": "source_backed_rage_generator"},
                    ),
                    PolicyRuleDefinition(
                        id="bear_swipe", action_id=swipe_action.id,
                        conditions=(PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),),
                        provenance={"authority": "canonical_game_ir", "g29": "bear_action_candidate"},
                    ),
                    PolicyRuleDefinition(
                        id="bear_primal_bite", action_id=primal_bite_action.id,
                        conditions=(PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),),
                        provenance={"authority": "canonical_game_ir", "g29": "bear_action_candidate"},
                    ),
                ),
                provenance={
                    "authority": "canonical_game_ir", "producer": "forever_druid_source_adapter",
                    "search_performed": False, "g29_scope": "mode_action_policy_seed", "entry_action_id": enter_bear.id,
                },
            )

        caster_mode = ModeDefinition(
            id="caster", label="Caster", initial=True,
            enabled_action_ids=tuple(action.id for action in actions) + (enter_bear.id,),
            resource_rules=(
                ModeResourceRule(resource_id="mana", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="health", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="rage", active=False, on_enter="preserve", on_exit="preserve"),
            ),
            provenance=({"authority": "canonical_game_ir_mode_baseline", "ruleset": "forever"},),
        )
        actions = actions + (enter_bear, exit_bear) + (() if enrage_action is None else (enrage_action,)) + (() if swipe_action is None else (swipe_action,)) + (() if primal_bite_action is None else (primal_bite_action,))
        modes = (caster_mode, bear_mode)
        auto_attacks = (() if bear_auto_attack is None else (bear_auto_attack,))
        bear_source_facts = ({
            "fact_kind": "mode_action_policy", "family_key": "bear_form", "name": "Bear Form",
            "required_level": int(wh.BEAR_FORM_LEVEL), "resource_cost": bear_form_cost,
            "attack_power": "explicit_gap_pending_canonical_primary_stat_conversion",
            "rage_generator": (None if enrage_action is None else enrage_action.id),
            "swipe_action": (None if swipe_action is None else swipe_action.id),
            "primal_bite_action": (None if primal_bite_action is None else primal_bite_action.id),
            "source": {"provider": "wowhead", "url": wh.SOURCES["bear_form"], "checked_at": "2026-10-08"},
        },)

    if level >= int(wh.CAT_FORM_LEVEL):
        base_mana = float(mana_resource.metadata.get("base_mana", 0.0))
        cat_form_cost = base_mana * float(wh.CAT_FORM_BASE_MANA_PCT)
        combo_points = ResourceDefinition(
            id="combo_points", name="Combo Points", owner_actor_id=actor.id, scope="target",
            state_status="target_bound_resource_definition", initial_amount=0.0, capacity=5.0,
            active_by_default=True, regeneration_per_s=0.0,
            provenance=({
                "authority": "current_public_forever_tooltip_fact",
                "provider": "wowhead", "url": wh.SOURCES["claw_r1"],
                "checked_at": "2026-10-07", "confidence": "high",
            },),
            metadata={
                "g26_scope": "generic_target_bound_resource",
                "lifecycle": "bound_to_current_target_and_reset_with_new_target",
                "capacity": 5,
            },
        )
        energy = ResourceDefinition(
            id="energy", name="Energy", owner_actor_id=actor.id, scope="actor",
            state_status="mode_managed_resource_definition", initial_amount=float(wh.CAT_ENERGY_CAPACITY), capacity=float(wh.CAT_ENERGY_CAPACITY),
            active_by_default=False, regeneration_per_s=float(wh.CAT_ENERGY_REGEN_PER_S),
            provenance=({
                "authority": "forever_cat_form_mode_fact",
                "provider": "wowhead", "url": wh.SOURCES["cat_form"],
                "checked_at": "2026-09-21", "confidence": "high",
            },),
            metadata={
                "g25_scope": "generic_active_resource_regeneration_and_cat_action_gating",
                "regeneration_model": "continuous_average",
                "regeneration_fidelity": "10_energy_per_s_average; discrete server tick phase remains later fidelity work",
                "prepared_pull_initial_amount": float(wh.CAT_ENERGY_CAPACITY),
            },
        )
        enter_cat = ActionDefinition(
            id="cat_form:768", family_key="cat_form", name="Cat Form", owner_actor_id=actor.id,
            requirements=(
                {"kind": "minimum_level", "value": int(wh.CAT_FORM_LEVEL)},
                {"kind": "mode_is", "value": "caster"},
            ),
            costs=(ResourceCost(resource_id="mana", amount=cat_form_cost),),
            cast_time_s=0.0, gcd_s=float(wh.FERAL_FORM_GCD_S), cooldown_s=0.0,
            effects=(ModeChangeEffect(effect_type="mode_change", target_mode_id="cat"),),
            provenance=({
                "authority": "current_public_forever_tooltip_fact",
                "provider": "wowhead", "url": wh.SOURCES["cat_form"],
                "checked_at": "2026-09-21", "confidence": "high",
            },),
            metadata={
                "g23_scope": "mode_entry",
                "mode_transition": "enter",
                "resource_cost_formula": "base_mana * cat_form_base_mana_pct",
                "base_mana": base_mana, "base_mana_pct": float(wh.CAT_FORM_BASE_MANA_PCT),
            },
        )
        exit_cat = ActionDefinition(
            id="cancel_mode:cat", family_key="cancel_mode", name="Cancel Cat Form", owner_actor_id=actor.id,
            requirements=({"kind": "mode_is", "value": "cat"},), costs=(),
            cast_time_s=0.0, gcd_s=0.0, cooldown_s=0.0,
            effects=(ModeChangeEffect(effect_type="mode_change", target_mode_id="caster"),),
            provenance=({
                "authority": "generic_mode_control_semantic",
                "derived_from_mode": "cat", "confidence": "high",
            },),
            metadata={"mode_transition": "exit"},
        )
        feral_weapon = weapon_for_level(level)
        # Only source-derived references are needed to seed policy rules.
        # The executable Claw action is constructed by the shared compiler
        # after the complete modes/resources/auto-attacks have been assembled.
        from src.game.data.forever.source_ability_semantics import latest_source_action_ref
        claw_action = (latest_source_action_ref('druid','claw',level)
                       if feral_weapon is not None else None)
        # All source values come from canonical SQLite's current Rake tooltip
        # and separately sourced effect semantics. No old wh.RAKE_RANKS fallback.
        from src.game.data.forever.sqlite_rake import load_rake_facts
        rake_fact = load_rake_facts(level)
        # Source-backed melee/bleed action is compiled by the shared SQLite
        # semantic compiler in _with_sqlite_talents, not constructed here.
        # Only the seed policy's action/aura references are declared here.
        rake_action_id = f"rake:{rake_fact['spell_id']}" if rake_fact is not None else None
        # Finisher rank/identity and executable effects both come from SQLite.
        # No Rank-1 hardcoding or stale rank-5 damage proxy in the provider.
        rip_action = (latest_source_action_ref('druid','rip',level)
                      if claw_action is not None else None)
        if rip_action is not None:
            cat_policy = PolicyDefinition(
                id=f"forever:druid:cat-builder-finisher@{level}",
                label="Source-ranked finisher at searched combo-point threshold; Claw filler",
                rules=(
                    PolicyRuleDefinition(
                        id="cat_finisher", action_id=rip_action.id,
                        conditions=(
                            PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),
                            PolicyCondition(kind="resource_threshold", resource_id="combo_points",
                                operator="gte", value=1.0,
                                search_values=(1.0,2.0,3.0,4.0,5.0)),
                        ),
                        provenance={"authority":"canonical_game_ir","producer":"source_ranked_finisher_seed"},
                    ),
                    *((PolicyRuleDefinition(
                        id="cat_rake_maintenance", action_id=rake_action_id,
                        conditions=(PolicyCondition(kind="aura_missing", aura_id=f"rake:{rake_fact['spell_id']}:bleed"),),
                        provenance={"authority":"canonical_game_ir", "source_spell_id":rake_fact["spell_id"]},
                    ),) if rake_action_id is not None else ()),
                    PolicyRuleDefinition(
                        id="cat_builder", action_id=claw_action.id,
                        conditions=(PolicyCondition(kind="target_state", field="alive", operator="eq", value=True),),
                        provenance={"authority":"canonical_game_ir", "producer":"source_ranked_builder_seed"},
                    ),
                ),
                provenance={"authority":"canonical_game_ir", "producer":"forever_druid_source_adapter",
                            "search_performed":False,"entry_action_id":enter_cat.id},
            )
            cat_source_facts = ({
                "fact_kind":"required_source_action", "family_key":"rip",
                "spell_id":rip_action.spell_id,"action_id":rip_action.id,
                "source_url":rip_action.source_url,
            },)

        if claw_action is not None:
            cat_source_facts = cat_source_facts + ({
                "fact_kind":"required_source_action", "family_key":"claw",
                "spell_id":claw_action.spell_id, "action_id":claw_action.id,
            },)
        if rake_fact is not None:
            cat_source_facts = cat_source_facts + ({
                "fact_kind":"required_source_action", "family_key":"rake",
                "spell_id":rake_fact["spell_id"], "action_id":rake_action_id,
            }, {
                "fact_kind":"source_backed_direct_periodic_melee",
                "family_key":"rake", "spell_id":rake_fact["spell_id"],
                "source_build":rake_fact["source_build"], "raw":dict(rake_fact),
                "executable":True,
            },)

        caster_enabled = tuple(action.id for action in actions) + (enter_cat.id,)
        caster_mode = ModeDefinition(
            id="caster", label="Caster", initial=True, enabled_action_ids=caster_enabled,
            resource_rules=(
                ModeResourceRule(resource_id="mana", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="health", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="energy", active=False, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="rage", active=False, on_enter="preserve", on_exit="preserve"),
            ),
            provenance=({"authority": "canonical_game_ir_mode_baseline", "ruleset": "forever"},),
        )
        cat_mode = ModeDefinition(
            id="cat", label="Cat Form", initial=False, enabled_action_ids=(exit_cat.id,), 
            stat_modifiers=(
                ModeStatModifier(target_stat="attack_power", kind="add_flat", value=float(wh.CAT_FORM_AP_FLAT)),
                ModeStatModifier(
                    target_stat="attack_power", kind="add_stat_scaled",
                    source_stat="agility", value=float(wh.CAT_FORM_AP_PER_AGILITY),
                ),
            ),
            resource_rules=(
                ModeResourceRule(resource_id="mana", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="health", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="energy", active=True, on_enter="preserve", on_exit="preserve"),
                ModeResourceRule(resource_id="rage", active=False, on_enter="preserve", on_exit="preserve"),
            ),
            provenance=({
                "authority": "current_public_forever_tooltip_fact",
                "provider": "wowhead", "url": wh.SOURCES["cat_form"],
                "checked_at": "2026-09-21", "confidence": "high",
            },),
            metadata={
                "g23_scope": "mode_transition_stat_modifiers_and_resource_activation",
                "g25_scope": "energy_regeneration_and_claw_action_gating",
            },
        )
        if feral_weapon is not None:
            cat_auto_attack = AutoAttackDefinition(
                id="auto_attack:cat", name="Cat Form melee", owner_actor_id=actor.id,
                attack_type="melee", swing_time_s=float(CAT_FORM_SWING_S), school="physical",
                damage_source=AutoAttackDamageSource(
                    kind="equipped_weapon_dps_plus_attack_power",
                    flat_dps=float(feral_weapon.weapon_dps),
                    attack_power_stat_id="attack_power", attack_power_per_dps=14.0,
                ),
                required_mode_id="cat", hit_chance=1.0, crit_chance_on_landed_hit=0.0,
                crit_multiplier=2.0,
                provenance=({
                    "authority": "existing_forever_feral_weapon_source_fact",
                    "source_url": feral_weapon.source_url,
                    "weapon_name": feral_weapon.name,
                    "required_level": int(feral_weapon.required_level),
                    "weapon_dps": float(feral_weapon.weapon_dps),
                    "form_swing_s": float(CAT_FORM_SWING_S),
                    "confidence": "medium_for_weapon_dps_low_for_fixed_form_swing",
                },),
                metadata={
                    "g24_scope": "generic_swing_timer_weapon_dps_ap_and_expected_hit_outcome",
                    "attack_table_fidelity": "declared_100pct_hit_0pct_crit_until_canonical_attack_table_and_derived_crit",
                    "weapon_stats_beyond_dps": "not_applied_in_g24",
                    "energy_and_cat_ability_cadence": "g25_claw_energy_gating_present; combo_points_deferred_to_g26",
                },
            )
            # Keep the historical G24 Cat probe first while adding Bear as a
            # separate source-declared repeated attack for G29.
            auto_attacks = (cat_auto_attack,) + auto_attacks
            auto_attack_source_facts = auto_attack_source_facts + ({
                "fact_kind": "auto_attack", "family_key": "cat_form_melee",
                "name": "Cat Form melee", "required_level": int(wh.CAT_FORM_LEVEL),
                "swing_time_s": float(CAT_FORM_SWING_S),
                "weapon_name": feral_weapon.name, "weapon_dps": float(feral_weapon.weapon_dps),
                "damage_formula": "(weapon_dps + attack_power / 14) * swing_time",
                "hit_resolution": "expected_value_declared_probabilities",
                "source": {
                    "url": feral_weapon.source_url,
                    "note": feral_weapon.note,
                    "form_speed_status": "explicit_existing_parameter_pending_target_server_probe",
                },
            },)

        actions = actions + (enter_cat, exit_cat) 
        resources = resources + (energy, combo_points)
        if claw_action is not None and bear_policy is not None and enrage_action is not None and primal_bite_action is not None:
            cross_mode_policy = PolicyDefinition(
                id=f"forever:druid:cross-mode-cat-bear@{level}",
                label="Cat until Energy spent; transition to Bear",
                rules=(
                    PolicyRuleDefinition(
                        id="g30_enter_cat", action_id=enter_cat.id,
                        conditions=(
                            PolicyCondition(kind="mode_state", operator="eq", value="caster"),
                            PolicyCondition(kind="resource_threshold", resource_id="mana", operator="gte", value=float(mana_resource.initial_amount) - cat_form_cost / 2.0),
                        ),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_transition"},
                    ),
                    PolicyRuleDefinition(
                        id="g30_cat_builder", action_id=claw_action.id,
                        conditions=(
                            PolicyCondition(kind="mode_state", operator="eq", value="cat"),
                            PolicyCondition(kind="resource_threshold", resource_id="energy", operator="gte", threshold_source="action_cost"),
                        ),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_action"},
                    ),
                    PolicyRuleDefinition(
                        id="g30_exit_cat", action_id=exit_cat.id,
                        conditions=(
                            PolicyCondition(kind="mode_state", operator="eq", value="cat"),
                            PolicyCondition(kind="resource_threshold", resource_id="energy", operator="lt", value=sum(float(x.amount) for x in claw_action.costs if x.resource_id == "energy")),
                        ),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_transition"},
                    ),
                    PolicyRuleDefinition(
                        id="g30_enter_bear", action_id=enter_bear.id,
                        conditions=(
                            PolicyCondition(kind="mode_state", operator="eq", value="caster"),
                            PolicyCondition(kind="resource_threshold", resource_id="mana", operator="lt", value=float(mana_resource.initial_amount) - cat_form_cost / 2.0),
                        ),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_transition"},
                    ),
                    PolicyRuleDefinition(
                        id="g30_bear_enrage", action_id=enrage_action.id,
                        conditions=(
                            PolicyCondition(kind="mode_state", operator="eq", value="bear"),
                            PolicyCondition(kind="resource_threshold", resource_id="rage", operator="lt", value=20.0),
                        ),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_action"},
                    ),
                    PolicyRuleDefinition(
                        id="g30_bear_attack", action_id=primal_bite_action.id,
                        conditions=(PolicyCondition(kind="mode_state", operator="eq", value="bear"),),
                        provenance={"authority": "canonical_game_ir", "g30": "generic_mode_action"},
                    ),
                ),
                provenance={
                    "authority": "canonical_game_ir", "producer": "forever_druid_source_adapter",
                    "search_performed": False, "g30_scope": "cross_mode_policy_candidate",
                    "mode_path": ["caster", "cat", "caster", "bear"],
                },
            )
        modes = (caster_mode, cat_mode) + (() if bear_mode is None else (bear_mode,))
        mode_source_facts = ({
            "fact_kind": "mode_transition", "family_key": "cat_form",
            "name": "Cat Form", "required_level": int(wh.CAT_FORM_LEVEL),
            "resource_cost": cat_form_cost, "resource_cost_formula": "base_mana * 0.55",
            "attack_power_flat": float(wh.CAT_FORM_AP_FLAT),
            "attack_power_per_agility": float(wh.CAT_FORM_AP_PER_AGILITY),
            "source": {"provider": "wowhead", "url": wh.SOURCES["cat_form"], "checked_at": "2026-09-21"},
        },)

    return _with_sqlite_talents(source_enrich_armor(replace(
        base_slice,
        id=f"forever:druid:caster-healing-slice@{level}",
        resources=resources, actions=actions, policies=(policy,) + (() if cat_policy is None else (cat_policy,)) + (() if bear_policy is None else (bear_policy,)) + (() if cross_mode_policy is None else (cross_mode_policy,)), modes=modes, auto_attacks=auto_attacks,
        mitigation_rules=mitigation_rules, incoming_attacks=incoming_attacks, triggers=triggers,
        source_facts=base_slice.source_facts + (moonfire_raw,) + tuple(healing_facts) + tuple(maintenance_facts) + rage_source_facts + incoming_source_facts + bear_source_facts + mode_source_facts + auto_attack_source_facts + cat_source_facts,
        provenance={
            **dict(base_slice.provenance),
            "periodic_source_family": "moonfire",
            "rank_selection": {"moonfire": "highest_source_backed_rank_at_or_below_level"},
            "policy_authority": "canonical_game_ir",
            "policy_ids": [p.id for p in ((policy,) + (() if cat_policy is None else (cat_policy,)) + (() if bear_policy is None else (bear_policy,)) + (() if cross_mode_policy is None else (cross_mode_policy,)))],
            "mode_authority": ("canonical_game_ir" if modes else None),
            "mode_ids": [mode.id for mode in modes],
            "auto_attack_authority": ("canonical_game_ir" if auto_attacks else None),
            "auto_attack_ids": [attack.id for attack in auto_attacks],
            "mitigation_authority": ("canonical_game_ir" if mitigation_rules else None),
            "mitigation_rule_ids": [rule.id for rule in mitigation_rules],
            "incoming_attack_ids": [attack.id for attack in incoming_attacks],
            "trigger_authority": ("canonical_game_ir" if triggers else None),
            "trigger_ids": [trigger.id for trigger in triggers],
            "maintenance_source_families": [x["family_key"] for x in maintenance_facts],
            "healing_source_families": [x["family_key"] for x in healing_facts],
            "health_resource_status": health_resource.state_status,
        },
    )
    ))


def _with_sqlite_talents(ir):
    from src.game.data.forever.mode_resource_facts import apply_mode_resource_facts
    ir = replace(ir, modes=apply_mode_resource_facts('druid', ir.modes))
    from src.game.data.forever.source_ability_semantics import source_ability_actions
    ir = source_ability_actions(ir, class_key='druid', level=int(ir.actor.metadata['level']))
    inventory = load_sqlite_talents(
        'druid', level=int(ir.actor.metadata['level']), action_families=(action.family_key for action in ir.actions),
        mode_labels={re.sub(r'[^a-z0-9]+', '_', mode.label.lower()).strip('_'): mode.id
                     for mode in ir.modes})
    # Executing an armor stat in an isolated incoming-hit probe is not the
    # same as scoring that stat in the production policy/recovery objective.
    # Preserve these blockers until source form multipliers and enemy attack
    # scheduling are represented in the common runtime evaluation.
    runtime_blockers = []
    mode_map = {mode.id: mode for mode in ir.modes}
    for talent in inventory.talents:
        affected = {modifier.target_id for rank in talent.ranks for modifier in rank.modifiers
                    if modifier.target_type == 'mode' and modifier.kind.startswith('mode_armor_')}
        # Source percentages now execute in active L20 modes, but their
        # inherited Classic conversions and secondary effects are not a
        # verified Forever server stat model. Preserve precise blockers.
        kinds = {modifier.kind for rank in talent.ranks for modifier in rank.modifiers}
        if 'actor_stat_pct' in kinds:
            runtime_blockers.append({'talent_id': talent.id,
                'reasons': ['actor_primary_stat_secondary_effects_unverified']})
        if 'mode_derived_stat_pct' in kinds or 'mode_resource_capacity_pct' in kinds:
            runtime_blockers.append({'talent_id': talent.id,
                'reasons': ['derived_stat_conversion_classic_proxy_not_forever_verified',
                            'gear_stamina_not_executable_in_joint_search',
                            'base_strength_to_ap_conversion_not_complete']})
        if 'mode_resource_capacity_pct' in kinds:
            runtime_blockers.append({'talent_id': talent.id,
                'reasons': ['incoming_attacks_not_scheduled_in_policy_recovery_score']})
        if affected:
            runtime_blockers.append({'talent_id': talent.id,
                'reasons': ['incoming_attacks_not_scheduled_in_policy_recovery_score']})
            for mode_id in sorted(affected):
                mode = mode_map[mode_id]
                if mode.metadata.get('item_armor_multiplier') == 'explicit_gap':
                    runtime_blockers.append({'talent_id': talent.id, 'mode_id': mode_id,
                        'reasons': ['form_armor_multiplier_not_executable']})
    return replace(
        ir, talents=inventory.talents,
        provenance={**dict(ir.provenance),
                    'talent_authority': 'canonical_sqlite_forever_abilities',
                    'talent_source_families': [t.id for t in inventory.talents],
                    'talent_tree_rules': inventory.tree_rule,
                    'talent_sqlite_coverage': {
                        'captured': inventory.captured_count,
                        'expected': inventory.expected_count,
                        'batch_id': inventory.batch_id,
                        'complete': inventory.complete,
                        'blockers': list(inventory.blockers) + runtime_blockers,
                    }},
    )

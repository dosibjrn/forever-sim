from __future__ import annotations

"""G38 executable Forever Rogue L10-L20 slice.

Actual ability ranks/costs/CP ladders are linked to the Forever Wowhead
spell pages. Naked main-hand DPS, AP, speed, health and attack outcomes are
explicit *scenario proxies*; this is not a final leveling result.
"""
from src.game.model import (
    ActionDefinition, ActorDefinition, AutoAttackDamageSource, AutoAttackDefinition,
    GameIRSlice, PolicyCondition, PolicyDefinition, PolicyRuleDefinition,
    ResourceChangeEffect, ResourceCost, ResourceDefinition, ResourceScaledDirectDamageEffect,
    WeaponDamageEffect, TalentDefinition, TalentRankDefinition, TalentModifier,
)
from src.rulesets.forever.shared.defense import representative_player_hp

# (minimum level, spell id, ordinary weapon damage bonus)
SINISTER_RANKS = ((1, 1752, 3.0), (6, 1757, 6.0), (14, 1758, 10.0))
# Eviscerate tooltip min/max per combo point. R2 explicitly prints 14..22,
# 25..33 etc. R3 prints 6 + 19*n to 20 + 19*n.
EVISCERATE_RANKS = (
    (1, 2098, {n: 1.0 + 5 * n for n in range(1, 6)}, {n: 5.0 + 5 * n for n in range(1, 6)}),
    (8, 6760, {n: 3.0 + 11 * n for n in range(1, 6)}, {n: 11.0 + 11 * n for n in range(1, 6)}),
    (16, 6761, {n: 6.0 + 19 * n for n in range(1, 6)}, {n: 20.0 + 19 * n for n in range(1, 6)}),
)


def _url(spell_id: int, name: str) -> str:
    return f"https://www.wowhead.com/forever/spell={spell_id}/{name}"


def _fact(spell_id: int, name: str) -> tuple[dict, ...]:
    return ({"authority": "current_public_forever_tooltip", "provider": "wowhead",
             "url": _url(spell_id, name), "checked_at": "2026-10-08"},)


def build_source_slice(level: int) -> GameIRSlice | None:
    level = int(level)
    if not 10 <= level <= 20:
        return None
    # No invented named gear or canonical primary stat distributions.
    weapon_dps = 9.0 + 0.5 * level
    weapon_speed = 2.5
    actor = ActorDefinition(
        id="player", actor_type="player", state_status="explicit_qualified_rogue_scenario_proxy",
        base_stats={"weapon_dps": weapon_dps, "attack_power": 25.0 + 2.4 * level,
                    "damage_multiplier": 1.0},
        provenance=({"authority": "scenario_proxy_not_source_backed", "note":
                     "Weapon DPS/speed and Rogue AP are explicit scenario anchors, not optimized gear"},),
        metadata={"class_key": "rogue", "level": level, "weapon_speed_s": weapon_speed},
    )
    health = float(representative_player_hp(level, 0.0))
    resources = (
        ResourceDefinition(id="health", name="Health", owner_actor_id="player",
                           state_status="qualified_proxy_starting_state",
                           initial_amount=health, capacity=health),
        ResourceDefinition(id="energy", name="Energy", owner_actor_id="player",
                           state_status="qualified_proxy_starting_state",
                           initial_amount=100.0, capacity=100.0, regeneration_per_s=10.0,
                           provenance=({"authority": "classic_continuous_average_energy_model",
                                        "note": "Discrete 20-energy/2-second tick phase unresolved"},),
                           metadata={"regen_model": "10_energy_per_second_continuous_average"}),
        ResourceDefinition(id="combo_points", name="Combo Points", owner_actor_id="player",
                           scope="target", state_status="source_backed_starting_state",
                           initial_amount=0.0, capacity=5.0,
                           provenance=_fact(1757, "sinister-strike"),
                           metadata={"lifecycle": "target_bound_resets_on_new_target"}),
    )
    sinister_level, sinister_id, bonus = max(x for x in SINISTER_RANKS if x[0] <= level)
    ev_level, ev_id, minima, maxima = max(x for x in EVISCERATE_RANKS if x[0] <= level)
    weapon_source = AutoAttackDamageSource(kind="qualified_equipped_mainhand_proxy",
                                           dps_stat_id="weapon_dps", attack_power_stat_id="attack_power")
    builder = ActionDefinition(
        id=f"sinister_strike:{sinister_id}", family_key="sinister_strike", name="Sinister Strike",
        owner_actor_id="player", requirements=({"kind": "minimum_level", "value": sinister_level},),
        costs=(ResourceCost("energy", 45.0),), cast_time_s=0.0, gcd_s=1.0, cooldown_s=0.0,
        effects=(WeaponDamageEffect("weapon_damage", "physical", "enemy", weapon_source,
                                    weapon_speed, 1.0, bonus, hit_chance=1.0,
                                    crit_chance_on_landed_hit=0.0, provenance=_fact(sinister_id, "sinister-strike")),
                 ResourceChangeEffect("resource_change", "combo_points", "enemy", "add", 1.0)),
        provenance=_fact(sinister_id, "sinister-strike"),
        metadata={"g38": "source_rank_builder_target_combo_point",
                  "weapon_speed": "explicit_scenario_proxy"},
    )
    finisher = ActionDefinition(
        id=f"eviscerate:{ev_id}", family_key="eviscerate", name="Eviscerate",
        owner_actor_id="player",
        requirements=({"kind": "minimum_level", "value": ev_level},
                      {"kind": "resource_min", "resource_id": "combo_points", "value": 1.0}),
        costs=(ResourceCost("energy", 35.0),), cast_time_s=0.0, gcd_s=1.0, cooldown_s=0.0,
        effects=(ResourceScaledDirectDamageEffect(
            "resource_scaled_direct_damage", "physical", "enemy", "combo_points", "target",
            minima, maxima,
            # Forever tooltip displays numeric ladder but hides explicit AP term;
            # qualified Classic 0.03/CP formula is NOT asserted as Forever authority.
            attack_power_coefficient_per_resource=0.0,
            field_provenance={"damage_ladder": _fact(ev_id, "eviscerate")},
            unsupported_semantics=({"semantic": "eviscerate_attack_power_scaling",
                                    "status": "current_forever_server_formula_not_yet_normalized"},)),
                 ResourceChangeEffect("resource_change", "combo_points", "enemy", "set", 0.0)),
        provenance=_fact(ev_id, "eviscerate"),
        metadata={"g38": "generic_snapshot_damage_then_cp_consume",
                  "numeric_gap": "Forever Eviscerate AP scaling not normalized"},
    )
    auto = AutoAttackDefinition(
        id="rogue:auto:mainhand", name="Rogue main-hand autoattack",
        owner_actor_id="player", attack_type="melee", swing_time_s=weapon_speed,
        school="physical", damage_source=weapon_source, hit_chance=1.0,
        crit_chance_on_landed_hit=0.0,
        provenance=({"authority": "explicit_weapon_and_outcome_scenario_proxy"},),
    )
    policy = PolicyDefinition(
        id=f"forever:rogue:builder-finisher@{level}",
        label="Eviscerate at searched combo-point threshold; Sinister Strike filler",
        rules=(
            PolicyRuleDefinition("rogue_finisher", finisher.id,
                conditions=(PolicyCondition("target_state", field="alive", operator="eq", value=True),
                            PolicyCondition("resource_threshold", resource_id="combo_points",
                                            operator="gte", value=2.0,
                                            search_values=(1.0, 2.0, 3.0, 4.0, 5.0)))),
            PolicyRuleDefinition("rogue_builder", builder.id,
                conditions=(PolicyCondition("target_state", field="alive", operator="eq", value=True),)),
        ),
        provenance={"authority": "canonical_source_actions_qualified_numeric_scenario",
                    "g26_scope": "builder_finisher_threshold_seed", "entry_action_id": "",
                    "g38_scope": "generic_rogue_energy_combo_builder_finisher"},
    )
    improved_eviscerate = TalentDefinition(
        id="improved_eviscerate", name="Improved Eviscerate", tree_key="assassination", max_rank=3,
        ranks=tuple(TalentRankDefinition(rank=i, modifiers=(TalentModifier(
            "effect_damage_pct", "action_family", "eviscerate", pct,
            provenance={"provider":"wowhead_forever", "trait_id":135238,"rank":i}),),
            provenance={"source":"https://www.wowhead.com/forever/spell=14162/improved-eviscerate",
                        "trait_rank_pct":round(pct*100)})
            for i,pct in enumerate((.07,.13,.20),1)),
        provenance=_fact(14162,"improved-eviscerate"), metadata={"tier":1},
    )
    improved_sinister = TalentDefinition(
        id="improved_sinister_strike", name="Improved Sinister Strike", tree_key="combat", max_rank=2,
        ranks=tuple(TalentRankDefinition(rank=i, modifiers=(TalentModifier(
            "resource_cost_flat", "action_family", "sinister_strike", delta,
            provenance={"provider":"wowhead_forever", "trait_id":135271,"rank":i}),),
            provenance={"source":"https://www.wowhead.com/forever/spell=13732/improved-sinister-strike",
                        "trait_energy_delta":delta})
            for i,delta in enumerate((-3.0,-5.0),1)),
        provenance=_fact(13732,"improved-sinister-strike"), metadata={"tier":1},
    )
    return GameIRSlice(
        id=f"forever:rogue:L{level}:g38", ruleset="forever", actor=actor,
        resources=resources, actions=(builder, finisher), policies=(policy,),
        talents=(improved_eviscerate,improved_sinister),
        auto_attacks=(auto,), source_facts=({"family": "rogue_L10_20",
              "source_action_ids": [sinister_id, ev_id],
              "stealth_backstab": "excluded_no_position_opener_primitive"},),
        unsupported_semantics=(
            {"code": "rogue_primary_stats_and_named_weapon", "status": "explicit_proxy"},
            {"code": "full_hit_crit_glancing_dodge_and_offhand", "status": "not_resolved"},
            {"code": "eviscerate_ap_scaling", "status": "not_resolved"},
            {"code": "stealth_openers_backstab_and_positioning", "status": "not_resolved"},
            {"code": "real_energy_tick_phase", "status": "not_resolved"},
            {"code": "incoming_attacks_and_rogue_survivability", "status": "not_resolved"},
            {"code": "gear_talent_optimization_and_level_route", "status": "not_resolved"},
        ),
        provenance={"provider": "forever_rogue_source_adapter",
                    "g38_proof_scope": "generic_rogue_energy_combo_direct_finisher_policy",
                    "numeric_scope": "bounded_L10_20_combat_and_recovery_not_final_leveling_score"},
    )

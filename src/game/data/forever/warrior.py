from __future__ import annotations

"""G37 Forever Warrior data adapter: no Warrior-specific combat executor.

Spell ranks are pinned to current public Forever tooltips. Weapon and naked
primary stats are explicit L10-L30 proxies until a canonical Warrior player/
gear source is imported. This makes the executable bounded decision auditable,
not a claim of final Warrior leveling fidelity.
"""

from src.game.model import (
    ActionDefinition, ActorDefinition, AutoAttackDamageSource, AutoAttackDefinition,
    DamageEffect, GameIRSlice, ModeChangeEffect, ModeDefinition, ModeResourceRule,
    ModeStatModifier, PeriodicEffect, PeriodicResourceEffect, PolicyCondition,
    PolicyDefinition, PolicyRuleDefinition, ResourceChangeEffect, ResourceCost,
    ResourceDefinition, ResourceEventGainRule, TalentDefinition, TalentRankDefinition, TalentModifier,
)
from src.rulesets.forever.classes.druid.rage import rage_conversion
from src.rulesets.forever.shared.defense import representative_player_hp

BATTLE = "https://www.wowhead.com/forever/spell=2457/battle-stance"
DEFENSIVE = "https://www.wowhead.com/forever/spell=71/defensive-stance"
BLOODRAGE = "https://www.wowhead.com/forever/spell=2687/bloodrage"
RANKS_REND = (
    (10, 6546, 28.0, 12.0),
    (20, 6547, 45.0, 15.0),
)
RANKS_THUNDER = (
    (6, 461830, 10.0),
    (18, 461829, 23.0),
)
HEROIC_STRIKE = "https://www.wowhead.com/forever/spell=78/heroic-strike"


def _source(url: str) -> tuple[dict, ...]:
    return ({"authority": "current_public_forever_tooltip", "provider": "wowhead", "url": url,
             "verified_on": "2026-10-08"},)


def build_source_slice(level: int) -> GameIRSlice | None:
    level = int(level)
    if not 10 <= level <= 30:
        return None
    # Combat stats and example weapon are deliberately not labelled as sourced
    # Forever items. They are isolated scenario assumptions, not a gear pick.
    health = float(representative_player_hp(level, 0.0))
    proxy_weapon_dps = 8.0 + 0.6 * level
    actor = ActorDefinition(
        id="player", actor_type="player", state_status="explicit_qualified_warrior_scenario_proxy",
        base_stats={"attack_power": 30.0 + 2.0 * level,
                    "weapon_dps": proxy_weapon_dps, "damage_multiplier": 1.0,
                    "strength": 0.0, "stamina": 0.0, "agility": 0.0},
        provenance=({"authority": "scenario_proxy_not_source_backed", "note":
            "Naked Warrior AP, ordinary representative main-hand weapon DPS/speed not yet canonical"},),
        metadata={"class_key": "warrior", "level": level, "weapon_speed_s": 2.8,
                  "weapon_dps_proxy": proxy_weapon_dps,
                  "primary_stats_are_gear_deltas_only": True},
    )
    # Pre-expansion outgoing Rage conversion is damage/rageconversion * 7.5.
    # It is attached only to white melee events (not bleed or Thunder Clap).
    # Real incoming melee, crit, miss, stance Rage retention, and damage-basis
    # corrections stay fidelity gaps, never hidden adjustments to this score.
    rage_gain = ResourceEventGainRule(
        id=f"warrior:white_hit_rage:L{level}", event_kind="damage_dealt",
        event_value_field="amount", multiplier=7.5 / rage_conversion(level),
        filters={"auto_attack": True}, provenance=({
            "authority": "qualified_classic_pre_expansion_rage_conversion",
            "source": "https://www.bluetracker.gg/wow/topic/eu-en/83678537-the-new-rage-formula-by-kalgan/",
            "note": "Expected landed white damage, no crit table or incoming attacks; Classic basis until Forever verified",
        },),
    )
    rage = ResourceDefinition(
        id="rage", name="Rage", owner_actor_id=actor.id,
        state_status="event_driven_resource_definition", initial_amount=0.0, capacity=100.0,
        regeneration_per_s=0.0, event_gain_rules=(rage_gain,),
        provenance=({"authority": "forever_source_rage_resource_with_qualified_classic_white_gain"},),
    )
    health_resource = ResourceDefinition(
        id="health", name="Health", owner_actor_id=actor.id,
        state_status="qualified_proxy_starting_state", initial_amount=health, capacity=health,
        provenance=({"authority": "forever_shared_defense_proxy", "level": level},),
    )
    modes = (
        ModeDefinition(id="battle", label="Battle Stance", initial=True,
                       resource_rules=(ModeResourceRule("rage", True),), provenance=_source(BATTLE)),
        ModeDefinition(id="defensive", label="Defensive Stance", initial=False,
                       stat_modifiers=(ModeStatModifier("damage_multiplier", "add_flat", -0.10),),
                       resource_rules=(ModeResourceRule("rage", True),), provenance=_source(DEFENSIVE),
                       metadata={"damage_taken_reduction": "source_10_percent_not_yet_applied_without_incoming_attack_scheduler",
                                 "quest_unlocked": "assumed_at_L10_not_verified_for_specific_character"}),
    )
    actions: list[ActionDefinition] = [
        ActionDefinition(
            id="stance:battle:2457", family_key="battle_stance", name="Battle Stance",
            owner_actor_id=actor.id, requirements=({"kind": "mode_is", "value": "defensive"},),
            costs=(), cast_time_s=0, gcd_s=0, cooldown_s=1.0,
            effects=(ModeChangeEffect("mode_change", "battle"),), provenance=_source(BATTLE),
        ),
        ActionDefinition(
            id="stance:defensive:71", family_key="defensive_stance", name="Defensive Stance",
            owner_actor_id=actor.id, requirements=({"kind": "mode_is", "value": "battle"},),
            costs=(), cast_time_s=0, gcd_s=0, cooldown_s=1.0,
            effects=(ModeChangeEffect("mode_change", "defensive"),), provenance=_source(DEFENSIVE),
        ),
        ActionDefinition(
            id="bloodrage:2687", family_key="bloodrage", name="Bloodrage", owner_actor_id=actor.id,
            requirements=({"kind": "minimum_level", "value": 10},),
            costs=(ResourceCost("health", health * 0.2),), cast_time_s=0, gcd_s=0, cooldown_s=60.0,
            effects=(ResourceChangeEffect("resource_change", "rage", "actor", "add", 10.0),
                     PeriodicResourceEffect("periodic_resource", "rage", "actor", "bloodrage:2687:rage",
                                            1.0, 10.0, 1.0, provenance=_source(BLOODRAGE))),
            provenance=_source(BLOODRAGE), metadata={"health_cost_formula":
                "20% of qualified player-health proxy (canonical base health unavailable)"},
        ),
    ]
    rend_level, rend_id, rend_total, rend_duration = max(x for x in RANKS_REND if x[0] <= level)
    rend_url = f"https://www.wowhead.com/forever/spell={rend_id}/rend"
    actions.append(ActionDefinition(
        id=f"rend:{rend_id}", family_key="rend", name="Rend", owner_actor_id=actor.id,
        requirements=({"kind": "minimum_level", "value": rend_level},
                      {"kind": "mode_is", "value": "battle"}),
        costs=(ResourceCost("rage", 10.0),), cast_time_s=0, gcd_s=1.5, cooldown_s=0,
        effects=(PeriodicEffect("periodic_damage", "physical", "enemy", f"rend:{rend_id}:bleed",
                                rend_total, rend_duration, 3.0, field_provenance={
                                    "total_base_damage": _source(rend_url)}, unsupported_semantics=({
                                    "semantic": "periodic_crit", "status": "not_resolved",
                                    "note": "Forever Rend may crit; generic expected-value periodic crit not modelled"},)),),
        provenance=_source(rend_url), metadata={"g37": "source_damage_duration_rage_cost"},
    ))
    tc_level, tc_id, tc_damage = max(x for x in RANKS_THUNDER if x[0] <= level)
    tc_url = f"https://www.wowhead.com/forever/spell={tc_id}/thunder-clap"
    actions.append(ActionDefinition(
        id=f"thunder_clap:{tc_id}", family_key="thunder_clap", name="Thunder Clap",
        owner_actor_id=actor.id,
        requirements=({"kind": "minimum_level", "value": tc_level},
                      {"kind": "mode_is", "value": "battle"}),
        costs=(ResourceCost("rage", 20.0),), cast_time_s=0, gcd_s=1.5, cooldown_s=4,
        effects=(DamageEffect("direct_damage", "physical", "enemy", tc_damage, tc_damage,
                              field_provenance={"base_damage": _source(tc_url)}),),
        provenance=_source(tc_url), metadata={"max_targets": 10,
            "not_modelled": "10% enemy attack-speed debuff and multi-target optimization"},
    ))
    # First executable action is the 0-GCD Rage generator; backend G07 probes
    # intentionally execute actions[0] in the initial Battle Stance.
    actions = [actions[2], *actions[:2], *actions[3:]]
    attack = AutoAttackDefinition(
        id="warrior:auto:mainhand", name="Warrior main-hand autoattack", owner_actor_id=actor.id,
        attack_type="melee", swing_time_s=2.8, school="physical", required_mode_id=None,
        damage_source=AutoAttackDamageSource(kind="scenario_ordinary_mainhand",
                                             dps_stat_id="weapon_dps", attack_power_stat_id="attack_power"),
        hit_chance=1.0, crit_chance_on_landed_hit=0.0,
        provenance=({"authority": "explicit_weapon_scenario_proxy", "weapon_speed_s": 2.8},),
    )
    policy = PolicyDefinition(
        id=f"warrior:L{level}:rage_priority", label="Bloodrage > Rend if missing > Thunder Clap",
        rules=(PolicyRuleDefinition("warrior:bloodrage", "bloodrage:2687"),
               PolicyRuleDefinition("warrior:rend", f"rend:{rend_id}",
                                    conditions=(PolicyCondition(kind="aura_missing", scope="target",
                                                                aura_id=f"rend:{rend_id}:bleed"),)),
               PolicyRuleDefinition("warrior:thunder", f"thunder_clap:{tc_id}")),
        provenance={"authority": "generic_warrior_bounded_policy_seed", "source_backed_actions": True,
                    "combat_model": "qualified_weapon_and_white_rage_proxy"},
    )
    # Current Forever talent tooltip/trait: Improved Rend first-tier Arms,
    # ranks 12/23/35% (the visible R1 tooltip rounds to 15%; trait is explicit).
    rend_talent = TalentDefinition(
        id="improved_rend", name="Improved Rend", tree_key="arms", max_rank=3,
        ranks=tuple(TalentRankDefinition(rank=i, modifiers=(TalentModifier(
            "effect_damage_pct", "action_family", "rend", fraction,
            provenance={"provider":"wowhead_forever", "trait_id":135487, "rank":i}),),
            provenance={"source":"https://www.wowhead.com/forever/spell=12286/improved-rend",
                        "trait_rank_pct":round(fraction*100)})
            for i, fraction in enumerate((.12,.23,.35),1)),
        provenance=_source("https://www.wowhead.com/forever/spell=12286/improved-rend"),
        metadata={"tier":1, "qualified_tooltip_trait_mismatch": "rank1 visible tooltip 15%; trait 12%"},
    )
    return GameIRSlice(
        id=f"forever:warrior:L{level}:g37", ruleset="forever", actor=actor,
        resources=(health_resource, rage), actions=tuple(actions), policies=(policy,), talents=(rend_talent,),
        modes=modes, auto_attacks=(attack,), source_facts=({
            "family": "warrior_L10_20", "source_action_ids": [2687, rend_id, tc_id, 2457, 71],
            "heroic_strike": {"spell_id": 78, "source": HEROIC_STRIKE,
                              "status": "excluded_until_on_next_swing_semantics"},
        },), unsupported_semantics=(
            {"code": "named_warrior_weapon_and_primary_stats", "status": "explicit_proxy"},
            {"code": "full_melee_hit_crit_avoidance_and_bleed_crit", "status": "not_resolved"},
            {"code": "heroic_strike_on_next_swing", "status": "not_resolved"},
            {"code": "incoming_attack_scheduler_and_rage", "status": "not_resolved"},
            {"code": "stance_rage_retention_and_damage_taken", "status": "not_resolved"},
            {"code": "full_talent_and_level_route", "status": "not_resolved"},
        ), provenance={"provider": "forever_warrior_source_adapter", "numeric_scope":
                          "bounded_L10_30_executable_combat_and_recovery_not_final_leveling_score",
                          "g37_proof_scope": "generic_warrior_rage_stance_auto_action_policy"},
    )

from __future__ import annotations

"""G35 sourced Forever L24 Cat pet vertical slice on the generic combat engine.

Only rank/cost/family/scaling rules below are sourced. Equipment/RAP and the
older natural-weapon base curve are *scenario inputs*, not a precise L24 BiS
claim. No legacy Hunter scoring is called.
"""

from src.game.model import (
    ActorDefinition, ActorLinkModifier, ActionDefinition, AutoAttackDamageSource,
    AutoAttackDefinition, DamageEffect, ResourceCost, ResourceDefinition,
    PolicyDefinition, PolicyRuleDefinition,
)
from src.game.multi_actor_policy import execute_multi_actor_priority_policies
from src.rulesets.forever.classes.hunter.pets import (
    PET_FAMILIES, PET_BASE_FOCUS_REGEN_PER_S, modeled_damage_skills,
    FOREVER_PET_GUIDE_SOURCE,
)
from .simulator import CombatRuntime
from .state import ActorState, TargetState

OWNER = "g35:hunter"
PET = "g35:cat"
# Explicit scenario inputs: not masquerading as a canonical equipment loadout.
EXAMPLE_RAP = 100.0
EXAMPLE_MELEE_AP = 80.0
EXAMPLE_RANGED_WEAPON_DPS = 15.0
EXAMPLE_CRIT = 0.10
EXAMPLE_TARGET_HP = 360.0


def _source_record(label: str, url: str):
    return ({"authority": label, "url": url},)


def compile_hunter_cat_slice(*, level: int = 24, focused_fire_rank: int = 0,
                             bestial_discipline_rank: int = 0):
    """Compile canonical pet skill rows to reusable Actor/Action/Link IR."""
    if level < 24 or level >= 32:
        raise ValueError("G35 source-pinned skill-rank corridor is L24-L31")
    if focused_fire_rank not in (0, 1, 2) or bestial_discipline_rank not in (0, 1, 2):
        raise ValueError("invalid declared talent ranks")
    source = _source_record("forever_hunter_pet_client_data", FOREVER_PET_GUIDE_SOURCE)
    owner_ir = ActorDefinition(OWNER, "player", base_stats={
        "ranged_attack_power": EXAMPLE_RAP, "attack_power": EXAMPLE_MELEE_AP,
        "ranged_weapon_dps": EXAMPLE_RANGED_WEAPON_DPS,
        "critical_strike_chance": EXAMPLE_CRIT,
        "focused_fire_rank": focused_fire_rank, "damage_multiplier": 1.0,
    }, state_status="explicit_scenario_equipment_not_verified_bis", provenance=source)
    # Natural attack baseline still uses the older accepted proxy curve. It is
    # labeled as such, rather than presented as an official Forever pet DPS.
    pet_white_dps_proxy = (4.8 + 0.46*level) * float(PET_FAMILIES["cat"]["damage"])
    pet_ir = ActorDefinition(PET, "pet", base_stats={
        "attack_power": 0.0, "critical_strike_chance": 0.0,
        "damage_multiplier": 1.0,
    }, state_status="source_rank_actions_with_qualified_white_damage_proxy", provenance=source,
        metadata={"family": "cat", "white_dps_proxy": pet_white_dps_proxy})
    focus_regen = PET_BASE_FOCUS_REGEN_PER_S * (1.0 + 0.10*bestial_discipline_rank)
    resource = ResourceDefinition("focus", "Focus", PET, initial_amount=100, capacity=100,
                                  regeneration_per_s=focus_regen, state_status="source_regen_proxy_capacity",
                                  provenance=source)
    # The source-owned 10% highest AP + 100% crit, plus Focused Fire 1% per
    # rank to both while a pet is active. The cross-actor executor is generic.
    links = (
        ActorLinkModifier("pet_ap", OWNER, PET, ("ranged_attack_power", "attack_power"),
                          "attack_power", 0.10, "add_scaled", PET, source),
        ActorLinkModifier("pet_crit", OWNER, PET, ("critical_strike_chance",),
                          "critical_strike_chance", 1.0, "set_scaled", PET, source),
        ActorLinkModifier("owner_focused_fire", OWNER, OWNER, ("focused_fire_rank",),
                          "damage_multiplier", 0.01, "add_scaled", PET, source),
        ActorLinkModifier("pet_focused_fire", OWNER, PET, ("focused_fire_rank",),
                          "damage_multiplier", 0.01, "add_scaled", PET, source),
    )
    owner_auto = AutoAttackDefinition(
        id="hunter:auto_shot", name="Ranged Auto Shot", owner_actor_id=OWNER,
        attack_type="ranged", swing_time_s=2.5, school="physical",
        damage_source=AutoAttackDamageSource(kind="scenario_ranged_weapon_dps",
                                             dps_stat_id="ranged_weapon_dps"),
        hit_chance=1.0, crit_chance_stat_id="critical_strike_chance",
        provenance=({"authority": "scenario_input", "weapon_speed_s": 2.5,
                     "note": "not a verified named Forever weapon"},),
    )
    pet_auto = AutoAttackDefinition(
        id="cat:auto", name="Cat natural melee", owner_actor_id=PET,
        attack_type="melee", swing_time_s=2.0, school="physical",
        damage_source=AutoAttackDamageSource(kind="qualified_base_pet_dps_curve",
                    flat_dps=pet_white_dps_proxy, attack_power_stat_id="attack_power"),
        hit_chance=1.0, crit_chance_stat_id="critical_strike_chance", provenance=source,
    )
    actions = []
    for row in modeled_damage_skills("cat", level):
        name = str(row["skill"])
        actions.append(ActionDefinition(
            id=f"cat:{name}", family_key=f"pet:{name}", name=f"Cat {name.title()}",
            owner_actor_id=PET, requirements=(),
            costs=(ResourceCost("focus", float(row["focus"])),),
            cast_time_s=0, gcd_s=float(row["gcd_s"]), cooldown_s=float(row["cooldown_s"]),
            effects=(DamageEffect("damage", str(row["school"]), "enemy",
                                  float(row["damage"]), float(row["damage"]),
                                  crit_chance_stat_id="critical_strike_chance"),),
            provenance=_source_record("forever_rank_4_pet_spell", str(row["source"])),
        ))
    return owner_ir, pet_ir, resource, tuple(links), (owner_auto, pet_auto), tuple(actions)


def execute_hunter_pet_policy(*, policy_names: tuple[str, ...], focused_fire_rank: int = 0,
                              bestial_discipline_rank: int = 0, level: int = 24,
                              target_hp: float = EXAMPLE_TARGET_HP) -> dict:
    owner_ir, pet_ir, resource, links, autos, actions = compile_hunter_cat_slice(
        level=level, focused_fire_rank=focused_fire_rank,
        bestial_discipline_rank=bestial_discipline_rank)
    owner = ActorState.from_ir(owner_ir, ())
    pet = ActorState.from_ir(pet_ir, (resource,))
    runtime = CombatRuntime(actor=owner, companions=(pet,), actor_links=links,
                            target=TargetState.with_health("g35:level24_mob", target_hp),
                            auto_attacks=autos)
    known = {action.family_key.removeprefix("pet:"): action for action in actions}
    if len(set(policy_names)) != len(policy_names) or any(n not in known for n in policy_names):
        raise ValueError("pet policy contains duplicated or unavailable skill")
    policy = PolicyDefinition(id="hunter_pet:" + ">".join(policy_names),
                               label=" > ".join(policy_names) or "Auto only",
                               rules=tuple(PolicyRuleDefinition(id="pet:"+n,
                                  action_id=known[n].id) for n in policy_names))
    candidate = execute_multi_actor_priority_policies(
        runtime=runtime, policies=({PET: policy} if policy.rules else {}),
        actions=actions, max_time_s=60)
    trace = candidate.timeline
    damaging = [e for e in trace.events if e.kind == "Damage" and e.payload.get("applied")]
    return {
        "policy": list(policy_names), "target_hp": target_hp,
        "kill_s": trace.target_death_s, "stopped_reason": candidate.stopped_reason,
        "pet_focus_regen_per_s": pet.resource_regeneration_per_s["focus"],
        "pet_focus_end": pet.resources["focus"],
        "stats": {x.id: dict(x.stats) for x in (owner, pet)},
        "applied_actor_links": [dict(x) for x in runtime.applied_actor_links],
        "action_events": [e.as_dict() for e in trace.events if e.kind == "ActionStarted"],
        "damage_events": [e.as_dict() for e in damaging],
        "damage_by_actor": {x.id: sum(float(e.payload["amount"]) for e in damaging
                                      if e.actor_id == x.id) for x in (owner, pet)},
        "legacy_fallback": False,
    }


def search_hunter_pet_policy(*, level: int = 24, focused_fire_rank: int = 0,
                             bestial_discipline_rank: int = 0) -> dict:
    candidates = ((), ("bite",), ("claw",), ("bite", "claw"), ("claw", "bite"))
    results = [execute_hunter_pet_policy(policy_names=path, level=level,
                 focused_fire_rank=focused_fire_rank,
                 bestial_discipline_rank=bestial_discipline_rank) for path in candidates]
    valid = [x for x in results if x["kill_s"] is not None]
    if not valid:
        raise RuntimeError("no executable Hunter pet policy killed source scenario target")
    best = min(valid, key=lambda c: (c["kill_s"], len(c["policy"]), tuple(c["policy"])))
    no_pet = execute_hunter_pet_policy(policy_names=(), level=level,
                             focused_fire_rank=focused_fire_rank,
                             bestial_discipline_rank=bestial_discipline_rank)
    # Full no-pet baseline: owner alone, not pet auto with no active skills.
    owner_ir, _, _, _, autos, _ = compile_hunter_cat_slice(level=level,
                    focused_fire_rank=focused_fire_rank,
                    bestial_discipline_rank=bestial_discipline_rank)
    # Owner-only does not get Focused Fire, because active companion is absent.
    owner = ActorState.from_ir(owner_ir, ())
    baseline_runtime = CombatRuntime(actor=owner,
            target=TargetState.with_health("g35:level24_mob", EXAMPLE_TARGET_HP),
            auto_attacks=(autos[0],))
    baseline_run = execute_multi_actor_priority_policies(
            runtime=baseline_runtime, policies={}, actions=(), max_time_s=60)
    baseline = baseline_run.timeline
    return {
        "status": "executed", "class_name": "Hunter", "pet_family": "cat",
        "level": level, "numeric_authority": "source_pet_spells_and_scaling_with_explicit_scenario_weapon_and_white_dps_proxy",
        "source": FOREVER_PET_GUIDE_SOURCE,
        "source_pet_skill_urls": [str(x["source"]) for x in modeled_damage_skills("cat", level)],
        "selected_policy": list(best["policy"]), "pet_policy_candidates": [
             {"policy": x["policy"], "kill_s": x["kill_s"],
              "pet_focus_end": x["pet_focus_end"]} for x in results],
        "owner_only_kill_s": baseline.target_death_s,
        "owner_plus_pet_auto_kill_s": no_pet["kill_s"],
        "owner_plus_pet_policy_kill_s": best["kill_s"],
        "improvement_vs_owner_only_s": None if baseline.target_death_s is None
             else float(baseline.target_death_s)-float(best["kill_s"]),
        "selected_detail": best, "focus_regen_per_s": best["pet_focus_regen_per_s"],
        "modifiers": best["applied_actor_links"],
        "unsupported": ["exact_pet_white_damage_baseline", "pet_positioning_and_range",
                        "growl_threat_target_selection", "enemy_ai_pet_survivability",
                        "named_hunter_weapon_gear", "attack_table_avoidance", "talent_tree_path_legality"],
        "legacy_fallback": False,
    }

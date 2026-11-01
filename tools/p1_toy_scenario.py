"""Class-neutral P1 toy mob and paired effects experiment.

This is a bounded test fixture. Action + effects, resources, combat events,
incoming attacks and sourced auto-swings are executed by production gsim.
No spell/name/class branches. A true native Rust hybrid must be integrated
separately; using this helper alone is never hybrid-P1 certification.
"""
from __future__ import annotations
from dataclasses import replace
import math

from src.game.model.ir import (
    IncomingAttackDefinition, QueuedSwingEffect, ResourceChangeEffect,
    TargetStatDebuffEffect, ControlEffect, DamageEffect, WeaponDamageEffect,
)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.simulator import action_eligibility

TOY_MOB_HP = 20_000.
EXTRA_PLAYER_HP = 5_000.
MOB_HIT = 10.
SWING_SECONDS = 2.

def _starting_state(ir, action, mode):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.metadata["level"] = int(ir.actor.metadata["level"])
    if mode != actor.current_mode_id:
        actor.transition_mode(mode)
    # A safe oversized health pool, but 500 damage missing to let heals work.
    if "health" not in actor.resource_capacity:
        raise ValueError("SOURCE_ACTOR_HEALTH_MISSING")
    actor.resource_capacity["health"] += EXTRA_PLAYER_HP
    actor.resources["health"] = actor.resource_capacity["health"] - 500.
    for resource, capacity in actor.resource_capacity.items():
        if resource != "health" and resource in actor.resources and actor.resource_is_active(resource):
            actor.resources[resource] = float(capacity)
    # Realistic nonzero toy mitigation/debuff channels; these are fixture
    # numbers, NOT Forever source coefficients or class-specific game rules.
    target = TargetState.with_health("toy_mob", TOY_MOB_HP, armor=200.,
                                     attack_power=200., melee_attack_power=200.)
    if hasattr(target, "bind_resource_definitions"):
        target.bind_resource_definitions(ir.resources)
    for req in action.requirements:
        if not hasattr(req, "get"):
            raise ValueError("UNUSABLE_SOURCE_REQUIREMENT")
        if req.get("kind") == "relative_position_is":
            target.metadata["attacker_relative_position"] = str(req["value"])
        if req.get("kind") == "resource_min":
            rid = str(req.get("resource_id") or "")
            amount = float(req.get("value") or 0.)
            if rid in getattr(target, "resources", {}):
                cap = getattr(target, "resource_capacity", {}).get(rid)
                if cap is None or amount <= cap:
                    target.resources[rid] = max(float(target.resources[rid]), amount)
        if req.get("kind") == "resource_below_capacity":
            rid = str(req.get("resource_id") or "")
            if rid in actor.resource_capacity and rid in actor.resources:
                actor.resources[rid] = max(0., float(actor.resource_capacity[rid]) - 1.)
    # Generic resource-generating actions require room to show an effect.
    for effect in action.effects:
        if (isinstance(effect, ResourceChangeEffect)
                and effect.target in ("actor", "self")
                and effect.operation == "add"):
            rid = str(effect.resource_id)
            if rid in actor.resources and rid in actor.resource_capacity:
                actor.resources[rid] = min(float(actor.resources[rid]),
                                           float(actor.resource_capacity[rid]) * 0.25)
    return actor, target


def _numeric(value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("NONFINITE_RUNTIME_OBSERVATION")
    return round(v, 6)


def observable_state(rt):
    """Real runtime end state and accumulated effects, not cast bookkeeping."""
    actor, target = rt.actor, rt.target
    # An active aura is an observable state; inactive/bogus auras are NOT
    # automatically accepted as a meaningful gameplay effect by the P1 gate.
    kinds = {}
    total_heal = total_overheal = total_taken = 0.
    for event in rt.trace:
        kinds[event.kind] = kinds.get(event.kind, 0) + 1
        if event.kind == "Heal":
            total_heal += float(event.payload.get("amount", 0.))
            total_overheal += float(event.payload.get("overheal", 0.))
        elif event.kind == "IncomingAttackResolved":
            total_taken += float(event.payload.get("post_mitigation_damage", 0.))
    return {
        "mob_hp": _numeric(target.health),
        "mob_stat_modifiers": {
            str(k): [str(v[0]), _numeric(v[1]), int(v[2])]
            for k, v in sorted(target.active_stat_modifiers.items())
        },
        "mob_school_power_modifiers": {
            str(k): [str(v[0]), _numeric(v[1]), int(v[2])]
            for k, v in sorted(target.active_school_power.items())
        },
        "player_hp": _numeric(actor.resources.get("health", 0.)),
        "player_resources": {k: _numeric(v) for k, v in sorted(actor.resources.items())},
        "player_stats": {k: _numeric(v) for k, v in sorted(actor.stats.items())},
        "player_mode": actor.current_mode_id,
        "player_auras": sorted(map(str, actor.active_auras)),
        "mob_controls": {k: _numeric(v) for k, v in sorted(target.active_controls.items())},
        "mob_auras": sorted(map(str, getattr(target, "active_auras", {}))),
        "damage_dealt": _numeric(rt.result().total_damage),
        "healing": _numeric(total_heal),
        "overhealing": _numeric(total_overheal),
        "damage_taken": _numeric(total_taken),
        # Accumulated behavioral observations handle effects which expire
        # before the end state (DoTs/CC/aura lifetimes).
        "damage_event_count": kinds.get("Damage", 0),
        "heal_event_count": kinds.get("Heal", 0),
        "control_event_count": kinds.get("ControlApplied", 0),
        "debuff_event_count": kinds.get("TargetStatDebuffApplied", 0),
    }


def _run_one(ir, action, mode, *, muted: bool):
    actor, target = _starting_state(ir, action, mode)
    incoming = IncomingAttackDefinition(
        id="toy_hit", name="toy mob 10-damage swing",
        source_actor_id=target.id, target_actor_id=actor.id,
        school="physical", raw_damage=MOB_HIT, hit_chance=1.,
        health_resource_id="health",
        metadata={"representative_swing_s": SWING_SECONDS,
                  "melee_ap_per_dps": 14.,
                  "melee_ap_per_dps_source": "classic_melee_attack_power_per_dps_14",
                  "scenario_status": "user_defined_toy_attack_fixture"},
        provenance=({"source": "user_defined_P1_toy_mob_fixture", "damage": MOB_HIT},),
    )
    # A queued-swing spell (Maul) only deals damage on the real next white
    # swing. Use the exact sourced autoattack definition, not a fake proc.
    queued = [e for e in action.effects if isinstance(e, QueuedSwingEffect)]
    attacks = tuple(a for a in ir.auto_attacks
                    if a.id in {e.auto_attack_id for e in queued})
    if len(attacks) != len(queued):
        raise ValueError("SOURCE_QUEUED_SWING_AUTOATTACK_MISSING")
    rt = CombatRuntime(actor=actor, target=target, auto_attacks=attacks,
                       incoming_attacks=(incoming,))
    if muted and action.metadata.get("aoe_center") == "actor":
        # The production engine correctly rejects a hostile-area cast without
        # any hostile-target effect. Neutralize magnitude, not AoE eligibility.
        # This is the SAME source-derived action, costs, time and area target.
        def neutral(effect):
            if getattr(effect, "target", None) != "enemies":
                raise ValueError("TOY_AOE_EFFECT_TARGET_UNKNOWN")
            if isinstance(effect, TargetStatDebuffEffect):
                return replace(effect, delta=0.)
            if isinstance(effect, ControlEffect):
                return replace(effect, proc_chance=0.)
            if isinstance(effect, DamageEffect):
                return replace(effect, base_min=0., base_max=0.)
            if isinstance(effect, WeaponDamageEffect):
                return replace(effect, weapon_damage_multiplier=0., flat_damage=0.)
            raise ValueError("TOY_NEUTRAL_AOE_EFFECT_NOT_IMPLEMENTED:"
                             + type(effect).__name__)
        if not action.effects:
            raise ValueError("TOY_NEUTRAL_AOE_EFFECT_NOT_IMPLEMENTED")
        real_or_muted = replace(
            action, effects=tuple(neutral(effect) for effect in action.effects))
    else:
        real_or_muted = replace(action, effects=()) if muted else action
    eligibility = action_eligibility(action=real_or_muted, actor=actor, target=target)
    if not eligibility.eligible:
        raise ValueError("ACTION_NOT_ELIGIBLE:" + str(eligibility.reason))
    rt.schedule_action(real_or_muted)
    # Short, bounded clock advance. Periodic ticks and incoming hits are
    # actually executed on the same production event queue.
    durations = [float(e.duration_s) for e in action.effects
                 if hasattr(e, "duration_s") and getattr(e, "duration_s", None) is not None]
    window = min(40., max(12., *(durations or [0.])))
    rt.advance_to(max(actor.current_time_s, 0.) + window)
    return observable_state(rt)


def compare_action(ir, action):
    """Paired action vs effect-free identical timing/cost on actual gsim."""
    modes = [m.id for m in ir.modes
             if m.enabled_action_ids is None or action.id in m.enabled_action_ids]
    if not ir.modes:
        modes = [None]
    if not modes:
        return {"status": "NO_SOURCE_LEGAL_MODE", "difference": {}}
    errors = []
    for mode in modes:
        try:
            real = _run_one(ir, action, mode, muted=False)
            inert = _run_one(ir, action, mode, muted=True)
            difference = {k: {"real": real[k], "without_effect": inert[k]}
                          for k in real if real[k] != inert[k]}
            # Costs, cast time, GCD and cooldown are the SAME both times.
            # No-effect outcomes are NOT credited as working spells.
            return {"status": "EFFECT_OBSERVED" if difference else "NO_OBSERVABLE_EFFECT",
                    "mode": mode, "difference": difference}
        except (ValueError, KeyError, TypeError, RuntimeError, AssertionError) as exc:
            errors.append(f"{mode}: {type(exc).__name__}: {exc}")
    return {"status": "UNEXECUTABLE_SETUP", "errors": errors[:4], "difference": {}}



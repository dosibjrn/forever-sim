from __future__ import annotations

"""G34 bounded executable two-actor *mechanics* witness.

The numbers below are deliberate, explicitly synthetic deterministic mechanics
fixtures; they are not Hunter or Warlock pet DPS estimates.  G35 owns real
source-backed class/pet policy and modifier compilation.
"""

from src.game.model import (
    ActorDefinition, ActionDefinition, AutoAttackDamageSource, AutoAttackDefinition,
    DamageEffect, ResourceCost, ResourceDefinition,
)
from .simulator import CombatRuntime
from .state import ActorState, TargetState


def execute_multi_actor_mechanics_probe() -> dict:
    owner_ir = ActorDefinition(id="g34:owner", actor_type="player", base_stats={"attack_power": 0},
                               state_status="synthetic_mechanics_probe")
    companion_ir = ActorDefinition(id="g34:companion", actor_type="pet", base_stats={"attack_power": 0},
                                   state_status="synthetic_mechanics_probe")
    owner_resource = ResourceDefinition(id="energy", name="Energy", owner_actor_id=owner_ir.id,
                                        initial_amount=100, capacity=100)
    companion_resource = ResourceDefinition(id="energy", name="Energy", owner_actor_id=companion_ir.id,
                                            initial_amount=30, capacity=40, regeneration_per_s=5)
    player_action = ActionDefinition(
        id="g34:owner:cast", family_key="probe_cast", name="Owner cast", owner_actor_id=owner_ir.id,
        requirements=(), costs=(ResourceCost(resource_id="energy", amount=30),),
        cast_time_s=3, gcd_s=1.5, cooldown_s=0,
        effects=(DamageEffect(effect_type="damage", school="arcane", target="enemy", base_min=40, base_max=40),),
        provenance=({"status": "synthetic_mechanics_probe"},),
    )
    pet_action = ActionDefinition(
        id="g34:companion:bite", family_key="probe_bite", name="Companion bite", owner_actor_id=companion_ir.id,
        requirements=(), costs=(ResourceCost(resource_id="energy", amount=15),),
        cast_time_s=0, gcd_s=1, cooldown_s=2,
        effects=(DamageEffect(effect_type="damage", school="physical", target="enemy", base_min=8, base_max=8),),
        provenance=({"status": "synthetic_mechanics_probe"},),
    )
    pet_auto = AutoAttackDefinition(
        id="g34:companion:auto", name="Companion natural melee", owner_actor_id=companion_ir.id,
        attack_type="melee", swing_time_s=2, school="physical",
        damage_source=AutoAttackDamageSource(kind="synthetic_mechanics_probe", flat_dps=6,
                                              attack_power_stat_id=None),
        provenance=({"status": "synthetic_mechanics_probe"},),
    )

    # Baseline uses exactly the same primary actor and action, but no companion.
    base_owner = ActorState.from_ir(owner_ir, (owner_resource,))
    base = CombatRuntime(actor=base_owner, target=TargetState.with_health("g34:target", 55))
    base.schedule_action(player_action)
    base.schedule_action(player_action)
    base.run_until_idle()
    baseline = base.result()

    owner = ActorState.from_ir(owner_ir, (owner_resource,))
    companion = ActorState.from_ir(companion_ir, (companion_resource,))
    runtime = CombatRuntime(
        actor=owner, companions=(companion,), target=TargetState.with_health("g34:target", 55),
        auto_attacks=(pet_auto,),
    )
    # Both actors start at t=0; enqueue is nonblocking, including player casts.
    runtime.enqueue_action(player_action)
    runtime.enqueue_action(pet_action)
    runtime.run_until_idle()
    result = runtime.result()
    damages = [e for e in result.events if e.kind == "Damage" and e.payload.get("applied")]
    return {
        "status": "executed", "scope": "synthetic_two_actor_mechanics_probe",
        "numeric_authority": "synthetic_not_forever_pet_tuning",
        "actor_ids": [owner.id, companion.id], "target_id": runtime.target.id,
        "baseline_kill_s": baseline.target_death_s,
        "companion_kill_s": result.target_death_s,
        "improvement_s": (baseline.target_death_s or 0) - (result.target_death_s or 0),
        "damage_events": [dict(e.as_dict()) for e in damages],
        "started_events": [e.as_dict() for e in result.events if e.kind == "ActionStarted"],
        "skipped_swing_events": [e.as_dict() for e in result.events if e.kind == "AutoAttackSwingSkipped"],
        "actor_damage": {
            aid: sum(float(e.payload.get("amount", 0)) for e in damages if e.actor_id == aid)
            for aid in (owner.id, companion.id)
        },
        "auto_swing_times_s": [float(e.time_s) for e in result.events if e.kind == "AutoAttackSwing"],
        "resources_after": {a.id: dict(a.resources) for a in (owner, companion)},
        "readiness": {a.id: {"gcd_ready_s": a.gcd_ready_s, "cooldowns": dict(a.cooldown_ready_s)}
                      for a in (owner, companion)},
        "shared_event_queue": True, "legacy_fallback": False,
    }

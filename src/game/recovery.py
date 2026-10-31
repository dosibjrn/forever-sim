from __future__ import annotations

"""Backend-neutral post-combat recovery over the same mutable ActorState.

G12 intentionally reuses the existing Forever ordinary food/water authority,
but recovery state is no longer reconstructed from scorer numbers.  The ActorState
that paid combat Action costs is the object restored here.  Direct heal Actions are
executed through the generic event runtime; periodic healing can overlap
ordinary food/water on the same recovery clock.
"""

from dataclasses import dataclass, replace
from copy import deepcopy
from typing import Any, Iterable, Mapping
from time import monotonic_ns, process_time_ns
from src.game.runtime.simulator import ComputeDeadlineExceeded

from src.game.model import ActionDefinition, HealEffect, PeriodicHealEffect, PeriodicResourceEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.game.runtime.simulator import expected_direct_heal
from src.rulesets.forever.shared.recovery import HealOption, food_tier, solve_recovery, water_tier


@dataclass(frozen=True)
class RecoveryExecutionResult:
    start_time_s: float
    end_time_s: float
    total_s: float
    resources_before: Mapping[str, float]
    resources_after: Mapping[str, float]
    health_missing_before: float
    mana_missing_before: float
    heal_action_id: str | None
    heal_casts: int
    heal_events: tuple[Mapping[str, Any], ...]
    food_s: float
    water_s: float
    food_tier: str
    water_tier: str
    passive_mana_regen_per_s: float
    method: str
    provenance: Mapping[str, Any]
    periodic_recovery_events: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_time_s": float(self.start_time_s),
            "end_time_s": float(self.end_time_s),
            "total_s": float(self.total_s),
            "resources_before": {str(k): float(v) for k, v in self.resources_before.items()},
            "resources_after": {str(k): float(v) for k, v in self.resources_after.items()},
            "health_missing_before": float(self.health_missing_before),
            "mana_missing_before": float(self.mana_missing_before),
            "heal_action_id": self.heal_action_id,
            "heal_casts": int(self.heal_casts),
            "heal_events": [dict(x) for x in self.heal_events],
            "food_s": float(self.food_s),
            "water_s": float(self.water_s),
            "food_tier": self.food_tier,
            "water_tier": self.water_tier,
            "passive_mana_regen_per_s": float(self.passive_mana_regen_per_s),
            "method": self.method,
            "periodic_recovery_events": int(self.periodic_recovery_events),
            "provenance": dict(self.provenance),
        }


def forever_classic_mana_regen_per_s(actor: ActorState) -> float:
    """Current shared Forever OOC mana semantic for naked caster state.

    Existing Druid/Hunter recovery uses ``15 + Spirit/5`` per two-second tick,
    i.e. ``7.5 + 0.1 * Spirit`` mana/s. Flat MP5 is absent from the current
    naked Generic Game IR slice and therefore is not silently invented here.
    """
    spirit = max(0.0, float(actor.stats.get("spirit", 0.0)))
    mp5 = max(0.0, float(actor.stats.get("mp5", 0.0)))
    return 7.5 + 0.1 * spirit + mp5 / 5.0


def _direct_heal_options(actions: Iterable[ActionDefinition], *, healing_power: float) -> tuple[tuple[ActionDefinition, HealOption], ...]:
    rows: list[tuple[ActionDefinition, HealOption]] = []
    for action in actions:
        # A compound direct+periodic heal cannot be represented as a one-shot
        # HealOption: its HoT overlaps food/water and may continue through the
        # next pull. Keep the executable action, but do not lie to this solver.
        if any(isinstance(effect, PeriodicHealEffect) for effect in action.effects):
            continue
        effects = [effect for effect in action.effects if isinstance(effect, HealEffect)]
        if len(effects) != 1:
            continue
        mana_cost = sum(float(cost.amount) for cost in action.costs if str(cost.resource_id) == "mana")
        rows.append((
            action,
            HealOption(
                name=action.id,
                heal=expected_direct_heal(effects[0], healing_power=healing_power),
                mana=mana_cost,
                cast_s=float(action.cast_time_s),
            ),
        ))
    return tuple(rows)


def _execute_paid_mana_channel(*, initial: ActorState, action: ActionDefinition,
                               remaining_actions: tuple[ActionDefinition, ...],
                               level: int, start: float, healing_power: float,
                               health_resource_id: str, mana_resource_id: str,
                               cpu_deadline_ns: int | None,
                               wall_deadline_ns: int | None):
    """One source action, its actual event clock, then paid ordinary recovery.

    Return None if it cannot legally start now; never wait through its cooldown.
    """
    trial = deepcopy(initial)
    trial.current_time_s = start
    if not action_eligibility(action=action, actor=trial).eligible:
        return None
    runtime = CombatRuntime(actor=trial,
        target=TargetState.with_health("mana_recovery_context", 1.0),
        enable_casting_regen=False)
    runtime.cpu_deadline_ns = cpu_deadline_ns
    runtime.wall_deadline_ns = wall_deadline_ns
    try:
        runtime.schedule_action(action)
        runtime.persist_actor_periodics()
    except (ValueError, RuntimeError):
        return None
    remaining = recover_actor_to_full(actor=trial, level=level,
        actions=remaining_actions, start_time_s=float(trial.current_time_s),
        healing_power=healing_power, health_resource_id=health_resource_id,
        mana_resource_id=mana_resource_id, cpu_deadline_ns=cpu_deadline_ns,
        wall_deadline_ns=wall_deadline_ns)
    return trial, remaining, tuple(e.as_dict() for e in runtime.trace)


def recover_actor_to_full(
    *, actor: ActorState, level: int, actions: Iterable[ActionDefinition], start_time_s: float,
    healing_power: float = 0.0, health_resource_id: str = "health", mana_resource_id: str = "mana",
    cpu_deadline_ns: int | None = None, wall_deadline_ns: int | None = None,
) -> RecoveryExecutionResult:
    """Recover the supplied post-combat ActorState to full HP/Mana.

    Mixed direct/periodic healing is searched and *actually executed* through
    generic Action/Event runtime. Food, water and HoT ticks overlap. When no
    periodic heal exists, the original direct-heal authority is preserved.
    """
    def check_deadline():
        if cpu_deadline_ns is not None and process_time_ns() >= cpu_deadline_ns:
            raise ComputeDeadlineExceeded(0,'CPU')
        if wall_deadline_ns is not None and monotonic_ns() >= wall_deadline_ns:
            raise ComputeDeadlineExceeded(0,'WALL')
    check_deadline()
    start = float(start_time_s)
    actor.current_time_s = start
    before = {str(k): float(v) for k, v in actor.resources.items()}
    hp = actor.resource_amount(health_resource_id)
    hp_cap = actor.resource_capacity.get(health_resource_id)
    mana = actor.resource_amount(mana_resource_id)
    mana_cap = actor.resource_capacity.get(mana_resource_id)
    if hp is None or hp_cap is None:
        raise ValueError("recovery requires actor health resource with capacity")
    has_mana = mana is not None and mana_cap is not None
    if (mana is None) != (mana_cap is None):
        raise ValueError("incomplete mana resource definition")
    hp_missing = max(0.0, float(hp_cap) - float(hp))
    mana_missing = max(0.0, float(mana_cap) - float(mana)) if has_mana else 0.0
    passive = forever_classic_mana_regen_per_s(actor) if has_mana else 0.0
    # ActorState owns the same passive HP5 clock in combat and recovery.
    # Ordinary food and HP5 overlap; neither is a free instantaneous heal.
    passive_health = max(0.0, float(actor.resource_regeneration_per_s.get(health_resource_id, 0.0)))

    # Source-defined mana channels compete with ordinary vendor water on the
    # *same* mutable actor/CombatRuntime clock. The baseline includes healing,
    # food, water, and pending periodic effects. A channel must beat that entire
    # baseline after paying its own cast/channel duration and remaining recovery.
    # No class-specific dispatch or invented fixed mana-per-second proxy.
    actions = tuple(actions)
    mana_channels = tuple(a for a in actions if bool(a.metadata.get("channel"))
        and any(isinstance(e, PeriodicResourceEffect) and e.target == "actor"
                and e.resource_id == mana_resource_id and e.operation == "add"
                for e in a.effects)) if has_mana and mana_missing > 1e-9 else ()
    if mana_channels:
        non_channels = tuple(a for a in actions if a not in mana_channels)
        initial = deepcopy(actor)
        baseline_actor = deepcopy(initial)
        baseline = recover_actor_to_full(actor=baseline_actor, level=level,
            actions=non_channels, start_time_s=start, healing_power=healing_power,
            health_resource_id=health_resource_id, mana_resource_id=mana_resource_id,
            cpu_deadline_ns=cpu_deadline_ns, wall_deadline_ns=wall_deadline_ns)
        best_actor, best_result, best_action_id = baseline_actor, baseline, None
        for action in mana_channels:
            check_deadline()
            candidate = _execute_paid_mana_channel(
                initial=initial, action=action, remaining_actions=non_channels,
                level=level, start=start, healing_power=healing_power,
                health_resource_id=health_resource_id,
                mana_resource_id=mana_resource_id,
                cpu_deadline_ns=cpu_deadline_ns, wall_deadline_ns=wall_deadline_ns)
            if candidate is None:
                continue
            trial, remaining, channel_trace = candidate
            elapsed = float(trial.current_time_s) - start
            if elapsed + 1e-9 < best_result.total_s:
                best_actor = trial
                best_action_id = action.id
                best_result = replace(remaining,
                    start_time_s=start, end_time_s=float(trial.current_time_s),
                    total_s=elapsed, resources_before=before,
                    health_missing_before=hp_missing, mana_missing_before=mana_missing,
                    heal_events=channel_trace + remaining.heal_events,
                    method="mana_channel+" + remaining.method)
        # Preserve the caller's ActorState identity across the encounter boundary.
        actor.__dict__.update(deepcopy(best_actor.__dict__))
        return replace(best_result, provenance={**best_result.provenance,
            "resource_recovery_decision": {
                "selected_action_id": best_action_id,
                "baseline_total_s": float(baseline.total_s),
                "selected_total_s": float(best_result.total_s),
                "candidate_count": len(mana_channels),
                "evaluation": "actual_CombatRuntime_plus_paid_vendor_recovery"}})

    # Compound direct+HoT spells and pure HoTs are valid recovery actions.
    # Search them on the same runtime clock as food/water, rather than
    # treating periodic healing as a direct heal or silently excluding it.
    actions = tuple(actions)
    if has_mana and (actor.pending_actor_periodic_events or
                     any(any(isinstance(e, PeriodicHealEffect) for e in a.effects) for a in actions)):
        from src.game.recovery_hot import optimize_mixed_recovery
        return optimize_mixed_recovery(
            actor=actor, level=int(level), actions=actions, start_time_s=start,
            healing_power=float(healing_power), health_resource_id=health_resource_id,
            mana_resource_id=mana_resource_id, passive=passive,
            cpu_deadline_ns=cpu_deadline_ns,wall_deadline_ns=wall_deadline_ns,
        )

    pairs = _direct_heal_options(actions,
        healing_power=actor.effective_healing_power(healing_power)) if has_mana else ()
    option_by_id = {opt.name: (action, opt) for action, opt in pairs}
    solve = solve_recovery(
        int(level), hp_missing, mana_missing, [opt for _, opt in pairs],
        passive_mana_regen_per_s=passive,
    )
    selected_action = None
    selected_casts = int(solve.heal_casts)
    if solve.heal_name is not None:
        selected_action = option_by_id.get(str(solve.heal_name), (None, None))[0]
    if selected_action is not None:
        total_mana_cost = sum(float(c.amount) for c in selected_action.costs if c.resource_id == mana_resource_id) * selected_casts
        if float(actor.resource_amount(mana_resource_id) or 0.0) + 1e-12 < total_mana_cost:
            selected_action = None
            selected_casts = 0

    heal_events: list[Mapping[str, Any]] = []
    if selected_action is not None and selected_casts > 0:
        context = TargetState.with_health("postcombat_recovery_context", 1.0, context="self_recovery")
        for _ in range(selected_casts):
            check_deadline()
            eligibility = action_eligibility(action=selected_action, actor=actor)
            if not eligibility.eligible and eligibility.reason == "action not ready: gcd/cooldown":
                wait_until = max(float(actor.current_time_s), float(eligibility.next_ready_s))
                actor.regenerate_for(wait_until - float(actor.current_time_s))
                actor.current_time_s = wait_until
                eligibility = action_eligibility(action=selected_action, actor=actor)
            if not eligibility.eligible:
                raise ValueError(f"selected recovery heal became ineligible: {eligibility.reason}")
            runtime = CombatRuntime(actor=actor, target=context, spell_power=float(healing_power),
                                    enable_casting_regen=False)
            runtime.cpu_deadline_ns=cpu_deadline_ns
            runtime.wall_deadline_ns=wall_deadline_ns
            runtime.schedule_action(selected_action)
            runtime.run_until_idle()
            heal_events.extend(event.as_dict() for event in runtime.result().events)
        heal_elapsed = max(0.0, float(actor.current_time_s) - start)
        if has_mana:
            actor.restore(mana_resource_id, passive * heal_elapsed)

    hp_now = float(actor.resource_amount(health_resource_id) or 0.0)
    mana_now = float(actor.resource_amount(mana_resource_id) or 0.0)
    hp_missing_after_heals = max(0.0, float(hp_cap) - hp_now)
    mana_missing_after_heals = max(0.0, float(mana_cap) - mana_now) if has_mana else 0.0
    food = food_tier(int(level))
    water = water_tier(int(level))
    food_s = hp_missing_after_heals / (food.rate_per_s + passive_health)
    water_s = mana_missing_after_heals / (water.rate_per_s + passive)
    sit_s = max(food_s, water_s)
    # Food/water and actor-owned periodic effects share one actor clock.
    # A no-mana Warrior can carry Bloodrage ticks into recovery just as a
    # caster can carry a HoT. Jumping current_time_s without processing the
    # pending queue left stale ticks and broke the next encounter.
    periodic_recovery_events = 0
    if sit_s > 0 and actor.pending_actor_periodic_events:
        recovery_runtime = CombatRuntime(
            actor=actor, target=TargetState.with_health('food_recovery_context', 1.0),
            enable_casting_regen=False)
        recovery_runtime.cpu_deadline_ns = cpu_deadline_ns
        recovery_runtime.wall_deadline_ns = wall_deadline_ns
        recovery_runtime.advance_to(float(actor.current_time_s) + sit_s)
        recovery_runtime.persist_actor_periodics()
        periodic_recovery_events = recovery_runtime.event_transitions
    else:
        actor.current_time_s = float(actor.current_time_s) + sit_s
    actor.restore(health_resource_id, hp_missing_after_heals)
    if has_mana:
        actor.restore(mana_resource_id, mana_missing_after_heals)
    end = float(actor.current_time_s)

    if selected_casts > 0:
        method = "generic_direct_heal+food+water"
    elif hp_missing > 0 and mana_missing > 0:
        method = "food+water"
    elif hp_missing > 0:
        method = "food"
    elif mana_missing > 0:
        method = "water"
    else:
        method = "none"

    return RecoveryExecutionResult(
        start_time_s=start,
        end_time_s=end,
        total_s=max(0.0, end - start),
        resources_before=before,
        resources_after={str(k): float(v) for k, v in actor.resources.items()},
        health_missing_before=hp_missing,
        mana_missing_before=mana_missing,
        heal_action_id=(selected_action.id if selected_action is not None else None),
        heal_casts=selected_casts,
        heal_events=tuple(heal_events),
        food_s=float(food_s),
        water_s=float(water_s),
        food_tier=food.name,
        water_tier=water.name if has_mana else "not_applicable",
        passive_mana_regen_per_s=passive,
        method=method,
        periodic_recovery_events=periodic_recovery_events,
        provenance={
            "ordinary_recovery_authority": "src.rulesets.forever.shared.recovery",
            "direct_heal_execution": "src.game.runtime.CombatRuntime",
            "state_continuity": "same ActorState instance from combat into recovery",
            "resource_profile": "health_and_mana" if has_mana else "health_only_no_mana",
            "health_capacity_fidelity": actor.metadata.get("health_capacity_fidelity", "resource metadata"),
            "passive_health_regen_per_s": passive_health,
        },
    )

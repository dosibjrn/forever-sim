from __future__ import annotations

"""Execute source-defined direct/periodic heals while ordinary food and water overlap.

The optimizer enumerates bounded *real* healing action sequences, rather than
converting a HoT into an instantaneous HealOption.  Candidate effects and
eligibility are executed by the shared CombatRuntime; the continuous recovery
rates are the existing Forever vendor authority.  No class or spell dispatch.
"""

from copy import deepcopy
from itertools import combinations, permutations
from math import ceil, inf
from time import process_time_ns, monotonic_ns
from src.game.runtime.simulator import ComputeDeadlineExceeded
from typing import Iterable

from src.game.model import ActionDefinition, HealEffect, PeriodicHealEffect
from src.game.runtime import CombatRuntime, TargetState, action_eligibility
from src.game.runtime.simulator import expected_direct_heal
from src.rulesets.forever.shared.recovery import food_tier, water_tier


def _plans(actions: Iterable[ActionDefinition], hp_missing: float, healing_power: float):
    healing = [a for a in actions if any(isinstance(e, (HealEffect, PeriodicHealEffect)) for e in a.effects)]
    direct = [a for a in healing if not any(isinstance(e, PeriodicHealEffect) for e in a.effects)]
    periodic = [a for a in healing if any(isinstance(e, PeriodicHealEffect) for e in a.effects)]
    yield ()
    for action in direct:
        heal = sum(expected_direct_heal(e, healing_power=healing_power)
                   for e in action.effects if isinstance(e, HealEffect))
        if heal <= 0: continue
        for count in range(1, int(ceil(hp_missing / heal)) + 1):
            block = (action,) * count
            yield block
            for hot in periodic:
                yield block + (hot,)
                yield (hot,) + block
    # Different aura families may overlap; repeat-casting one aura is not a
    # separate recovery option because its replacement is not additive.
    # Source downranks of one HoT share an aura family. Never enumerate
    # simultaneous ranks as independent, stacking heals: the runtime would
    # replace the aura, and these redundant candidates inflate compute.
    for size in range(1, min(len(periodic), 3) + 1):
        for subset in combinations(periodic, size):
            aura_ids=[e.aura_id for action in subset for e in action.effects
                      if isinstance(e, PeriodicHealEffect)]
            if len(aura_ids) != len(set(aura_ids)):
                continue
            for order in permutations(subset):
                yield order


def _simulate(actor, *, level: int, start: float, plan, healing_power: float,
              health_id: str, mana_id: str, passive: float,
              cpu_deadline_ns: int | None = None, wall_deadline_ns: int | None = None):
    """Return an executed candidate, or None if an action cannot be paid/cast."""
    _check_deadline(cpu_deadline_ns,wall_deadline_ns)
    trial = deepcopy(actor)
    trial.current_time_s = float(start)
    hp_cap = float(trial.resource_capacity[health_id])
    has_mana = mana_id in trial.resources
    mana_cap = float(trial.resource_capacity[mana_id]) if has_mana else 0.0
    runtime = CombatRuntime(actor=trial, target=TargetState.with_health('recovery_context', 1.0),
                            spell_power=float(healing_power), enable_casting_regen=False)
    runtime.cpu_deadline_ns=cpu_deadline_ns
    runtime.wall_deadline_ns=wall_deadline_ns
    for action in plan:
        _check_deadline(cpu_deadline_ns,wall_deadline_ns)
        gate = action_eligibility(action=action, actor=trial, target=runtime.target)
        if not gate.eligible and gate.reason == 'action not ready: gcd/cooldown':
            old = float(trial.current_time_s)
            runtime.advance_to(float(gate.next_ready_s))
            if has_mana: trial.restore(mana_id, passive * (trial.current_time_s - old))
            gate = action_eligibility(action=action, actor=trial, target=runtime.target)
        if not gate.eligible:
            return None
        old = float(trial.current_time_s)
        try:
            runtime.schedule_action(action)
        except (ValueError, RuntimeError):
            return None
        if has_mana: trial.restore(mana_id, passive * (trial.current_time_s - old))

    food_rate = food_tier(level).rate_per_s
    # runtime.advance_to() applies passive health regeneration itself.
    # Count it in time-to-full but do NOT restore it again with food.
    passive_health = max(0.0, float(trial.resource_regeneration_per_s.get(health_id, 0.0)))
    water_rate = water_tier(level).rate_per_s if has_mana else 0.0
    food_s = water_s = 0.0
    # All food/water and HoT ticks share one monotonic time axis. Advance to
    # whichever happens first: both resources full or the next queued tick.
    for _ in range(1000):
        _check_deadline(cpu_deadline_ns,wall_deadline_ns)
        hp_missing = max(0.0, hp_cap - float(trial.resource_amount(health_id) or 0.0))
        mana_missing = max(0.0, mana_cap - float(trial.resource_amount(mana_id) or 0.0)) if has_mana else 0.0
        if hp_missing <= 1e-8 and mana_missing <= 1e-8:
            break
        until_full = max(hp_missing / (food_rate + passive_health), mana_missing / (water_rate + passive))
        next_event = runtime.queue.peek_time() if runtime.queue else inf
        dt = min(until_full, max(0.0, float(next_event) - float(trial.current_time_s)))
        if dt > 0:
            food_s += min(dt, hp_missing / (food_rate + passive_health))
            if has_mana: water_s += min(dt, mana_missing / (water_rate + passive))
            # Apply continuous consumables before an event at the interval's
            # end, so a HoT tick is capped against the *current* health.
            trial.restore(health_id, food_rate * dt)
            if has_mana: trial.restore(mana_id, (water_rate + passive) * dt)
        runtime.advance_to(float(trial.current_time_s) + dt)
        if dt == 0 and next_event == inf:
            raise AssertionError('recovery stalled with missing resources')
    else:
        raise AssertionError('recovery did not converge within 1000 events')
    runtime.persist_actor_periodics()
    return trial, runtime, food_s, water_s


def _check_deadline(cpu_deadline_ns,wall_deadline_ns):
    if cpu_deadline_ns is not None and process_time_ns() >= cpu_deadline_ns:
        raise ComputeDeadlineExceeded(0,'CPU')
    if wall_deadline_ns is not None and monotonic_ns() >= wall_deadline_ns:
        raise ComputeDeadlineExceeded(0,'WALL')


def optimize_mixed_recovery(*, actor, level: int, actions: Iterable[ActionDefinition],
                            start_time_s: float, healing_power: float,
                            health_resource_id: str, mana_resource_id: str, passive: float,
                            cpu_deadline_ns: int | None = None, wall_deadline_ns: int | None = None):
    before = {str(k): float(v) for k, v in actor.resources.items()}
    hp_missing = max(0.0, float(actor.resource_capacity[health_resource_id]) - before[health_resource_id])
    best = None
    # Source-defined actions can be absent or ineligible (forms, mana, etc.).
    mana_missing = max(0.0, float(actor.resource_capacity[mana_resource_id]) - before[mana_resource_id]) \
        if mana_resource_id in before else 0.0
    # If drinking already dominates the full recovery window, spending mana
    # on any heal cannot shorten it. This is an exact monotone lower bound,
    # not a policy heuristic; passive mana gain is unchanged by healing.
    food_rate = food_tier(level).rate_per_s
    water_rate = water_tier(level).rate_per_s
    passive_health = max(0.0, float(actor.resource_regeneration_per_s.get(health_resource_id, 0.0)))
    only_ordinary = hp_missing <= 1e-9 or hp_missing / (food_rate + passive_health) <= mana_missing / (water_rate + passive) + 1e-9
    plans = ((),) if only_ordinary else _plans(actions, hp_missing, healing_power)
    for plan in plans:
        _check_deadline(cpu_deadline_ns,wall_deadline_ns)
        candidate = _simulate(actor, level=level, start=start_time_s, plan=plan,
                              healing_power=healing_power, health_id=health_resource_id,
                              mana_id=mana_resource_id, passive=passive,
                              cpu_deadline_ns=cpu_deadline_ns,wall_deadline_ns=wall_deadline_ns)
        if candidate is None: continue
        trial, runtime, food_s, water_s = candidate
        elapsed = max(0.0, float(trial.current_time_s) - float(start_time_s))
        key = (round(elapsed, 10), len(plan), tuple(a.id for a in plan))
        if best is None or key < best[0]:
            best = (key, trial, runtime, plan, food_s, water_s)
    if best is None:
        raise ValueError('no executable recovery candidate, including ordinary food/water')
    _, trial, runtime, plan, food_s, water_s = best
    pending_hot_auras = sorted({str(e.payload['aura_id'])
                               for e in trial.pending_actor_periodic_events})
    # Preserve the caller's original ActorState identity across combat/recovery.
    actor.__dict__.update(deepcopy(trial.__dict__))
    from src.game.recovery import RecoveryExecutionResult
    direct_casts = sum(any(isinstance(e, HealEffect) for e in a.effects) for a in plan)
    return RecoveryExecutionResult(
        start_time_s=float(start_time_s), end_time_s=float(actor.current_time_s),
        total_s=float(actor.current_time_s) - float(start_time_s),
        resources_before=before, resources_after={str(k): float(v) for k, v in actor.resources.items()},
        health_missing_before=hp_missing,
        mana_missing_before=max(0.0, float(actor.resource_capacity[mana_resource_id]) - before[mana_resource_id])
                            if mana_resource_id in before else 0.0,
        heal_action_id=plan[0].id if plan else None, heal_casts=len(plan),
        heal_events=tuple(e.as_dict() for e in runtime.result().events
                          if e.kind in ('Heal', 'AuraApplied', 'AuraReplaced', 'AuraExpired')),
        food_s=food_s, water_s=water_s,
        food_tier=food_tier(level).name,
        water_tier=water_tier(level).name if mana_resource_id in before else 'not_applicable',
        passive_mana_regen_per_s=passive,
        method='mixed_heal_hot+food+water' if plan else ('food+water' if hp_missing > 0 else 'water'),
        provenance={
            'ordinary_recovery_authority': 'src.rulesets.forever.shared.recovery',
            'healing_execution': 'src.game.runtime.CombatRuntime',
            'state_continuity': 'same ActorState instance from combat into recovery',
            'heal_action_sequence': [a.id for a in plan],
            'direct_heal_casts': direct_casts,
            'periodic_heal_casts': len(plan) - sum(not any(isinstance(e, PeriodicHealEffect) for e in a.effects) for a in plan),
            'food_water_overlap': True,
            'pending_hot_auras_carried_into_next_pull': pending_hot_auras,
            'pending_actor_periodic_events': len(trial.pending_actor_periodic_events),
            'candidate_scope': 'all single direct-rank repeated casts, up to three distinct HoTs, one direct block + one HoT in both orders',
            'health_capacity_fidelity': actor.metadata.get('health_capacity_fidelity', 'resource metadata'),
        },
    )

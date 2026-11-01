from __future__ import annotations

"""Generic execution of canonical Policy IR.

Policy data lives in Game IR. This module only evaluates reusable state
predicates and executes rules in priority order; it never constructs class or
spell rotations.
"""

from dataclasses import dataclass, replace
from typing import Any, Mapping

from src.game.model import (
    ActionDefinition,
    PolicyCondition,
    PolicyDefinition,
    PolicyRuleDefinition,
    SummonEffect,
    QueuedSwingEffect,
    ModeChangeEffect,
    ModeChangeEffect,
)
from src.game.runtime import ActionNotEligibleError, CombatRuntime, action_eligibility

# Compatibility names used by earlier G11 tests/callers. The authority is now
# src.game.model.ir, not local policy dataclasses.
PolicyRule = PolicyRuleDefinition
PriorityPolicy = PolicyDefinition


def remove_combat_policy_seeds_preserve_maintenance(ir):
    """Prevent historical APL seeding WITHOUT deleting sourced paid upkeep.

    Every optimizer must retain between-pull maintenance when clearing policy
    rules. Dropping entire PolicyDefinitions silently switches the L2 scorer to
    an unbuffed game while the continuous finalist scorer charges and applies
    the same buff. Merge unique maintenance facts by source action identity;
    conflicting declarations fail closed rather than selecting an arbitrary
    winner. This is class/spell-name independent.
    """
    maintenance={}
    for policy in ir.policies:
        for fact in policy.maintenance:
            action_id=fact.get('maintenance_action_id')
            aura_id=fact.get('aura_id')
            if not action_id or not aura_id:
                raise ValueError('INCOMPLETE_SOURCE_MAINTENANCE_DECLARATION')
            key=(str(action_id),str(aura_id))
            if key in maintenance and maintenance[key]!=fact:
                raise ValueError('CONFLICTING_SOURCE_MAINTENANCE_DECLARATION')
            maintenance[key]=fact
    if not maintenance:
        return replace(ir,policies=())
    only=PolicyDefinition(id=f'{ir.id}:maintenance_only',
        label='Sourced upkeep, no combat priority seed',rules=(),
        maintenance=tuple(maintenance[key] for key in sorted(maintenance)),
        provenance={'authority':'source_maintenance_only',
                    'historical_combat_priority_removed':True})
    return replace(ir,policies=(only,))


@dataclass(frozen=True)
class PolicyExecutionResult:
    policy_id: str
    selected_actions: tuple[Mapping[str, Any], ...]
    stopped_reason: str | None
    timeline: Any
    satisfied_mode_opening_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "selected_actions": [dict(x) for x in self.selected_actions],
            "stopped_reason": self.stopped_reason,
            "timeline": self.timeline.as_dict(),
            "satisfied_mode_opening_ids": list(self.satisfied_mode_opening_ids),
        }


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    op = str(operator or "eq")
    if op == "eq": return actual == expected
    if op == "ne": return actual != expected
    if op == "gte": return float(actual) >= float(expected)
    if op == "gt": return float(actual) > float(expected)
    if op == "lte": return float(actual) <= float(expected)
    if op == "lt": return float(actual) < float(expected)
    raise ValueError(f"unsupported policy comparison operator: {op}")


def _aura_host(scope: str, runtime: CombatRuntime):
    if scope == "target": return runtime.target
    if scope == "actor": return runtime.actor
    raise ValueError(f"unsupported aura scope: {scope or 'unknown'}")


def _resource_threshold_limit(condition: PolicyCondition, *, action: ActionDefinition) -> float:
    resource_id = str(condition.resource_id or "")
    if not resource_id:
        raise ValueError("resource_threshold condition missing resource_id")
    if condition.threshold_source == "action_cost":
        costs = [float(x.amount) for x in action.costs if str(x.resource_id) == resource_id]
        if not costs:
            raise ValueError(f"action {action.id!r} has no cost for resource {resource_id!r}")
        return sum(costs)
    if condition.threshold_source is None:
        if condition.value is None:
            raise ValueError("resource_threshold condition missing value")
        return float(condition.value)
    raise ValueError(f"unsupported resource threshold source: {condition.threshold_source}")


def _resource_threshold(condition: PolicyCondition, *, action: ActionDefinition, runtime: CombatRuntime) -> bool:
    resource_id = str(condition.resource_id or "")
    if not resource_id:
        raise ValueError("resource_threshold condition missing resource_id")
    current = runtime.resource_amount(resource_id)
    if current is None:
        return False
    threshold = _resource_threshold_limit(condition, action=action)
    return _compare(float(current), condition.operator or "gte", threshold)


def _resource_threshold_regen_ready_at(condition: PolicyCondition, *, action: ActionDefinition,
                                       runtime: CombatRuntime) -> float | None:
    """Only real actor-owned, active regeneration can satisfy a failed >= guard.

    A policy condition is checked before action_eligibility. Without this
    readiness, a sourced energy-cost guard can stop a fight while the actor
    could legally regenerate enough energy on its existing combat clock.
    Target-bound resources, nonmonotonic guards and unreachable thresholds
    never create a wait or a synthetic resource event.
    """
    if condition.kind != 'resource_threshold' or (condition.operator or 'gte') != 'gte':
        return None
    resource_id = str(condition.resource_id or '')
    definition = runtime.actor.resource_definitions.get(resource_id)
    if (definition is None or str(definition.scope or 'actor') != 'actor'
            or not runtime.actor.resource_is_active(resource_id)):
        return None
    current = runtime.actor.resource_amount(resource_id)
    capacity = runtime.actor.resource_capacity.get(resource_id)
    rate = float(runtime.actor.resource_regeneration_per_s.get(resource_id, 0.))
    threshold = _resource_threshold_limit(condition, action=action)
    if (current is None or capacity is None or rate <= 0.
            or threshold > float(capacity) + 1e-12 or float(current) >= threshold):
        return None
    # Advance through CombatRuntime, which charges the elapsed time and
    # produces actual ResourceRegenerated events. A nanosecond avoids a
    # floating-point equality loop at an exactly-on-threshold boundary.
    return float(runtime.actor.current_time_s) + (threshold-float(current))/rate + 1e-9


def _target_state(condition: PolicyCondition, *, runtime: CombatRuntime) -> bool:
    field = str(condition.field or "alive")
    if field == "alive": actual = bool(runtime.target.alive)
    elif field == "health": actual = float(runtime.target.health)
    elif field == "health_pct":
        actual = 0.0 if runtime.target.max_health <= 0 else float(runtime.target.health) / float(runtime.target.max_health)
    else:
        raise ValueError(f"unsupported target state field: {field}")
    return _compare(actual, condition.operator or "eq", condition.value)


def _actor_state(condition: PolicyCondition, *, runtime: CombatRuntime) -> bool:
    field = str(condition.field or 'health_pct')
    if field not in ('health', 'health_pct', 'alive'):
        raise ValueError('unsupported actor state field: ' + field)
    current = runtime.actor.resource_amount('health')
    if current is None:
        raise ValueError('actor health is unavailable in source runtime')
    if field == 'health': actual = float(current)
    elif field == 'alive': actual = float(current) > 0
    else:
        cap = runtime.actor.resource_capacity.get('health')
        if cap is None or float(cap) <= 0:
            raise ValueError('actor health capacity unavailable in source runtime')
        actual = float(current) / float(cap)
    return _compare(actual, condition.operator or 'lte', condition.value)


def _spatial_state(condition: PolicyCondition, *, runtime: CombatRuntime) -> bool:
    """Fail closed unless encounter owns simultaneous live 2D geometry.

    Sequential spaced-pull layout is not simultaneous encounter geometry.
    No implicit assumption that enemy_count is one or that targets coincide.
    """
    ctx = getattr(runtime, 'spatial_context', None)
    if not isinstance(ctx, dict) or not ctx.get('simultaneous_2d'):
        raise ValueError('BLOCKED_SIMULTANEOUS_2D_ENCOUNTER_CONTEXT_MISSING')
    if condition.kind == 'enemy_count':
        value = ctx.get('enemy_count_in_range') if condition.field=='in_range' else ctx.get('enemy_count_engaged')
    else:
        value = ctx.get('target_distance_yards')
    if value is None:
        raise ValueError('BLOCKED_SPATIAL_OBSERVABLE_UNAVAILABLE')
    return _compare(float(value), condition.operator or 'gte', condition.value)


def condition_matches(condition: PolicyCondition, *, action: ActionDefinition, runtime: CombatRuntime) -> bool:
    kind = str(condition.kind or "")
    if kind == 'aura_any_present':
        ids = condition.value
        if not isinstance(ids, (list,tuple)) or not ids or not all(isinstance(i,str) and i for i in ids):
            raise ValueError('aura_any_present condition requires sourced aura IDs')
        host = _aura_host(str(condition.scope or 'actor'), runtime)
        return any(i in host.active_auras and host.active_auras[i].expires_at_s > runtime.actor.current_time_s for i in ids)
    if kind in {"aura_present", "aura_missing"}:
        if not condition.aura_id:
            raise ValueError(f"{kind} condition missing aura_id")
        host = _aura_host(str(condition.scope or "target"), runtime)
        aura = host.active_auras.get(str(condition.aura_id))
        present = aura is not None and float(aura.expires_at_s) > float(runtime.actor.current_time_s) + 1e-12
        return present if kind == "aura_present" else not present
    if kind == 'target_control_missing':
        control_id=str(condition.value or '')
        if not control_id:
            raise ValueError('target_control_missing requires sourced control_id')
        return float(runtime.target.active_controls.get(control_id,0.0)) <= float(runtime.actor.current_time_s)+1e-12
    if kind == 'stored_cast_charges':
        # The candidate action itself attests the bank identity. An arbitrary
        # string in a policy cannot create a free state observable.
        spec=action.metadata.get('source_cast_charge_consumer') or {}
        bank=str(condition.field or '')
        if not bank or bank != spec.get('bank_id'):
            raise ValueError('UNKNOWN_SOURCE_CHARGE_BANK:'+bank)
        if type(condition.value) not in (int,float) or not 0 <= float(condition.value) <= int(16):
            raise ValueError('INVALID_SOURCE_CHARGE_THRESHOLD')
        count=runtime.actor.source_cast_charge_count(bank)
        return _compare(count,condition.operator or 'gte',condition.value)
    if kind == "resource_threshold":
        return _resource_threshold(condition, action=action, runtime=runtime)
    if kind == 'cooldown_ready':
        # Observe a real, source-known action cooldown. The condition is not
        # permission to execute that action in the current form; action
        # eligibility still checks mode, costs, GCD and other requirements.
        action_id = str(condition.field or '')
        known = {action.id}
        for mode in runtime.actor.mode_definitions.values():
            known.update(mode.enabled_action_ids or ())
        if not action_id or action_id not in known:
            raise ValueError('COOLDOWN_UNKNOWN_SOURCE_ACTION:' + action_id)
        if type(condition.value) is not bool or (condition.operator or 'eq') not in ('eq', 'ne'):
            raise ValueError('COOLDOWN_INVALID_BOOLEAN_PREDICATE')
        ready = float(runtime.actor.cooldown_ready_s.get(action_id, 0.)) <= float(runtime.actor.current_time_s) + 1e-12
        return _compare(ready, condition.operator or 'eq', condition.value)
    if kind == "mode_state":
        if condition.value is None:
            raise ValueError("mode_state condition missing value")
        return _compare(str(runtime.actor.current_mode_id or ""), condition.operator or "eq", str(condition.value))
    if kind == "target_state":
        return _target_state(condition, runtime=runtime)
    if kind == 'actor_state':
        return _actor_state(condition, runtime=runtime)
    if kind in ('enemy_count', 'target_distance'):
        return _spatial_state(condition, runtime=runtime)
    raise ValueError(f"unsupported policy condition: {kind or 'unknown'}")


def select_action(policy: PolicyDefinition, *, actions: Mapping[str, ActionDefinition], runtime: CombatRuntime):
    """Select the first condition-matching, currently legal combat Action."""
    readiness: list[float] = []
    for rule in policy.rules:
        if rule.phase != "combat":
            continue
        action = actions.get(rule.action_id)
        if action is None:
            raise KeyError(f"policy rule {rule.id!r} references missing Action {rule.action_id!r}")
        # A 2D priority policy may change targets as enemies approach.
        # Evaluate target-dependent guards AFTER choosing a reachable victim.
        if not runtime.select_reachable_target(action):
            continue
        unmet = tuple(c for c in rule.conditions
                      if not condition_matches(c, action=action, runtime=runtime))
        if unmet:
            # Eligibility only reports resource readiness for rules that pass
            # their guards. A sourced >= resource guard must itself contribute
            # a future wakeup when actual actor regeneration can satisfy it.
            guard_ready = tuple(_resource_threshold_regen_ready_at(
                c, action=action, runtime=runtime) for c in unmet)
            if all(t is not None for t in guard_ready):
                readiness.append(max(guard_ready))
            continue
        # A summon is a reusable actor lifecycle, not a spammable combat
        # action. A policy must not recast it while spawn is pending or its
        # companion remains active; ordinary action eligibility does not
        # inspect multi-actor runtime state.
        summon_effects = tuple(effect for effect in action.effects
                               if isinstance(effect, SummonEffect))
        if any(
            effect.summon_id not in runtime.timed_summons
            or effect.summon_id in runtime.summon_pending
            or runtime.actor_active.get(
                runtime.timed_summons[effect.summon_id].summoned_actor_id, False
            )
            for effect in summon_effects
        ):
            continue
        # A zero-GCD on-next-swing button can be pressed only once per queued
        # auto attack, even though it has no ordinary cooldown. Never let a
        # spammable priority rule abort the encounter before the swing lands.
        if any(isinstance(e, QueuedSwingEffect) and
               e.auto_attack_id in runtime.pending_queued_swing for e in action.effects):
            continue
        eligibility = action_eligibility(action=action, actor=runtime.actor, target=runtime.target)
        if eligibility.eligible:
            return rule, action, tuple(readiness)
        if str(eligibility.reason or "").startswith("action not ready:"):
            readiness.append(float(eligibility.next_ready_s))
    return None, None, tuple(readiness)



def opening_for_persistent_actor(
    *, opening_action_ids: tuple[str, ...], actions: tuple[ActionDefinition, ...],
    actor: Any,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Adapt only a proven-already-satisfied *leading* mode transition.

    This is an encounter-boundary compilation of a source-discovered opening,
    not a permissive runtime fallback. It has no class/spell fact knowledge.
    It never drops damage, healing, buff, summon or compound transitions;
    it also refuses unknown actions and wrong owners. The original action
    sequence remains authoritative for a fresh actor.
    """
    action_map = {a.id: a for a in actions}
    remaining = tuple(opening_action_ids)
    skipped: list[str] = []
    while remaining:
        action = action_map.get(remaining[0])
        if action is None:
            raise ValueError('BLOCKED_ILLEGAL_PREFIX: missing source action')
        if action.owner_actor_id != actor.id:
            raise ValueError('BLOCKED_ILLEGAL_PREFIX: wrong source action owner')
        if (not action.effects or
            any(not isinstance(effect, ModeChangeEffect) for effect in action.effects) or
            any(str(effect.target_mode_id) != str(actor.current_mode_id) for effect in action.effects)):
            break
        skipped.append(remaining[0])
        remaining = remaining[1:]
    return remaining, tuple(skipped)


def execute_priority_policy(
    *, policy: PolicyDefinition, actions: tuple[ActionDefinition, ...], runtime: CombatRuntime,
    max_actions: int = 256, opening_action_ids: tuple[str, ...] = (),
    resume_selected_actions: tuple[Mapping[str, Any], ...] = (),
    stop_after_opening_actions: int | None = None,
    on_opening_action=None,
    skip_satisfied_mode_opening: bool = False,
) -> PolicyExecutionResult:
    """Execute canonical Policy IR until target death or fail-closed stop."""
    action_map = {action.id: action for action in actions}
    selected: list[dict[str, Any]] = [dict(x) for x in resume_selected_actions]
    stop_reason: str | None = None
    # An opening prefix is a strict sequence of *executed actions*, not APL
    # priority. The ordinary source policy takes over only after the prefix.
    # No action-specific gameplay fact or simulated effect lives here.
    opening = tuple(opening_action_ids)
    if any(a not in action_map for a in opening):
        raise ValueError("BLOCKED_ILLEGAL_PREFIX: missing source action")
    if skip_satisfied_mode_opening and (resume_selected_actions or stop_after_opening_actions is not None):
        raise ValueError('state-conditional opening cannot resume or create partial prefix checkpoints')
    opening_index = sum(str(x.get('rule_id', '')).startswith('opening:') for x in selected)
    skipped_mode_entries: list[int] = []
    if opening_index > len(opening) or any(
        str(x.get('action_id')) != opening[i] for i, x in enumerate(selected[:opening_index])
    ):
        raise ValueError('BLOCKED_CHECKPOINT_PREFIX_MISMATCH')
    if stop_after_opening_actions is not None and not 0 < stop_after_opening_actions <= len(opening):
        raise ValueError('partial rollout needs a positive prefix action horizon')
    partial_stop = False
    for _ in range(max(0, int(max_actions) - len(selected))):
        if not runtime.target.alive:
            break
        if any(not runtime.actor.resource_positive(str(attack.health_resource_id))
               for attack in runtime.scheduled_incoming_attacks.values()):
            stop_reason = "actor_died"
            break
        if opening_index < len(opening):
            # A persistent sourced mode transition is already satisfied on
            # later pulls. Do not recast it, charge a GCD or reset resources.
            # This is *only* legal for a pure ModeChangeEffect, never a
            # general-purpose bypass for blocked/unsupported actions.
            if skip_satisfied_mode_opening:
                while opening_index < len(opening):
                    candidate = action_map[opening[opening_index]]
                    if (len(candidate.effects) != 1
                            or not isinstance(candidate.effects[0], ModeChangeEffect)
                            or candidate.effects[0].target_mode_id != runtime.actor.current_mode_id
                            or candidate.effects[0].target_mode_id not in runtime.actor.mode_definitions):
                        break
                    skipped_mode_entries.append(opening_index)
                    opening_index += 1
            if opening_index >= len(opening):
                rule, action, readiness = select_action(policy, actions=action_map, runtime=runtime)
            else:
                action = action_map[opening[opening_index]]
                # Ordered source openings are strict, but a moving 2D pack
                # may carry the player out of melee reach while a sourced
                # form change consumes its GCD. Wait for actual queued route
                # events and retarget only when another live mob is in range.
                if not runtime.select_reachable_target(action):
                    if runtime.begin_target_chase():
                        continue
                    now = float(runtime.actor.current_time_s)
                    next_event = runtime.queue.peek_time() if runtime.queue else None
                    if (next_event is not None and now - 1e-12 <= float(next_event)
                            <= now + 120.0):
                        runtime.advance_to(float(next_event))
                        continue
                    stop_reason = 'BLOCKED_PREFIX_SPATIAL_RANGE'
                    break
                eligibility = action_eligibility(action=action, actor=runtime.actor, target=runtime.target)
                if not eligibility.eligible:
                    ready = float(eligibility.next_ready_s)
                    now = float(runtime.actor.current_time_s)
                    if (str(eligibility.reason or '').startswith('action not ready:')
                            and now + 1e-12 < ready <= now + 120.0):
                        runtime.advance_to(ready)
                        continue
                    # Ordered actions can legitimately wait for source-defined
                    # resource gains (regen, incoming hit, proc, scheduled tick).
                    # Only the REAL event queue can advance the resource; no
                    # artificial Rage/Energy is injected into the actor.
                    if str(eligibility.reason or '').startswith('insufficient '):
                        next_event = runtime.queue.peek_time() if runtime.queue else None
                        if (next_event is not None and now - 1e-12 <= float(next_event)
                                <= now + 120.0):
                            runtime.advance_to(float(next_event))
                            continue
                    stop_reason = 'BLOCKED_PREFIX_ELIGIBILITY: ' + str(eligibility.reason)
                    break
                rule = PolicyRuleDefinition(id=f'opening:{opening_index}', action_id=action.id)
                readiness = ()
        else:
            rule, action, readiness = select_action(policy, actions=action_map, runtime=runtime)
        if action is None:
            future = [t for t in readiness if t > runtime.actor.current_time_s + 1e-12]
            queued = (
                [float(runtime.queue.peek_time())]
                if runtime.queue and runtime.queue.peek_time() > runtime.actor.current_time_s + 1e-12
                else []
            )
            # Chase before waiting on enemy swing events: a hostile's
            # recurring swing must not starve all movement indefinitely.
            if runtime.begin_target_chase():
                continue
            if future or queued:
                runtime.advance_to(min(future + queued))
                continue
            stop_reason = "no legal policy action"
            break
        start = float(runtime.actor.current_time_s)
        # A policy may stop to hard-cast, but the engine must never execute a
        # non-instant while walking. Preserve queued route steps and their
        # full travel cost; zero-cast-time actions do not pause movement.
        cast_duration_s = runtime.effective_source_cast_time(action)
        if cast_duration_s > 0.:
            runtime.pause_player_route_for_cast(cast_duration_s)
        try:
            runtime.schedule_action(action)
        except ActionNotEligibleError as exc:
            stop_reason = exc.eligibility.reason or "selected action became ineligible"
            break
        if opening_index < len(opening):
            opening_index += 1
        selected.append({
            "index": len(selected), "rule_id": rule.id, "action_id": action.id,
            "action_name": action.name, "start_time_s": start,
            "end_time_s": float(runtime.actor.current_time_s),
        })
        if opening_index <= len(opening) and str(rule.id).startswith('opening:'):
            if on_opening_action is not None:
                on_opening_action(tuple(opening[:opening_index]), runtime, tuple(selected))
            if stop_after_opening_actions is not None and opening_index >= stop_after_opening_actions:
                stop_reason = 'PARTIAL_OPENING_CHECKPOINT'
                partial_stop = True
                break
    else:
        stop_reason = f"max_actions:{int(max_actions)}"
    if partial_stop:
        # No run_until_idle here: future event queue, auras and cooldowns must
        # remain intact for an exact continuation from this checkpoint.
        return PolicyExecutionResult(policy_id=policy.id, selected_actions=tuple(selected),
                                     stopped_reason=stop_reason, timeline=runtime.result(),
                                     satisfied_mode_opening_ids=tuple(opening[i] for i in skipped_mode_entries))
    # Policy encounters must hand off actor-owned HoTs to recovery/next pull.
    # Single-action diagnostic timelines may intentionally drain skipped enemy
    # ticks for their full event trace; they retain the default runtime mode.
    runtime.run_until_idle(preserve_actor_periodics=True)
    return PolicyExecutionResult(
        policy_id=policy.id, selected_actions=tuple(selected),
        stopped_reason=stop_reason, timeline=runtime.result(),
        satisfied_mode_opening_ids=tuple(opening[i] for i in skipped_mode_entries),
    )

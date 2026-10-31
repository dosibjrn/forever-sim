from __future__ import annotations

"""Bounded, backend-neutral concurrent priority-policy driver (G35).

All combat mechanics remain in CombatRuntime; this only chooses next legal
Actions for each registered Actor and advances the single encounter clock.
"""

from dataclasses import dataclass
from typing import Mapping
from src.game.model import ActionDefinition, PolicyDefinition
from src.game.policy import select_action
from src.game.runtime import CombatRuntime


@dataclass(frozen=True)
class MultiActorPolicyResult:
    selected_actions: tuple[dict, ...]
    stopped_reason: str
    timeline: object

    def as_dict(self) -> dict:
        return {"selected_actions": [dict(x) for x in self.selected_actions],
                "stopped_reason": self.stopped_reason, "timeline": self.timeline.as_dict()}


def execute_multi_actor_priority_policies(
    *, runtime: CombatRuntime, policies: Mapping[str, PolicyDefinition],
    actions: tuple[ActionDefinition, ...], max_time_s: float = 60.0,
    max_iterations: int = 2048,
) -> MultiActorPolicyResult:
    """Run owner and pet policies concurrently without duplicating event logic."""
    action_map = {action.id: action for action in actions}
    if len(action_map) != len(actions):
        raise ValueError("duplicate multi-actor action id")
    for owner, policy in policies.items():
        if owner not in runtime.actors:
            raise ValueError(f"policy for unregistered actor: {owner}")
        for rule in policy.rules:
            action = action_map.get(rule.action_id)
            if action is None or action.owner_actor_id != owner:
                raise ValueError(f"policy action not owned by {owner}: {rule.action_id}")
    selected: list[dict] = []
    reason = "max_iterations"
    end = float(runtime.start_time_s) + float(max_time_s)
    if max_time_s <= 0 or max_iterations <= 0:
        raise ValueError("multi actor policy limits must be positive")
    for _ in range(max_iterations):
        now = float(runtime.actor.current_time_s)
        if not runtime.target.alive:
            reason = "target_defeated"
            break
        if (runtime.actor.resource_amount('health') is not None
                and not runtime.actor.resource_positive('health')):
            reason = 'actor_died'
            break
        if now >= end - 1e-10:
            reason = "max_time"
            break
        earliest_ready: list[float] = []
        any_enqueued = False
        for actor_id, policy in policies.items():
            if not runtime.actor_is_active(actor_id):
                continue
            with runtime._actor_context(actor_id):
                # Shared executor forbids actions while an actor is still
                # casting/channeling, even after the GCD expires. The policy
                # selector cannot see this runtime-owned state by itself.
                # Wait for the actual cast completion instead of enqueueing
                # an illegal action or dropping the companion's whole pull.
                busy_until = float(runtime.actor_cast_busy_until.get(actor_id, 0.0))
                if busy_until > now + 1e-9:
                    earliest_ready.append(busy_until)
                    continue
                rule, action, ready = select_action(policy, actions=action_map, runtime=runtime)
                if action is not None:
                    runtime.enqueue_action(action)
                    selected.append({"actor_id": actor_id, "rule_id": rule.id,
                                     "action_id": action.id, "start_time_s": now})
                    any_enqueued = True
                else:
                    earliest_ready.extend(t for t in ready if t > now + 1e-9)
                    # Generic Resource regeneration wake-up for policy actions
                    # currently blocked by Focus/Energy, without class dispatch.
                    for candidate_rule in policy.rules:
                        if candidate_rule.phase != "combat":
                            continue
                        candidate = action_map[candidate_rule.action_id]
                        need_ready = max(now, runtime.actor.gcd_ready_s,
                                         runtime.actor.cooldown_ready_s.get(candidate.id, now))
                        for cost in candidate.costs:
                            present = runtime.actor.resource_amount(cost.resource_id)
                            regen = float(runtime.actor.resource_regeneration_per_s.get(cost.resource_id, 0))
                            if present is None or not runtime.actor.resource_is_active(cost.resource_id):
                                need_ready = float("inf")
                                break
                            if present < cost.amount - 1e-10:
                                if regen <= 0:
                                    need_ready = float("inf")
                                    break
                                need_ready = max(need_ready, now + (float(cost.amount)-present)/regen)
                        if now + 1e-9 < need_ready < float("inf"):
                            earliest_ready.append(float(need_ready))
        if any_enqueued:
            runtime.advance_to(now)
            continue
        next_times = [t for t in earliest_ready if now + 1e-9 < t <= end]
        if runtime.queue:
            next_event = float(runtime.queue.peek_time())
            if next_event <= now + 1e-9:
                runtime.advance_to(now)
                continue
            if next_event <= end:
                next_times.append(next_event)
        if not next_times:
            reason = "no_future_action_or_event"
            break
        runtime.advance_to(min(next_times))
    else:
        reason = "max_iterations"
    return MultiActorPolicyResult(tuple(selected), reason, runtime.result())

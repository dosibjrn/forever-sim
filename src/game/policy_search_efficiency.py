from __future__ import annotations

"""Backend-neutral dominance pruning and evaluation caching for policy search.

G18 keeps search semantics exact while avoiding repeated expensive combat
simulations.  Dominance is intentionally conservative: a later combat rule is
removed only when an earlier zero-cooldown rule is guaranteed to match and be
resource-eligible whenever the later rule could execute in the current Game IR
slice.  The resulting executable policy signature ignores ids/provenance and
normalizes action-cost thresholds to numeric values, so structurally different
search candidates with identical runtime behaviour share one cache entry.
"""

from dataclasses import dataclass, field, replace
import json
from typing import Any, Callable, Mapping

from src.game.model import ActionDefinition, PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.game.policy_search import PolicyEvaluator


def _condition_value(condition: PolicyCondition, *, action: ActionDefinition) -> Any:
    if condition.kind == "resource_threshold" and condition.threshold_source == "action_cost":
        resource_id = str(condition.resource_id or "")
        costs = [float(x.amount) for x in action.costs if str(x.resource_id) == resource_id]
        if not costs:
            raise ValueError(f"action {action.id!r} has no cost for resource {resource_id!r}")
        return float(sum(costs))
    return condition.value


def _condition_key(condition: PolicyCondition) -> tuple[str, str, str, str, str]:
    return (
        str(condition.kind or ""),
        str(condition.scope or ""),
        str(condition.field or ""),
        str(condition.aura_id or ""),
        str(condition.resource_id or ""),
    )


def _normalized_condition(condition: PolicyCondition, *, action: ActionDefinition) -> dict[str, Any]:
    out = condition.as_dict()
    out.pop("threshold_source", None)
    value = _condition_value(condition, action=action)
    if value is not None:
        out["value"] = value
    return out


def _condition_implies(stronger: PolicyCondition, weaker: PolicyCondition, *, stronger_action: ActionDefinition, weaker_action: ActionDefinition) -> bool:
    """Return True when ``stronger`` being true guarantees ``weaker`` is true."""
    if _condition_key(stronger) != _condition_key(weaker):
        return False
    strong_op = str(stronger.operator or "eq")
    weak_op = str(weaker.operator or "eq")
    strong_value = _condition_value(stronger, action=stronger_action)
    weak_value = _condition_value(weaker, action=weaker_action)
    if strong_op == weak_op == "eq":
        return strong_value == weak_value
    if strong_op == weak_op == "gte":
        return float(strong_value) >= float(weak_value)
    if strong_op == weak_op == "gt":
        return float(strong_value) >= float(weak_value)
    if strong_op == weak_op == "lte":
        return float(strong_value) <= float(weak_value)
    if strong_op == weak_op == "lt":
        return float(strong_value) <= float(weak_value)
    return False


def _later_conditions_imply_earlier(
    earlier: PolicyRuleDefinition,
    later: PolicyRuleDefinition,
    *,
    earlier_action: ActionDefinition,
    later_action: ActionDefinition,
) -> bool:
    for earlier_condition in earlier.conditions:
        if not any(
            _condition_implies(
                later_condition,
                earlier_condition,
                stronger_action=later_action,
                weaker_action=earlier_action,
            )
            for later_condition in later.conditions
        ):
            return False
    return True


def _resource_floor(rule: PolicyRuleDefinition, *, action: ActionDefinition, resource_id: str) -> float:
    # If the later action is eligible, its declared costs are affordable even
    # when the policy has no explicit resource predicate.
    floor = sum(float(x.amount) for x in action.costs if str(x.resource_id) == resource_id)
    for condition in rule.conditions:
        if condition.kind != "resource_threshold" or str(condition.resource_id or "") != resource_id:
            continue
        if str(condition.operator or "gte") not in {"gte", "gt"}:
            continue
        value = _condition_value(condition, action=action)
        if value is not None:
            floor = max(float(floor), float(value))
    return float(floor)


def _earlier_action_eligible_when_later_is(
    earlier: PolicyRuleDefinition,
    later: PolicyRuleDefinition,
    *,
    earlier_action: ActionDefinition,
    later_action: ActionDefinition,
) -> bool:
    # Independent cooldowns break the guarantee. Shared GCD does not: if the
    # later action is GCD-ready, an otherwise-ready zero-cooldown earlier action
    # is also GCD-ready.
    if float(earlier_action.cooldown_s) > 1e-12:
        return False
    if str(earlier_action.owner_actor_id) != str(later_action.owner_actor_id):
        return False
    for cost in earlier_action.costs:
        resource_id = str(cost.resource_id)
        if _resource_floor(later, action=later_action, resource_id=resource_id) + 1e-12 < float(cost.amount):
            return False
    return True


def rule_dominates_later(
    earlier: PolicyRuleDefinition,
    later: PolicyRuleDefinition,
    *,
    actions: Mapping[str, ActionDefinition],
) -> bool:
    if str(earlier.phase) != "combat" or str(later.phase) != "combat":
        return False
    earlier_action = actions.get(str(earlier.action_id))
    later_action = actions.get(str(later.action_id))
    if earlier_action is None or later_action is None:
        return False
    return (
        _later_conditions_imply_earlier(
            earlier,
            later,
            earlier_action=earlier_action,
            later_action=later_action,
        )
        and _earlier_action_eligible_when_later_is(
            earlier,
            later,
            earlier_action=earlier_action,
            later_action=later_action,
        )
    )


def prune_dominated_rules(
    policy: PolicyDefinition,
    *,
    actions: tuple[ActionDefinition, ...],
) -> tuple[PolicyDefinition, tuple[Mapping[str, Any], ...]]:
    action_map = {str(action.id): action for action in actions}
    kept: list[PolicyRuleDefinition] = []
    pruned: list[dict[str, Any]] = []
    for rule in policy.rules:
        if str(rule.phase) != "combat":
            kept.append(rule)
            continue
        dominating = next((
            prior for prior in kept
            if str(prior.phase) == "combat" and rule_dominates_later(prior, rule, actions=action_map)
        ), None)
        if dominating is None:
            kept.append(rule)
            continue
        pruned.append({
            "rule_id": str(rule.id),
            "action_id": str(rule.action_id),
            "dominated_by_rule_id": str(dominating.id),
            "dominated_by_action_id": str(dominating.action_id),
            "reason": "earlier_rule_guaranteed_match_and_eligibility",
        })
    if not pruned:
        return policy, ()
    return replace(policy, rules=tuple(kept)), tuple(pruned)


def executable_policy_signature(policy: PolicyDefinition, *, actions: tuple[ActionDefinition, ...]) -> str:
    action_map = {str(action.id): action for action in actions}
    effective, _ = prune_dominated_rules(policy, actions=actions)
    rows: list[dict[str, Any]] = []
    for rule in effective.rules:
        action = action_map.get(str(rule.action_id))
        if action is None:
            raise KeyError(f"policy rule {rule.id!r} references missing Action {rule.action_id!r}")
        rows.append({
            "phase": str(rule.phase),
            "action_id": str(rule.action_id),
            "conditions": [
                _normalized_condition(condition, action=action)
                for condition in rule.conditions
            ],
        })
    payload = {
        "rules": rows,
        "maintenance": [dict(x) for x in effective.maintenance],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass
class PolicyEvaluationCache:
    actions: tuple[ActionDefinition, ...]
    expensive_evaluate: PolicyEvaluator
    _cache: dict[str, tuple[float | None, Mapping[str, Any]]] = field(default_factory=dict)
    requests: int = 0
    expensive_evaluations: int = 0
    cache_hits: int = 0
    dominance_pruned_requests: int = 0
    dominance_pruned_rule_count: int = 0

    def evaluate(self, policy: PolicyDefinition) -> tuple[float | None, Mapping[str, Any]]:
        self.requests += 1
        effective, pruned = prune_dominated_rules(policy, actions=self.actions)
        if pruned:
            self.dominance_pruned_requests += 1
            self.dominance_pruned_rule_count += len(pruned)
        key = executable_policy_signature(effective, actions=self.actions)
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            score, detail = cached
            return score, {
                **dict(detail),
                "policy_cache_hit": True,
                "dominance_pruned": bool(pruned),
                "dominance_pruned_rules": [dict(x) for x in pruned],
            }
        self.expensive_evaluations += 1
        score, detail = self.expensive_evaluate(effective)
        stored = (score, dict(detail or {}))
        self._cache[key] = stored
        return score, {
            **dict(stored[1]),
            "policy_cache_hit": False,
            "dominance_pruned": bool(pruned),
            "dominance_pruned_rules": [dict(x) for x in pruned],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": int(self.requests),
            "expensive_evaluations": int(self.expensive_evaluations),
            "cache_hits": int(self.cache_hits),
            "cache_entries": len(self._cache),
            "dominance_pruned_requests": int(self.dominance_pruned_requests),
            "dominance_pruned_rule_count": int(self.dominance_pruned_rule_count),
            "expensive_evaluations_avoided": int(self.requests - self.expensive_evaluations),
        }

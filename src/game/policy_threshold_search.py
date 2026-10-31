from __future__ import annotations

"""Bounded numeric threshold search over canonical priority-policy conditions.

G17 extends G16 structural policy search without class/spell branches. It mutates
only generic executable predicates whose threshold semantics can be derived from
Game IR: resource thresholds and periodic-action target-health cutoffs.
"""

from dataclasses import dataclass, replace
from itertools import product
from typing import Any, Callable, Mapping

from src.game.model import ActionDefinition, PeriodicEffect, PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.game.policy_search import PolicyEvaluator, PolicySearchResult


@dataclass(frozen=True)
class ThresholdMutation:
    rule_id: str
    key: str
    values: tuple[float, ...]
    condition_index: int | None = None
    append_condition: PolicyCondition | None = None
    baseline_value: float = 0.0


def _action_cost(action: ActionDefinition, resource_id: str) -> float | None:
    values = [float(x.amount) for x in action.costs if str(x.resource_id) == str(resource_id)]
    return None if not values else float(sum(values))


def _mutations_for_policy(policy: PolicyDefinition, actions: Mapping[str, ActionDefinition]) -> tuple[ThresholdMutation, ...]:
    out: list[ThresholdMutation] = []
    for rule in policy.rules:
        if str(rule.phase) != "combat":
            continue
        action = actions.get(str(rule.action_id))
        if action is None:
            continue
        for i, condition in enumerate(rule.conditions):
            if condition.kind == "resource_threshold" and condition.threshold_source == "action_cost" and condition.resource_id:
                cost = _action_cost(action, str(condition.resource_id))
                if cost is not None and cost > 0:
                    out.append(ThresholdMutation(
                        rule_id=str(rule.id),
                        key=f"{rule.id}.resource.{condition.resource_id}",
                        values=tuple(dict.fromkeys((float(cost), float(cost) * 2.0, float(cost) * 4.0))),
                        condition_index=i, baseline_value=float(cost),
                    ))
            elif condition.kind == "resource_threshold" and condition.threshold_source is None and condition.resource_id and condition.search_values:
                values = tuple(dict.fromkeys(float(v) for v in condition.search_values))
                if values:
                    baseline = float(condition.value if condition.value is not None else values[0])
                    out.append(ThresholdMutation(
                        rule_id=str(rule.id),
                        key=f"{rule.id}.resource.{condition.resource_id}",
                        values=values, condition_index=i, baseline_value=baseline,
                    ))
        # Generic periodic-maintenance rule: let search decide when remaining
        # target health is too low to justify another application/refresh.
        if any(isinstance(effect, PeriodicEffect) for effect in action.effects) and any(
            c.kind in {"aura_missing", "aura_present"} for c in rule.conditions
        ):
            out.append(ThresholdMutation(
                rule_id=str(rule.id),
                key=f"{rule.id}.target.health_pct",
                values=(0.0, 0.10, 0.25, 0.50, 0.75, 0.90),
                append_condition=PolicyCondition(kind="target_state", field="health_pct", operator="gte", value=0.0),
                baseline_value=0.0,
            ))
    return tuple(out)


def _rebuild_structural_policy(seed_policy: PolicyDefinition, row: Mapping[str, Any]) -> PolicyDefinition:
    by_id = {str(rule.id): rule for rule in seed_policy.rules}
    combat = tuple(by_id[str(rule_id)] for rule_id in row.get("rule_ids", ()))
    fixed = tuple(rule for rule in seed_policy.rules if str(rule.phase) != "combat")
    return replace(seed_policy, rules=combat + fixed)


def _apply_thresholds(policy: PolicyDefinition, mutations: tuple[ThresholdMutation, ...], values: tuple[float, ...]) -> PolicyDefinition:
    selected = dict(zip((m.key for m in mutations), values))
    rules: list[PolicyRuleDefinition] = []
    for rule in policy.rules:
        conditions = list(rule.conditions)
        rule_mutations = [(m, selected[m.key]) for m in mutations if m.rule_id == str(rule.id)]
        for mutation, value in rule_mutations:
            if mutation.condition_index is not None:
                original = conditions[int(mutation.condition_index)]
                conditions[int(mutation.condition_index)] = replace(
                    original, value=float(value), threshold_source=None,
                )
            elif mutation.append_condition is not None:
                conditions.append(replace(mutation.append_condition, value=float(value)))
        rules.append(replace(rule, conditions=tuple(conditions)))
    return replace(policy, rules=tuple(rules))


def _threshold_identity(structural_id: str, mutations: tuple[ThresholdMutation, ...], values: tuple[float, ...]) -> str:
    parts = [f"{m.key}={float(v):g}" for m, v in zip(mutations, values)]
    return structural_id + ("|thresholds:" + ";".join(parts) if parts else "|thresholds:none")


def search_policy_thresholds(
    seed_policy: PolicyDefinition,
    *,
    structural_search: PolicySearchResult,
    actions: tuple[ActionDefinition, ...],
    evaluate: PolicyEvaluator,
    max_candidates: int = 128,
) -> PolicySearchResult:
    """Search numeric executable condition values over G16 structural candidates."""
    max_candidates = max(1, int(max_candidates))
    action_map = {str(action.id): action for action in actions}
    rows: list[dict[str, Any]] = []
    policies: dict[str, PolicyDefinition] = {}

    for structural_row in structural_search.candidates:
        structural_policy = _rebuild_structural_policy(seed_policy, structural_row)
        mutations = _mutations_for_policy(structural_policy, action_map)
        value_sets = [m.values for m in mutations] or [()]
        combos = product(*value_sets) if mutations else [()]
        for values in combos:
            if len(rows) >= max_candidates:
                break
            values = tuple(float(x) for x in values)
            policy = _apply_thresholds(structural_policy, mutations, values)
            structural_id = str(structural_row.get("candidate_id") or "priority:unknown")
            candidate_id = _threshold_identity(structural_id, mutations, values)
            thresholds = {m.key: float(v) for m, v in zip(mutations, values)}
            policy = replace(
                policy,
                id=f"{seed_policy.id}::threshold-search::{candidate_id}",
                label="Threshold-searched priority: " + " > ".join(str(r.id) for r in policy.rules if str(r.phase) == "combat"),
                provenance={
                    **dict(seed_policy.provenance),
                    "authority": "generic_policy_threshold_search",
                    "source_policy_authority": seed_policy.provenance.get("authority"),
                    "structural_candidate_id": structural_id,
                    "search_performed": True,
                    "threshold_search_performed": True,
                    "search_dimensions": ["action_inclusion_exclusion", "priority_order", "numeric_condition_thresholds"],
                    "candidate_id": candidate_id,
                    "threshold_values": thresholds,
                },
            )
            score, detail = evaluate(policy)
            row = {
                "candidate_id": candidate_id,
                "policy_id": policy.id,
                "structural_candidate_id": structural_id,
                "rule_ids": [str(rule.id) for rule in policy.rules if str(rule.phase) == "combat"],
                "action_ids": [str(rule.action_id) for rule in policy.rules if str(rule.phase) == "combat"],
                "threshold_values": thresholds,
                "is_seed": bool(structural_row.get("is_seed")) and all(abs(v - m.baseline_value) < 1e-12 for m, v in zip(mutations, values)),
                "threshold_distance": sum(abs(v - m.baseline_value) / (abs(m.baseline_value) + 1.0) for m, v in zip(mutations, values)),
                "valid": score is not None,
                "seconds_per_mob": None if score is None else float(score),
                **dict(detail or {}),
            }
            rows.append(row)
            policies[candidate_id] = policy
        if len(rows) >= max_candidates:
            break

    valid_rows = [row for row in rows if row["valid"]]
    selected_policy = None
    if valid_rows:
        winner = min(valid_rows, key=lambda row: (float(row["seconds_per_mob"]), len(row["rule_ids"]), float(row.get("threshold_distance") or 0.0), str(row["candidate_id"])))
        selected_policy = policies[str(winner["candidate_id"])]
        seed_row = next((row for row in rows if row.get("is_seed")), None)
        structural_selected = structural_search.selected_candidate
        selected_policy = replace(selected_policy, provenance={
            **dict(selected_policy.provenance),
            "candidate_count": len(rows),
            "valid_candidate_count": len(valid_rows),
            "selected_seconds_per_mob": winner["seconds_per_mob"],
            "seed_seconds_per_mob": None if seed_row is None else seed_row.get("seconds_per_mob"),
            "structural_selected_seconds_per_mob": None if structural_selected is None else structural_selected.get("seconds_per_mob"),
            "improvement_vs_seed_seconds_per_mob": (None if seed_row is None or seed_row.get("seconds_per_mob") is None else float(seed_row["seconds_per_mob"]) - float(winner["seconds_per_mob"])),
            "improvement_vs_structural_seconds_per_mob": (None if structural_selected is None or structural_selected.get("seconds_per_mob") is None else float(structural_selected["seconds_per_mob"]) - float(winner["seconds_per_mob"])),
        })

    return PolicySearchResult(
        seed_policy_id=seed_policy.id,
        selected_policy=selected_policy,
        candidates=tuple(rows),
        bounded_max_candidates=max_candidates,
        search_dimensions=("action_inclusion_exclusion", "priority_order", "numeric_condition_thresholds"),
    )

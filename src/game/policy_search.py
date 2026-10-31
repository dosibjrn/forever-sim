from __future__ import annotations

"""Bounded backend-neutral search over canonical priority-policy structure.

G16 owns only discrete action inclusion/exclusion and priority ordering. Numeric
condition mutation belongs to G17. Candidate execution/evaluation is supplied by
the caller so this module never knows classes, spells, or combat objective details.
"""

from dataclasses import dataclass, replace
from itertools import combinations, permutations
from typing import Any, Callable, Mapping

from src.game.model import PolicyDefinition, PolicyRuleDefinition


PolicyEvaluator = Callable[[PolicyDefinition], tuple[float | None, Mapping[str, Any]]]


@dataclass(frozen=True)
class PolicySearchResult:
    seed_policy_id: str
    selected_policy: PolicyDefinition | None
    candidates: tuple[Mapping[str, Any], ...]
    bounded_max_candidates: int
    search_dimensions: tuple[str, ...] = ("action_inclusion_exclusion", "priority_order")

    @property
    def search_performed(self) -> bool:
        return bool(self.candidates)

    @property
    def valid_candidates(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(x for x in self.candidates if bool(x.get("valid")))

    @property
    def selected_candidate(self) -> Mapping[str, Any] | None:
        if self.selected_policy is None:
            return None
        selected_id = str(self.selected_policy.provenance.get("candidate_id") or "")
        return next((x for x in self.candidates if str(x.get("candidate_id")) == selected_id), None)

    @property
    def seed_candidate(self) -> Mapping[str, Any] | None:
        return next((x for x in self.candidates if bool(x.get("is_seed"))), None)

    def as_dict(self) -> dict[str, Any]:
        selected = self.selected_candidate
        seed = self.seed_candidate
        selected_seconds = None if selected is None else selected.get("seconds_per_mob")
        seed_seconds = None if seed is None else seed.get("seconds_per_mob")
        improvement = None
        if selected_seconds is not None and seed_seconds is not None:
            improvement = float(seed_seconds) - float(selected_seconds)
        return {
            "seed_policy_id": self.seed_policy_id,
            "search_performed": self.search_performed,
            "search_dimensions": list(self.search_dimensions),
            "bounded_max_candidates": int(self.bounded_max_candidates),
            "candidate_count": len(self.candidates),
            "valid_candidate_count": len(self.valid_candidates),
            "selected_policy_id": None if self.selected_policy is None else self.selected_policy.id,
            "selected_candidate_id": None if selected is None else selected.get("candidate_id"),
            "selected_seconds_per_mob": selected_seconds,
            "seed_seconds_per_mob": seed_seconds,
            "improvement_vs_seed_seconds_per_mob": improvement,
            "candidates": [dict(x) for x in self.candidates],
        }


def _candidate_specs(seed_policy: PolicyDefinition, *, max_candidates: int):
    combat_rules = tuple(rule for rule in seed_policy.rules if str(rule.phase) == "combat")
    fixed_rules = tuple(rule for rule in seed_policy.rules if str(rule.phase) != "combat")
    if not combat_rules:
        return
    emitted = 0
    for size in range(1, len(combat_rules) + 1):
        for subset in combinations(combat_rules, size):
            for ordered in permutations(subset):
                if emitted >= int(max_candidates):
                    return
                emitted += 1
                yield tuple(ordered), fixed_rules


def _candidate_id(rules: tuple[PolicyRuleDefinition, ...]) -> str:
    return "priority:" + ">".join(str(rule.id) for rule in rules)


def search_priority_policy(
    seed_policy: PolicyDefinition,
    *,
    evaluate: PolicyEvaluator,
    max_candidates: int = 64,
) -> PolicySearchResult:
    """Search non-empty combat-rule subsets and priority permutations.

    Conditions are copied byte-for-byte from the seed Policy IR: this function
    deliberately does not mutate thresholds or other numeric condition values.
    Invalid/non-killing candidates remain visible and cannot win.
    """
    max_candidates = max(1, int(max_candidates))
    rows: list[dict[str, Any]] = []
    policies: dict[str, PolicyDefinition] = {}
    seed_rule_ids = tuple(str(rule.id) for rule in seed_policy.rules if str(rule.phase) == "combat")

    for ordered_combat, fixed_rules in _candidate_specs(seed_policy, max_candidates=max_candidates):
        candidate_id = _candidate_id(ordered_combat)
        rules = tuple(ordered_combat) + tuple(fixed_rules)
        is_seed = tuple(str(rule.id) for rule in ordered_combat) == seed_rule_ids
        policy = replace(
            seed_policy,
            id=f"{seed_policy.id}::search::{candidate_id}",
            label="Searched priority: " + " > ".join(str(rule.id) for rule in ordered_combat),
            rules=rules,
            provenance={
                **dict(seed_policy.provenance),
                "authority": "generic_policy_search",
                "source_policy_authority": seed_policy.provenance.get("authority"),
                "seed_policy_id": seed_policy.id,
                "search_performed": True,
                "search_dimensions": ["action_inclusion_exclusion", "priority_order"],
                "candidate_id": candidate_id,
            },
        )
        score, detail = evaluate(policy)
        valid = score is not None
        row = {
            "candidate_id": candidate_id,
            "policy_id": policy.id,
            "rule_ids": [str(rule.id) for rule in ordered_combat],
            "action_ids": [str(rule.action_id) for rule in ordered_combat],
            "is_seed": bool(is_seed),
            "valid": bool(valid),
            "seconds_per_mob": None if score is None else float(score),
            **dict(detail or {}),
        }
        rows.append(row)
        policies[candidate_id] = policy

    valid_rows = [row for row in rows if row["valid"]]
    selected_policy = None
    if valid_rows:
        winner = min(
            valid_rows,
            key=lambda row: (
                float(row["seconds_per_mob"]),
                len(row["rule_ids"]),
                str(row["candidate_id"]),
            ),
        )
        selected_policy = policies[str(winner["candidate_id"])]
        seed_row = next((row for row in rows if row["is_seed"]), None)
        selected_policy = replace(
            selected_policy,
            provenance={
                **dict(selected_policy.provenance),
                "candidate_count": len(rows),
                "valid_candidate_count": len(valid_rows),
                "selected_seconds_per_mob": winner["seconds_per_mob"],
                "seed_seconds_per_mob": None if seed_row is None else seed_row["seconds_per_mob"],
                "improvement_vs_seed_seconds_per_mob": (
                    None if seed_row is None or seed_row["seconds_per_mob"] is None
                    else float(seed_row["seconds_per_mob"]) - float(winner["seconds_per_mob"])
                ),
            },
        )

    return PolicySearchResult(
        seed_policy_id=seed_policy.id,
        selected_policy=selected_policy,
        candidates=tuple(rows),
        bounded_max_candidates=max_candidates,
    )

"""One-request native Warlock level-range performance search.

Forever owns the search frontier and objective aggregation, not Warcraft rules.
The supplied evaluator must call the pinned Rust source/native execution path and
return its *observed* receipt for each proposal.  Missing full-resource recovery
or unproved cross-level ancestry is never upgraded to a comparable score.

Sparse checkpoints are samples of an objective, NOT a complete leveling route.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def sampled_levels(start_level: int, end_level: int, level_stride: int) -> tuple[int, ...]:
    if (type(start_level) is not int or type(end_level) is not int
            or type(level_stride) is not int or not 10 <= start_level <= end_level <= 60
            or level_stride < 1):
        raise ValueError("invalid 10..60 level range/stride")
    levels = list(range(start_level, end_level + 1, level_stride))
    if levels[-1] != end_level:
        levels.append(end_level)
    return tuple(levels)


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value
    )


def _receipt_error(
    row: Mapping[str, Any], *, level: int, parent: Mapping[str, Any] | None,
    mob_count: int, rng_mode: str, iterations: int,
) -> str | None:
    """Validate Forever transport/objective completeness, never Rust legality."""
    if row.get("native_prepared") is not True or row.get("native_world_ack") is not True:
        return "native prepare/world ACK missing"
    if (row.get("level") != level or row.get("mob_count") != mob_count
            or row.get("targets_killed") != mob_count
            or row.get("rng_mode") != rng_mode or row.get("iterations") != iterations):
        return "native scenario/target/seed contract mismatch"
    if not (_sha(row.get("source_request_sha256"))
            and _sha(row.get("engine_binary_sha256"))):
        return "native source/binary identity missing"
    if (row.get("native_full_recovery_paid") is not True
            or row.get("recover_to_full") is not True):
        return "native terminal full recovery not paid"
    for name in ("terminal_hp", "terminal_max_hp", "terminal_mana", "terminal_max_mana"):
        value = row.get(name)
        if type(value) not in (int, float) or not math.isfinite(value):
            return "native terminal resources missing"
    if row["terminal_max_hp"] <= 0 or row["terminal_max_mana"] <= 0:
        return "native resource maxima missing"
    if (abs(row["terminal_hp"] - row["terminal_max_hp"]) > 1e-6
            or abs(row["terminal_mana"] - row["terminal_max_mana"]) > 1e-6):
        return "native terminal HP and mana not both full"
    elapsed = row.get("elapsed_seconds")
    recovery = row.get("terminal_recovery_seconds")
    if (not _positive_number(elapsed)
            or type(recovery) not in (int, float) or not math.isfinite(recovery)
            or recovery < 0 or recovery > elapsed):
        return "native charged elapsed/recovery clock missing"
    if parent is not None:
        if row.get("engine_binary_sha256") != parent["engine_binary_sha256"]:
            return "cross-engine path is not comparable"
        if (row.get("native_parent_source_sha256") != parent["source_request_sha256"]
                or row.get("native_continuity_ack") is not True
                or row.get("native_continuity_from_level") != parent["level"]):
            return "native continuing talent/actor edge unproved"
        if (level > parent["level"] + 1
                and row.get("native_intermediate_levels_verified") is not True):
            return "sparse-level ancestry unproved"
    return None


def optimize(
    start_level: int, end_level: int, level_stride: int, mob_count: int,
    budget: int, *,
    evaluate: Callable[..., Sequence[Mapping[str, Any]]],
    beam_width: int = 3, rng_mode: str = "balanced", iterations: int = 1,
    recover_to_full: bool = True,
) -> dict[str, Any]:
    """Sample/rank a source-native *continuing* path in one high-level call.

    evaluate(level=, parent=, mob_count=, budget=, rng_mode=, iterations=,
             recover_to_full=) must return at most budget distinct native
    attempts. parent is the exact previous native receipt, or None at start.
    Every returned attempt, including refusals, consumes the search budget.
    The evaluator owns native get_options/proposals, preparation, execution,
    native terminal restoration and exact-compatible paid receipt reuse.

    No Python talent, item, spell or resource mechanics are implemented here.
    """
    levels = sampled_levels(start_level, end_level, level_stride)
    if (type(mob_count) is not int or mob_count < 1
            or type(budget) is not int or budget < 1
            or type(beam_width) is not int or beam_width < 2
            or type(iterations) is not int or iterations < 1
            or not isinstance(rng_mode, str) or not rng_mode
            or recover_to_full is not True):
        raise ValueError("mob_count/budget/beam_width/RNG/terminal recovery invalid")

    # State: cumulative observed time, latest native source, sampled path.
    frontier: list[tuple[float, Mapping[str, Any] | None, list[dict[str, Any]]]] = [
        (0.0, None, [])
    ]
    examined = 0
    rejected: list[dict[str, Any]] = []
    covered: list[int] = []
    competing: dict[str, int] = {}
    last_frontier: list[tuple[float, Mapping[str, Any] | None, list[dict[str, Any]]]] = []
    native_attempts_by_level: dict[str, int] = {}
    for level_index, level in enumerate(levels):
        # Budget the entire request, not just the first sample. A scorer may
        # spend up to its allotted candidate count but cannot starve every
        # later requested level by using the whole remaining global budget.
        levels_left = len(levels) - level_index
        level_budget = max(1, (budget - examined) // levels_left)
        level_attempts = 0
        next_paths: dict[tuple[str, str], tuple[float, Mapping[str, Any], list[dict[str, Any]]]] = {}
        at_level = 0
        for parent_index, (base_cost, parent, history) in enumerate(frontier):
            remaining = min(budget - examined, level_budget - level_attempts)
            if remaining <= 0:
                break
            parent_count_left = len(frontier) - parent_index
            parent_budget = max(1, remaining // parent_count_left)
            receipts = evaluate(
                level=level, parent=parent, mob_count=mob_count, budget=parent_budget,
                rng_mode=rng_mode, iterations=iterations, recover_to_full=True,
            )
            if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
                raise TypeError("native evaluator must return a sequence of receipts")
            if len(receipts) > parent_budget:
                raise ValueError("native evaluator exceeded candidate budget")
            for row in receipts:
                examined += 1
                level_attempts += 1
                at_level += 1
                if not isinstance(row, Mapping):
                    rejected.append({"level": level, "reason": "non-mapping native receipt"})
                    continue
                error = _receipt_error(
                    row, level=level, parent=parent, mob_count=mob_count,
                    rng_mode=rng_mode, iterations=iterations,
                )
                if error:
                    rejected.append({
                        "level": level, "source_request_sha256": row.get("source_request_sha256"),
                        "candidate_id": row.get("candidate_id"),
                        "reason": error, "native_status": row.get("status"),
                        "native_refusal": row.get("native_refusal"),
                    })
                    continue
                cost = base_cost + float(row["elapsed_seconds"])
                step = {
                    "level": level, "source_request_sha256": row["source_request_sha256"],
                    "engine_binary_sha256": row["engine_binary_sha256"],
                    "native_elapsed_seconds": float(row["elapsed_seconds"]),
                    "terminal_recovery_seconds": float(row["terminal_recovery_seconds"]),
                    "sampled_cumulative_seconds": cost,
                    "native_parent_source_sha256": row.get("native_parent_source_sha256"),
                    "talents": row.get("talents"), "pet": row.get("pet"),
                    "gear": row.get("gear"), "apl": row.get("apl"),
                    "receipt": dict(row),
                }
                key = (row["engine_binary_sha256"], row["source_request_sha256"])
                old = next_paths.get(key)
                if old is None or cost < old[0]:
                    next_paths[key] = (cost, row, [*history, step])
        native_attempts_by_level[str(level)] = level_attempts
        competing[str(level)] = len(next_paths)
        if not next_paths:
            break
        covered.append(level)
        last_frontier = sorted(
            next_paths.values(), key=lambda p: (p[0], p[1]["source_request_sha256"])
        )
        frontier = last_frontier[:beam_width]
        # A single remaining-budget shortfall cannot be disguised as a result
        # for the unvisited samples. Preserve the completed prefix instead.
        if examined >= budget:
            break

    ranked = [
        {"sampled_cumulative_seconds": cost, "steps": steps,
         "source_request_sha256": source["source_request_sha256"]}
        for cost, source, steps in last_frontier
    ]
    complete = covered == list(levels)
    return {
        "status": ("SAMPLED_NATIVE_PATH_RANKED" if complete and len(ranked) >= 2
                   else "SAMPLED_NATIVE_PREFIX_ONLY" if covered
                   else "NO_COMPARABLE_NATIVE_PATH"),
        "sampled_levels_requested": list(levels),
        "sampled_levels_completed": covered,
        "mob_count": mob_count, "rng_mode": rng_mode, "iterations": iterations,
        "recover_to_full": True, "candidate_budget": budget,
        "native_candidates_examined": examined, "beam_width": beam_width,
        "native_attempts_by_level": native_attempts_by_level,
        "competing_qualified_paths_by_level": competing,
        "ranked_alternatives": ranked,
        "rejected_native_attempts": rejected,
        "full_10_60_continuous_leveling_route_proven": False,
        "scope": "sampled native combat+movement+charged terminal recovery only; not XP/travel/training/acquisition",
    }

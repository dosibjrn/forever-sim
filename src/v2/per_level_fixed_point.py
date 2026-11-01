from __future__ import annotations

"""Bounded per-level coordinate optimization.

The leveling problem has three mutually-dependent decisions: gear, gameplay
(talents/rotation/profile), and marginal stat values.  This helper deliberately
owns only the *coordination* loop; class backends remain authorities for scoring,
gear legality, and stat derivatives.
"""

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class FixedPointStep:
    iteration: int
    score: Mapping[str, Any]
    weights: Mapping[str, float]
    gear_signature: tuple[Any, ...]


@dataclass(frozen=True)
class FixedPointResult:
    score: Mapping[str, Any]
    weights: Mapping[str, float]
    iterations: int
    converged: bool
    trace: tuple[FixedPointStep, ...]


def positive_stat_values(stat_payload: Mapping[str, Any] | None) -> dict[str, float]:
    """Convert normalized stat-weight payloads to positive gear-selector values."""
    payload = dict(stat_payload or {})
    grads = payload.get("objective_gradient")
    if isinstance(grads, Mapping):
        out = {}
        for k, v in grads.items():
            try:
                out[str(k)] = max(0.0, -float(v))
            except (TypeError, ValueError):
                continue
        if any(v > 0 for v in out.values()):
            return out

    # Normalized public payloads may instead expose seconds saved directly.
    stats = payload.get("stats") or payload.get("weights") or {}
    out = {}
    if isinstance(stats, Mapping):
        for k, row in stats.items():
            try:
                if isinstance(row, Mapping):
                    v = row.get("seconds_saved_per_100_per_point", row.get("value", 0.0))
                else:
                    v = row
                out[str(k)] = max(0.0, float(v or 0.0))
            except (TypeError, ValueError):
                continue
    return out


def optimize_level_fixed_point(*, initial_gear: Any,
                               score_with_gear: Callable[[Any], Mapping[str, Any]],
                               stat_weights: Callable[[Mapping[str, Any]], Mapping[str, Any]],
                               select_gear: Callable[[Any, Mapping[str, float]], Any],
                               gear_signature: Callable[[Any], tuple[Any, ...]],
                               max_iters: int = 4) -> FixedPointResult:
    """Coordinate-descent style bounded fixed point for one level/build.

    Order intentionally matches the product decision model:
      1. score/select gameplay for current gear,
      2. update stat weights at that optimum,
      3. pick best legal gear under those weights,
      4. repeat until the gear selection no longer changes.

    Talents are owned by the caller's surrounding candidate search.  Therefore
    evaluating every talent candidate through this function makes the outer
    talent/rotation search compare candidates at their own converged gear point.
    """
    gear = initial_gear
    trace: list[FixedPointStep] = []
    last_score: Mapping[str, Any] = {}
    last_values: Mapping[str, float] = {}
    converged = False
    cycle_detected = False
    seen_signatures: dict[tuple[Any, ...], int] = {}

    for i in range(1, max(1, int(max_iters)) + 1):
        try:
            from .runtime_progress import emit_runtime_progress
            emit_runtime_progress(
                stage="fixed_point",
                fixed_point_iteration=i,
                fixed_point_max_iters=max(1, int(max_iters)),
            )
        except Exception:
            pass
        score = dict(score_with_gear(gear))
        sw = dict(stat_weights(score) or {})
        values = positive_stat_values(sw)
        sig = tuple(gear_signature(gear))
        trace.append(FixedPointStep(i, score, values, sig))
        last_score, last_values = score, values
        seen_signatures.setdefault(sig, len(trace)-1)

        next_gear = select_gear(gear, values)
        next_sig = tuple(gear_signature(next_gear))
        if next_sig == sig:
            converged = True
            break
        if next_sig in seen_signatures:
            cycle_detected = True
            # Discrete gear choices can oscillate when local derivatives cross a
            # cast-count boundary. The actual leveling objective remains the
            # authority: publish the best state we have really scored, not an
            # arbitrary member of the cycle. Ties prefer the later state.
            def objective(step):
                try:
                    return (float(step.score.get("total_s", float("inf"))), -int(step.iteration))
                except (TypeError, ValueError):
                    return (float("inf"), -int(step.iteration))
            best = min(trace, key=objective)
            last_score, last_values = dict(best.score), dict(best.weights)
            break
        gear = next_gear
    else:
        # The coordinate budget expired without a fixed point. Score the final
        # proposed gear once, then publish the *best actually scored state* over
        # the whole bounded walk. Returning the last proposal unconditionally
        # can make the optimizer dramatically worse when local derivatives
        # oscillate near discrete cast-count/item boundaries.
        final_score = dict(score_with_gear(gear))
        final_sw = dict(stat_weights(final_score) or {})
        final_values = positive_stat_values(final_sw)
        candidates = [(dict(step.score), dict(step.weights), int(step.iteration)) for step in trace]
        candidates.append((final_score, final_values, len(trace)+1))
        def score_key(row):
            score, _values, order = row
            try:
                total = float(score.get("total_s", float("inf")))
            except (TypeError, ValueError):
                total = float("inf")
            return (total, -order)
        last_score, last_values, _best_order = min(candidates, key=score_key)

    out = dict(last_score)
    def _published_sig(score):
        gs=score.get("gear_stats") if isinstance(score, Mapping) else None
        return gs.get("gear_signature") if isinstance(gs, Mapping) else None
    out["gear_fixed_point"] = {
        "iterations": len(trace),
        "converged": converged,
        "cycle_detected": cycle_detected,
        "max_iters": max(1, int(max_iters)),
        "cap_policy": "best_scored_objective_state",
        "trace": [
            {"iteration": s.iteration, "gear_signature": list(s.gear_signature), "weights": dict(s.weights),
             "score_s_per_100": float(s.score.get("total_s", float("inf")))}
            for s in trace
        ],
    }
    return FixedPointResult(out, dict(last_values), len(trace), converged, tuple(trace))

from __future__ import annotations

"""Backend-neutral bounded fixed-point orchestration for coupled optimizers.

The simulator remains a pure scorer. This module only alternates explicit
optimizer dimensions supplied by callbacks and records exact state identity.
"""

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping

from src.game.model.ir import GameIRSlice


@dataclass(frozen=True)
class FixedPointIteration:
    index: int
    state_identity: str
    state_dimensions: Mapping[str, Any]
    seconds_per_mob: float
    stat_weights: Mapping[str, float]
    gear_candidate_id: str
    gear_detail: Mapping[str, Any]
    talent_candidate_id: str | None
    policy_candidate_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "state_identity": self.state_identity,
            "state_dimensions": dict(self.state_dimensions),
            "seconds_per_mob": float(self.seconds_per_mob),
            "stat_weights": {str(k): float(v) for k, v in self.stat_weights.items()},
            "gear_candidate_id": self.gear_candidate_id,
            "gear_detail": dict(self.gear_detail),
            "talent_candidate_id": self.talent_candidate_id,
            "policy_candidate_id": self.policy_candidate_id,
        }


@dataclass(frozen=True)
class FixedPointResult:
    iterations: tuple[FixedPointIteration, ...]
    converged: bool
    stop_reason: str
    selected_iteration: int
    max_iterations: int

    @property
    def selected(self) -> FixedPointIteration:
        return self.iterations[self.selected_iteration]

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": "explicit_bounded_optimizer_fixed_point",
            "dimensions": ["gear", "stat_weights", "talents", "policy"],
            "converged": bool(self.converged),
            "stop_reason": self.stop_reason,
            "iteration_count": len(self.iterations),
            "selected_iteration": int(self.selected_iteration),
            "selected_state_identity": self.selected.state_identity,
            "max_iterations": int(self.max_iterations),
            "iterations": [x.as_dict() for x in self.iterations],
        }


EvaluateState = Callable[[GameIRSlice], Mapping[str, Any]]
MeasureWeights = Callable[[GameIRSlice], Mapping[str, float]]
SelectGear = Callable[[Mapping[str, float]], Mapping[str, Any]]
ApplyGear = Callable[[GameIRSlice, Mapping[str, Any]], GameIRSlice]


def _ir_hash(ir_slice: GameIRSlice) -> str:
    raw = json.dumps(ir_slice.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _state_identity(*, source_ir_hash: str, gear_candidate_id: str, stat_weights: Mapping[str, float],
                    talent_candidate_id: str | None, policy_candidate_id: str | None) -> tuple[str, dict[str, Any]]:
    dims = {
        "source_game_ir_sha256": source_ir_hash,
        "gear_candidate_id": str(gear_candidate_id),
        "stat_weights": {str(k): float(v) for k, v in sorted(stat_weights.items())},
        "talent_candidate_id": talent_candidate_id,
        "policy_candidate_id": policy_candidate_id,
    }
    raw = json.dumps(dims, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), dims


def run_optimizer_fixed_point(
    source_ir_slice: GameIRSlice,
    *,
    evaluate_state: EvaluateState,
    measure_weights: MeasureWeights,
    select_gear: SelectGear,
    apply_gear: ApplyGear,
    max_iterations: int = 4,
) -> FixedPointResult:
    """Alternate explicit optimizer dimensions until exact state repeats.

    Iteration 0 is the naked/bootstrap scorer state. Each following iteration
    selects gear from the previous state's scorer-derived weights, applies that
    candidate to the immutable source IR, then re-runs talent+policy scoring and
    stat sensitivity. Convergence requires the full optimized-dimension identity
    to repeat, not merely the same item set.
    """
    limit = max(1, int(max_iterations))
    source_hash = _ir_hash(source_ir_slice)
    rows: list[FixedPointIteration] = []

    def record(index: int, ir_slice: GameIRSlice, gear_id: str, gear_detail: Mapping[str, Any]) -> FixedPointIteration:
        state = dict(evaluate_state(ir_slice))
        score = state.get("seconds_per_mob")
        if score is None:
            raise ValueError("fixed-point state scorer returned no seconds_per_mob")
        weights = {str(k): float(v) for k, v in dict(measure_weights(ir_slice)).items()}
        identity, dims = _state_identity(
            source_ir_hash=source_hash,
            gear_candidate_id=gear_id,
            stat_weights=weights,
            talent_candidate_id=state.get("talent_candidate_id"),
            policy_candidate_id=state.get("policy_candidate_id"),
        )
        return FixedPointIteration(
            index=index,
            state_identity=identity,
            state_dimensions=dims,
            seconds_per_mob=float(score),
            stat_weights=weights,
            gear_candidate_id=str(gear_id),
            gear_detail=dict(gear_detail),
            talent_candidate_id=state.get("talent_candidate_id"),
            policy_candidate_id=state.get("policy_candidate_id"),
        )

    rows.append(record(0, source_ir_slice, "none", {"status": "naked_bootstrap"}))
    current_weights = rows[0].stat_weights
    converged = False
    stop_reason = "max_iterations"

    for index in range(1, limit + 1):
        gear = dict(select_gear(current_weights))
        gear_id = str(gear.get("candidate_id") or "")
        if not gear_id:
            raise ValueError("gear selector must publish candidate_id")
        candidate_ir = apply_gear(source_ir_slice, gear)
        row = record(index, candidate_ir, gear_id, gear)
        rows.append(row)
        if index >= 2 and row.state_identity == rows[-2].state_identity:
            converged = True
            stop_reason = "exact_state_repeat"
            break
        current_weights = row.stat_weights

    if converged:
        selected_idx = len(rows) - 1
    else:
        # Bounded-best fallback is deterministic and explicit.
        selected_idx = min(range(len(rows)), key=lambda i: (rows[i].seconds_per_mob, rows[i].state_identity))
    return FixedPointResult(tuple(rows), converged, stop_reason, selected_idx, limit)

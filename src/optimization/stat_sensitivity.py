from __future__ import annotations

"""Game-independent exact-scorer stat sensitivity measurement.

The optimizer owns the probing algorithm and result types. Callers supply both
the production scorer and the state mutation callback; this module knows
nothing about GameIR, gear application, source data or combat execution.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, TypeVar

StateT = TypeVar("StateT")

DEFAULT_PROBE_DELTAS = (1.0, 2.0, 5.0, 10.0, 20.0)

Scorer = Callable[[StateT], float | None]
StatPerturbation = Callable[[StateT, str, float], StateT]


@dataclass(frozen=True)
class StatSensitivity:
    stat: str
    value: float
    first_effective_delta: float | None
    baseline_seconds_per_mob: float
    perturbed_seconds_per_mob: float | None
    probes: tuple[Mapping[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stat": self.stat,
            "value": float(self.value),
            "seconds_per_mob_saved_per_point": float(self.value),
            "first_effective_delta": self.first_effective_delta,
            "baseline_seconds_per_mob": float(self.baseline_seconds_per_mob),
            "perturbed_seconds_per_mob": self.perturbed_seconds_per_mob,
            "probes": [dict(x) for x in self.probes],
        }


@dataclass(frozen=True)
class StatSensitivityResult:
    method: str
    baseline_seconds_per_mob: float
    rows: tuple[StatSensitivity, ...]
    probe_deltas: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        ordered = sorted(self.rows, key=lambda x: (-float(x.value), x.stat))
        return {
            "method": self.method,
            "baseline_seconds_per_mob": float(self.baseline_seconds_per_mob),
            "probe_deltas": [float(x) for x in self.probe_deltas],
            "values": {row.stat: float(row.value) for row in self.rows},
            "ranked": [row.as_dict() for row in ordered],
        }


def measure_stat_sensitivities(
    state: StateT,
    *,
    stats: Iterable[str],
    score: Scorer[StateT],
    apply_delta: StatPerturbation[StateT],
    probe_deltas: Iterable[float] = DEFAULT_PROBE_DELTAS,
) -> StatSensitivityResult:
    """Measure exact objective changes using only caller-owned scoring/mutation."""
    deltas = tuple(float(x) for x in probe_deltas if float(x) > 0.0)
    if not deltas:
        raise ValueError("at least one positive stat probe delta is required")
    baseline = score(state)
    if baseline is None:
        raise ValueError("baseline generic scorer returned no score")
    baseline = float(baseline)
    if not isfinite(baseline) or baseline <= 0.0:
        raise ValueError("baseline generic scorer returned nonpositive or nonfinite seconds per mob")

    rows = []
    for stat in tuple(str(x) for x in stats):
        probes = []
        chosen_delta = None
        chosen_score = None
        chosen_value = 0.0
        first_regression = None
        for delta in deltas:
            candidate = apply_delta(state, stat, delta)
            candidate_score = score(candidate)
            if candidate_score is not None:
                candidate_score = float(candidate_score)
                # An incomplete or invalid paid evaluation is not a measured
                # improvement and must not manufacture a positive stat weight.
                if not isfinite(candidate_score) or candidate_score <= 0.0:
                    candidate_score = None
            probes.append({
                "delta": float(delta),
                "seconds_per_mob": candidate_score,
            })
            if candidate_score is None:
                continue
            improvement = baseline - candidate_score
            if improvement > 1e-12:
                # Discrete kill/recovery thresholds can make a smaller
                # perturbation worse while a larger one genuinely helps.
                chosen_delta = float(delta)
                chosen_score = candidate_score
                chosen_value = improvement / float(delta)
                break
            if improvement < -1e-12 and first_regression is None:
                first_regression = (float(delta), candidate_score)
        if chosen_delta is None and first_regression is not None:
            # Preserve a measured regression instead of clipping it to zero.
            chosen_delta, chosen_score = first_regression
            chosen_value = (baseline - chosen_score) / chosen_delta
        rows.append(StatSensitivity(
            stat=stat,
            value=float(chosen_value),
            first_effective_delta=chosen_delta,
            baseline_seconds_per_mob=baseline,
            perturbed_seconds_per_mob=chosen_score,
            probes=tuple(probes),
        ))
    return StatSensitivityResult(
        method="generic_exact_state_first_effect_forward_difference",
        baseline_seconds_per_mob=baseline,
        rows=tuple(rows),
        probe_deltas=deltas,
    )


__all__ = (
    "DEFAULT_PROBE_DELTAS",
    "Scorer",
    "StateT",
    "StatPerturbation",
    "StatSensitivity",
    "StatSensitivityResult",
    "measure_stat_sensitivities",
)

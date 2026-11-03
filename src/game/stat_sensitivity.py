from __future__ import annotations

"""Exact-scorer stat sensitivities for discrete generic objectives."""

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, TypeVar

StateT = TypeVar("StateT")


DEFAULT_PROBE_DELTAS = (1.0, 2.0, 5.0, 10.0, 20.0)


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


Scorer = Callable[[StateT], float | None]
StatPerturbation = Callable[[StateT, str, float], StateT]


def measure_stat_sensitivities(
    ir_slice: StateT,
    *,
    stats: Iterable[str],
    score: Scorer[StateT],
    probe_deltas: Iterable[float] = DEFAULT_PROBE_DELTAS,
    apply_delta: StatPerturbation[StateT] | None = None,
) -> StatSensitivityResult:
    deltas = tuple(float(x) for x in probe_deltas if float(x) > 0.0)
    if not deltas:
        raise ValueError("at least one positive stat probe delta is required")
    baseline = score(ir_slice)
    if baseline is None:
        raise ValueError("baseline generic scorer returned no score")
    baseline = float(baseline)
    if not isfinite(baseline) or baseline <= 0.0:
        raise ValueError('baseline generic scorer returned nonpositive or nonfinite seconds per mob')
    # Legacy IR gear semantics remain the default until callers migrate.
    # Native clients can supply a typed request mutation without importing
    # the retiring Python GameIR/gear implementation.
    if apply_delta is None:
        from src.game.gear import apply_stat_delta
        apply_delta = apply_stat_delta
    rows = []
    for stat in tuple(str(x) for x in stats):
        probes = []
        chosen_delta = None
        chosen_score = None
        chosen_value = 0.0
        first_regression = None
        for delta in deltas:
            candidate = apply_delta(ir_slice, stat, delta)
            candidate_score = score(candidate)
            if candidate_score is not None:
                candidate_score = float(candidate_score)
                # The paid production evaluator can fail to complete a kill
                # or return an invalid score. Such a probe is NOT a measured
                # improvement and must not manufacture a positive gear weight.
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
                # Discrete kill/recovery thresholds can make a small positive
                # gear perturbation worse while a larger one genuinely helps.
                # Keep searching for the first *measured* beneficial step.
                chosen_delta = float(delta)
                chosen_score = candidate_score
                chosen_value = improvement / float(delta)
                break
            if improvement < -1e-12 and first_regression is None:
                first_regression = (float(delta), candidate_score)
        if chosen_delta is None and first_regression is not None:
            # Do not clip a real regression to zero or fabricate a positive
            # P3 weight when no tested production perturbation improves time.
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

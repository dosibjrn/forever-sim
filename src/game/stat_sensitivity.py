from __future__ import annotations

"""Exact-scorer stat sensitivities for discrete generic objectives."""

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from src.game.gear import apply_stat_delta
from src.game.model.ir import GameIRSlice


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


Scorer = Callable[[GameIRSlice], float | None]


def measure_stat_sensitivities(
    ir_slice: GameIRSlice,
    *,
    stats: Iterable[str],
    score: Scorer,
    probe_deltas: Iterable[float] = DEFAULT_PROBE_DELTAS,
) -> StatSensitivityResult:
    deltas = tuple(float(x) for x in probe_deltas if float(x) > 0.0)
    if not deltas:
        raise ValueError("at least one positive stat probe delta is required")
    baseline = score(ir_slice)
    if baseline is None:
        raise ValueError("baseline generic scorer returned no score")
    baseline = float(baseline)
    rows = []
    for stat in tuple(str(x) for x in stats):
        probes = []
        chosen_delta = None
        chosen_score = None
        chosen_value = 0.0
        for delta in deltas:
            candidate = apply_stat_delta(ir_slice, stat, delta)
            candidate_score = score(candidate)
            probes.append({
                "delta": float(delta),
                "seconds_per_mob": None if candidate_score is None else float(candidate_score),
            })
            if candidate_score is None:
                continue
            candidate_score = float(candidate_score)
            if abs(candidate_score - baseline) > 1e-12:
                chosen_delta = float(delta)
                chosen_score = candidate_score
                chosen_value = (baseline - candidate_score) / float(delta)
                break
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

from __future__ import annotations

"""Adaptive stochastic adjudication for complete frozen leveling paths.

This is deliberately separate from broad MC search.  Every candidate supplies a
fixed talents+policy choice for the same level set.  Each round extends only the
surviving candidates using the simulator's continuation state, combines the
per-level estimates with the authoritative XP-workload weights, and eliminates
only candidates whose optimistic whole-path interval is slower than another
candidate's pessimistic interval.
"""

from dataclasses import dataclass, field
import math
from statistics import NormalDist
from typing import Callable, Mapping, Sequence, Any

from src.engine_registry import eng
from src import objective


@dataclass(frozen=True)
class FrozenLevel:
    level: int
    talents: eng.Talents
    policy: eng.Policy


@dataclass(frozen=True)
class FrozenPath:
    name: str
    levels: tuple[FrozenLevel, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PathRaceRow:
    candidate_index: int
    mobs_per_level: int
    mean_seconds: float
    stderr_seconds: float
    lower_seconds: float
    upper_seconds: float
    eliminated: bool = False

    @property
    def mean_hours(self) -> float:
        return self.mean_seconds / 3600.0

    @property
    def stderr_hours(self) -> float:
        return self.stderr_seconds / 3600.0


@dataclass(frozen=True)
class PathRaceResult:
    winner_index: int
    survivor_indices: tuple[int, ...]
    resolved: bool
    rows: tuple[PathRaceRow, ...]
    rounds: int
    total_mobs_simulated: int
    critical_z: float


def _z_bonferroni(alpha: float, n: int) -> float:
    tail = max(1e-15, min(0.25, float(alpha) / (2.0 * max(1, int(n)))))
    return NormalDist().inv_cdf(1.0 - tail)


def _default_simulate(level, talents, policy, cfg, *, target_n, seed, continuation):
    return eng.simulate_chain_incremental(
        int(level), talents, policy, cfg,
        target_n=int(target_n), seed=int(seed), continuation=continuation,
    )


def _path_levels(candidate: FrozenPath) -> tuple[int, ...]:
    levels = tuple(int(row.level) for row in candidate.levels)
    if len(levels) != len(set(levels)):
        raise ValueError(f'duplicate level in frozen path {candidate.name!r}')
    return levels


def _aggregate(candidate_index: int, candidate: FrozenPath, metrics: dict[tuple[int, int], dict],
               target: int, z: float, eliminated: bool,
               weight_fn: Callable[[int], float]) -> PathRaceRow:
    mean_s = 0.0
    var_s = 0.0
    for row in candidate.levels:
        m = metrics[(candidate_index, int(row.level))]
        w = float(weight_fn(int(row.level)))
        mean = float(m['mean_s_per_mob'])
        se = float(m['stderr_s_per_mob'])
        if not math.isfinite(mean):
            raise ValueError(f'non-finite stochastic mean for candidate {candidate_index} level {row.level}')
        if se < 0 or math.isnan(se):
            raise ValueError(f'invalid stochastic stderr for candidate {candidate_index} level {row.level}')
        mean_s += mean * w
        if math.isfinite(se):
            var_s += (se * w) ** 2
        else:
            var_s = math.inf
    stderr_s = math.sqrt(var_s)
    if math.isfinite(stderr_s):
        lo = mean_s - z * stderr_s
        hi = mean_s + z * stderr_s
    else:
        lo, hi = -math.inf, math.inf
    return PathRaceRow(candidate_index, int(target), mean_s, stderr_s, lo, hi, eliminated)


def race_paths(candidates: Sequence[FrozenPath], cfg: eng.SimConfig, *,
               start_mobs: int = 100, max_mobs: int = 3200, growth: int = 2,
               alpha: float = 0.05, seed: int = 1,
               simulate_incremental: Callable | None = None,
               weight_fn: Callable[[int], float] = objective.estimated_workload_mobs) -> PathRaceResult:
    """Race fixed whole paths with adaptive per-level continuation.

    ``resolved`` is true only when confidence elimination leaves exactly one
    survivor.  At ``max_mobs`` overlapping survivors remain explicitly
    unresolved; the lowest sample mean is reported as ``winner_index`` only as
    a diagnostic ordering, not as authoritative proof.
    """
    if not candidates:
        raise ValueError('no path candidates')
    if int(start_mobs) < 2 or int(max_mobs) < int(start_mobs):
        raise ValueError('invalid mob limits')
    if int(growth) < 2:
        raise ValueError('growth must be >=2')

    level_sets = [_path_levels(c) for c in candidates]
    if any(levels != level_sets[0] for levels in level_sets[1:]):
        raise ValueError('full-path race requires identical level sets')
    if not level_sets[0]:
        raise ValueError('empty frozen path')

    sim = simulate_incremental or _default_simulate
    z = _z_bonferroni(alpha, len(candidates))
    alive = set(range(len(candidates)))
    continuations: dict[tuple[int, int], Any] = {}
    metrics: dict[tuple[int, int], dict] = {}
    current_n = {i: 0 for i in range(len(candidates))}
    total_mobs = 0
    target = int(start_mobs)
    rounds = 0

    while alive:
        rounds += 1
        for i in sorted(alive):
            prev_n = current_n[i]
            cand = candidates[i]
            for j, row in enumerate(cand.levels):
                key = (i, int(row.level))
                out, state = sim(
                    int(row.level), row.talents, row.policy, cfg,
                    target_n=target,
                    seed=int(seed) + j * 1_000_003,
                    continuation=continuations.get(key),
                )
                metrics[key] = out
                continuations[key] = state
                total_mobs += target - prev_n
            current_n[i] = target

        current_rows = {
            i: _aggregate(i, candidates[i], metrics, target, z, False, weight_fn)
            for i in alive
        }
        best_upper = min(r.upper_seconds for r in current_rows.values())
        drop = {i for i, r in current_rows.items() if r.lower_seconds > best_upper + 1e-12}
        if len(drop) >= len(alive):
            drop.clear()
        alive -= drop

        if len(alive) <= 1 or target >= int(max_mobs):
            break
        target = min(int(max_mobs), target * int(growth))

    evaluated = sorted({i for i, _lvl in metrics})
    final_rows = [
        _aggregate(i, candidates[i], metrics, current_n[i], z, i not in alive, weight_fn)
        for i in evaluated
    ]
    final_rows.sort(key=lambda r: r.mean_seconds)
    survivor_indices = tuple(sorted(alive))
    winner_pool = survivor_indices or tuple(r.candidate_index for r in final_rows)
    winner_index = min(
        winner_pool,
        key=lambda i: next(r.mean_seconds for r in final_rows if r.candidate_index == i),
    )
    return PathRaceResult(
        winner_index=winner_index,
        survivor_indices=survivor_indices,
        resolved=len(survivor_indices) == 1,
        rows=tuple(final_rows),
        rounds=rounds,
        total_mobs_simulated=total_mobs,
        critical_z=z,
    )

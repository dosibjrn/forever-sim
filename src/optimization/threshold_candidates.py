"""Backend-neutral G17 numeric candidate product and deterministic identities.

The game adapter owns which thresholds are legal/meaningful and how they are
applied to a policy. This module only enumerates supplied numeric choices.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterator, Mapping, Protocol


class ThresholdAxisLike(Protocol):
    key: str
    values: tuple[float, ...]
    baseline_value: float


@dataclass(frozen=True)
class ThresholdAxis:
    key: str
    values: tuple[float, ...]
    baseline_value: float = 0.0


@dataclass(frozen=True)
class ThresholdCombination:
    values: tuple[float, ...]
    candidate_id: str
    thresholds: Mapping[str, float]
    is_baseline: bool
    distance: float


def iter_threshold_candidates(
    structural_id: str,
    axes: tuple[ThresholdAxisLike, ...],
    *,
    limit: int,
) -> Iterator[ThresholdCombination]:
    """Enumerate the bounded Cartesian product in stable source-axis order."""
    if limit <= 0:
        return
    choices = product(*(axis.values for axis in axes)) if axes else ((),)
    for index, raw_values in enumerate(choices):
        if index >= limit:
            return
        values = tuple(float(value) for value in raw_values)
        parts = [f"{axis.key}={float(value):g}" for axis, value in zip(axes, values)]
        candidate_id = structural_id + ("|thresholds:" + ";".join(parts) if parts else "|thresholds:none")
        yield ThresholdCombination(
            values=values,
            candidate_id=candidate_id,
            thresholds={axis.key: float(value) for axis, value in zip(axes, values)},
            is_baseline=all(abs(value - axis.baseline_value) < 1e-12 for axis, value in zip(axes, values)),
            distance=sum(abs(value - axis.baseline_value) / (abs(axis.baseline_value) + 1.0)
                         for axis, value in zip(axes, values)),
        )


__all__ = ("ThresholdAxis", "ThresholdAxisLike", "ThresholdCombination", "iter_threshold_candidates")

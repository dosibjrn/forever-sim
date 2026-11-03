from __future__ import annotations

"""Compatibility adapter for exact-scorer stat sensitivities.

The game-independent probing algorithm and result types live in
src.optimization.stat_sensitivity. This module retains the existing stat-scale
configuration and legacy GameIR gear mutation default for current callers.
"""

from typing import Iterable

from src.optimization.stat_sensitivity import (
    DEFAULT_PROBE_DELTAS,
    Scorer,
    StateT,
    StatPerturbation,
    StatSensitivity,
    StatSensitivityResult,
    measure_stat_sensitivities as _measure_stat_sensitivities,
)


# A source delta in the *input unit*, not a game-specific damage coefficient.
# Stat-specific probe scales are input-unit perturbations, not combat effect coefficients.
# Agility and weapon DPS must cross discrete 100-mob action/kill thresholds.
# These are *minimum item-relevant steps*, not locally reliable derivatives.
PROBE_STEPS = {
    'strength': 5., 'agility': 20., 'stamina': 5., 'intellect': 5.,
    'spirit': 5., 'attack_power': 10., 'spell_power': 10.,
    'healing': 10., 'mp5': 5., 'armor': 100.,
    'weapon_dps': 10., 'wand_dps': 2.,
    'health_regeneration_per_5s': 5.,
}


def measure_stat_sensitivities(
    ir_slice: StateT,
    *,
    stats: Iterable[str],
    score: Scorer[StateT],
    probe_deltas: Iterable[float] = DEFAULT_PROBE_DELTAS,
    apply_delta: StatPerturbation[StateT] | None = None,
) -> StatSensitivityResult:
    """Preserve the legacy API while delegating generic probing to optimization."""
    if apply_delta is None:
        # Existing GameIR callers retain their historical default. Native callers
        # can pass a typed request mutation without importing this legacy path.
        from src.game.gear import apply_stat_delta
        apply_delta = apply_stat_delta
    return _measure_stat_sensitivities(
        ir_slice,
        stats=stats,
        score=score,
        apply_delta=apply_delta,
        probe_deltas=probe_deltas,
    )


__all__ = (
    "DEFAULT_PROBE_DELTAS",
    "PROBE_STEPS",
    "Scorer",
    "StateT",
    "StatPerturbation",
    "StatSensitivity",
    "StatSensitivityResult",
    "measure_stat_sensitivities",
)

"""Compatibility re-export for the optimizer-owned fixed-point orchestration.

The algorithm accepts a serializable scorer state and callbacks; it has no
game-model or runtime dependency. New production imports should use
``src.optimization.fixed_point``.
"""

from src.optimization.fixed_point import (
    ApplyGear,
    EvaluateState,
    FixedPointIteration,
    FixedPointResult,
    MeasureWeights,
    SelectGear,
    SerializableOptimizerState,
    run_optimizer_fixed_point,
)

__all__ = (
    "ApplyGear",
    "EvaluateState",
    "FixedPointIteration",
    "FixedPointResult",
    "MeasureWeights",
    "SelectGear",
    "SerializableOptimizerState",
    "run_optimizer_fixed_point",
)

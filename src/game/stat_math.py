"""Pure, game-agnostic evaluation of source-declared stat conversion curves.

The coefficients, thresholds, sources and target resource names belong to
canonical data, not this executor math module.
"""
from math import isfinite


def converted_stat_amount(fact: dict, value: float) -> float:
    v = max(0.0, float(value))
    if not isfinite(v):
        raise ValueError('NONFINITE_SOURCE_STAT_CONVERSION_INPUT')
    coefficient = float(fact['coefficient'])
    if not isfinite(coefficient) or coefficient <= 0:
        raise ValueError('INVALID_SOURCE_STAT_CONVERSION_COEFFICIENT')
    if fact['operation'] == 'linear':
        return v * coefficient
    if fact['operation'] == 'threshold_linear':
        threshold = float(fact['threshold'])
        below = float(fact['below_coefficient'])
        if not (isfinite(threshold) and threshold >= 0 and isfinite(below) and below > 0):
            raise ValueError('INVALID_SOURCE_STAT_CONVERSION_THRESHOLD')
        return min(v, threshold) * below + max(0.0, v-threshold) * coefficient
    raise ValueError('UNSUPPORTED_SOURCE_STAT_CONVERSION_OPERATION')

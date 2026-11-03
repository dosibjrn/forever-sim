"""Pure arithmetic for source-declared stat conversion curves.

The source coefficients, thresholds, target identifiers and provenance are
owned by the caller. This module only evaluates the generic conversion shape;
it imports no game model, source catalogue or combat runtime.
"""
from math import isfinite


def converted_stat_amount(fact: dict, value: float) -> float:
    raw_value = float(value)
    if not isfinite(raw_value):
        raise ValueError('NONFINITE_SOURCE_STAT_CONVERSION_INPUT')
    v = max(0.0, raw_value)
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


__all__ = ("converted_stat_amount",)

"""Compatibility re-export for the former game-layer stat conversion helper.

The pure, source-fact-driven arithmetic lives in :mod:`src.shared.stat_math`.
Keep this import path stable for downstream and historical callers.
"""
from src.shared.stat_math import converted_stat_amount

__all__ = ("converted_stat_amount",)

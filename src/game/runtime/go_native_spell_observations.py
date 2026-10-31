"""Validate *actual native-sourced* cumulative spell metrics in the Go range loop.

Metric deltas show native activity after world inputs, but are not exact-time
spell events or applied gsim world-action ACKs. Source provenance requires the
live pinned Go process; a stand-alone JSON object cannot prove origin.
"""
from __future__ import annotations

from math import isfinite
from typing import Mapping


class NativeSpellObservationError(ValueError):
    pass


class NativeSpellObservationLedger:
    """Track cumulative pinned-Go spell counters without fabricating actions."""

    _counts = ("casts", "hits", "crits", "ticks")

    def __init__(self):
        self._last: dict[tuple[str, int], dict] = {}
        self._next_seq = 0

    def observe(self, rows: list, *, sequence: int) -> list[dict]:
        if type(sequence) is not int or sequence != self._next_seq:
            raise NativeSpellObservationError("NATIVE_SPELL_OBSERVATION_SEQUENCE_INVALID")
        if not isinstance(rows, list):
            raise NativeSpellObservationError("NATIVE_SPELL_OBSERVATIONS_NOT_LIST")
        current: dict[tuple[str, int], dict] = {}
        deltas: list[dict] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise NativeSpellObservationError("NATIVE_SPELL_OBSERVATION_NOT_MAPPING")
            action = row.get("action_id")
            rank = row.get("rank")
            if not isinstance(action, str) or not action or type(rank) is not int or rank < 0:
                raise NativeSpellObservationError("NATIVE_SPELL_IDENTITY_INVALID")
            key = (action, rank)
            if key in current:
                raise NativeSpellObservationError("NATIVE_SPELL_IDENTITY_DUPLICATE")
            parsed = {}
            for field in self._counts:
                value = row.get(field)
                if type(value) is not int or value < 0:
                    raise NativeSpellObservationError("NATIVE_SPELL_COUNT_INVALID:" + field)
                parsed[field] = value
            damage = row.get("total_damage")
            if type(damage) not in (int, float) or not isfinite(damage) or damage < 0:
                raise NativeSpellObservationError("NATIVE_SPELL_DAMAGE_INVALID")
            parsed["total_damage"] = float(damage)
            if not any(parsed.values()):
                raise NativeSpellObservationError("NATIVE_SPELL_REGISTERED_BUT_UNOBSERVED")
            prev = self._last.get(key, {name: 0 for name in (*self._counts, "total_damage")})
            delta = {}
            for name, value in parsed.items():
                difference = value - prev[name]
                if difference < -1e-8:
                    raise NativeSpellObservationError("NATIVE_SPELL_COUNTER_REGRESSED:" + action)
                delta[name] = max(0, difference)
            current[key] = parsed
            if any(delta.values()):
                deltas.append({"action_id": action, "rank": rank, **delta})
        # Previously observed spell IDs may disappear after a tag switch or form
        # transition; this is NOT proof they were undone. Never fabricate a
        # negative delta or retroactively delete their history.
        self._last.update(current)
        self._next_seq += 1
        return deltas

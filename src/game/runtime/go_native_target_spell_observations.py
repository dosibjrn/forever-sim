"""Fail-closed mapping audit for *observed* one-enemy native Go spell metrics.

Provides target identity for later true native spell → gsim world application.
Does NOT apply damage, create action IDs, or assert a production world ACK.
"""
from __future__ import annotations

from typing import Mapping

from .go_native_spell_observations import (
    NativeSpellObservationError, NativeSpellObservationLedger,
)


class NativeTargetSpellObservationLedger:
    """One native target and an explicit gsim selected-target mapping per tick."""

    def __init__(self):
        self._ledger = NativeSpellObservationLedger()
        self._native_identity: tuple[int, int, str] | None = None
        self._gsim_target_id: str | None = None

    def begin_next_world_target(self, previous_target_id: str, next_target_id: str) -> None:
        # Keep cumulative native source counters: only the gsim mapping
        # changes between serial pulls, never the native process or target slot.
        if (self._gsim_target_id != previous_target_id
                or not isinstance(next_target_id, str)
                or not next_target_id or next_target_id == previous_target_id):
            raise NativeSpellObservationError("NATIVE_TARGET_LEDGER_INVALID_SERIAL_RETARGET")
        self._gsim_target_id = next_target_id

    def observe(self, rows, *, sequence: int, gsim_target_id: str) -> list[dict]:
        if not isinstance(gsim_target_id, str) or not gsim_target_id:
            raise NativeSpellObservationError("GSIM_TARGET_ID_MISSING")
        if self._gsim_target_id is not None and gsim_target_id != self._gsim_target_id:
            raise NativeSpellObservationError("GSIM_SELECTED_TARGET_CHANGED_WITHOUT_NATIVE_RETARGET")
        if not isinstance(rows, list):
            raise NativeSpellObservationError("NATIVE_TARGET_SPELL_ROWS_INVALID")
        identity = self._native_identity
        for row in rows:
            if not isinstance(row, Mapping):
                raise NativeSpellObservationError("NATIVE_TARGET_SPELL_ROW_INVALID")
            idx, unit_idx, label = (row.get("native_target_index"),
                                    row.get("native_target_unit_index"),
                                    row.get("native_target_label"))
            if (type(idx) is not int or idx != 0
                    or type(unit_idx) is not int or unit_idx < 0
                    or not isinstance(label, str) or not label):
                raise NativeSpellObservationError("NATIVE_TARGET_SPELL_IDENTITY_INVALID")
            current = (idx, unit_idx, label)
            if identity is not None and current != identity:
                raise NativeSpellObservationError("NATIVE_TARGET_SPELL_IDENTITY_CHANGED")
            identity = current
        # Commit ledger state only after every native target identity validates.
        deltas = self._ledger.observe(rows, sequence=sequence)
        self._native_identity = identity
        self._gsim_target_id = gsim_target_id
        return [{"gsim_selected_target_id": gsim_target_id,
                 "native_target_index": 0,
                 "native_target_unit_index": identity[1] if identity else None,
                 "native_target_label": identity[2] if identity else None,
                 **delta} for delta in deltas]

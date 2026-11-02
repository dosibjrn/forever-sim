"""Fail-closed counter tests. Synthetic rows are schema fixtures, NOT P7 evidence."""
from __future__ import annotations

import math
import pytest

from src.game.runtime.go_native_spell_observations import (
    NativeSpellObservationError, NativeSpellObservationLedger,
)


def spell(casts=1, damage=12.5, *, action="SpellID:8921", rank=2):
    return {"action_id": action, "rank": rank, "casts": casts, "hits": casts,
            "crits": 0, "ticks": 0, "total_damage": damage}


def test_real_native_counter_ledger_accumulates_only_actual_deltas():
    ledger = NativeSpellObservationLedger()
    first = ledger.observe([spell()], sequence=0)
    assert first == [spell()]
    assert ledger.observe([spell()], sequence=1) == []
    third = ledger.observe([spell(3, 29.)], sequence=2)
    assert third[0]["casts"] == 2
    assert third[0]["total_damage"] == pytest.approx(16.5)
    assert third[0]["action_id"] == "SpellID:8921"


def test_tag_or_form_transition_keeps_prior_counter_history():
    ledger = NativeSpellObservationLedger()
    ledger.observe([spell()], sequence=0)
    switched = ledger.observe([spell(action="SpellID:8921/tag1")], sequence=1)
    assert len(switched) == 1
    assert ledger.observe([spell()], sequence=2) == []


@pytest.mark.parametrize("rows", [
    None, {},
    [spell(casts=-1)], [spell(damage=-1)],
    [spell(damage=math.nan)], [spell(damage=math.inf)],
    [dict(spell(), casts=True)], [dict(spell(), rank=True)],
    [dict(spell(), action_id="")], [dict(spell(), hits="5")],
    [spell(), spell()], [spell(casts=0, damage=0)],
])
def test_malformed_or_fake_native_counters_rejected(rows):
    with pytest.raises(NativeSpellObservationError):
        NativeSpellObservationLedger().observe(rows, sequence=0)


def test_mismatched_order_or_regressed_counters_rejected():
    ledger = NativeSpellObservationLedger()
    with pytest.raises(NativeSpellObservationError, match="SEQUENCE"):
        ledger.observe([], sequence=1)
    ledger.observe([spell(2, 20)], sequence=0)
    with pytest.raises(NativeSpellObservationError, match="REGRESSED"):
        ledger.observe([spell(1, 20)], sequence=1)
    # A failed receipt must not advance the ledger's world-tick sequence.
    good = ledger.observe([spell(3, 25)], sequence=1)
    assert good[0]["casts"] == 1

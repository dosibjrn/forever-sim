from datetime import date

import pytest

from src.rulesets.forever.shared.tuning import (
    active_spell_tuning,
    base_damage_multiplier,
)


def test_wrath_september_24_tuning_is_dated_and_not_back_applied():
    assert base_damage_multiplier('druid', 'wrath', as_of=date(2026, 9, 23)) == pytest.approx(1.0)
    assert base_damage_multiplier('druid', 'wrath', as_of=date(2026, 9, 24)) == pytest.approx(1.5)
    rows = active_spell_tuning('druid', 'wrath', as_of=date(2026, 10, 2))
    assert len(rows) == 1
    assert rows[0].effective_from == date(2026, 9, 24)
    assert rows[0].approximate is True
    assert 'base damage increased ~50%' in rows[0].source_note


def test_unrelated_spell_has_no_implicit_tuning():
    assert base_damage_multiplier('druid', 'moonfire') == pytest.approx(1.0)
    assert active_spell_tuning('mage', 'frostbolt') == ()

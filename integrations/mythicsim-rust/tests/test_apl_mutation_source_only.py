"""P7.2 source-only APL proposals must not be rewritten by Python fallbacks.

The native scorer, not Forever, decides whether an original source action
remains executable after a priority-list edit.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import mutate_apl


SOURCE_FALLBACK = {
    "action": {"castSpell": {"spellId": {"itemId": 9449}}}
}
SOURCE_CONDITIONAL = {
    "action": {
        "castSpell": {"spellId": {"spellId": 768}},
        "condition": {"auraIsActive": {"auraId": {"spellId": 768}}},
    },
}
SOURCE_OPAQUE = {
    "action": {
        "autocastOtherCooldowns": {},
        "condition": {"currentMana": {}},
    },
}
SOURCE_ACTIONS = [SOURCE_FALLBACK, SOURCE_CONDITIONAL, SOURCE_OPAQUE]


class SwapFirstTwo:
    def choices(self, modes, *, weights):
        assert "swap" in modes
        return ["swap"]

    def sample(self, population, size):
        assert size == 2
        return [0, 1]


class ColdWithoutFallback:
    def randint(self, low, high):
        assert low == 2 and high == len(SOURCE_ACTIONS)
        return 2

    def sample(self, population, size):
        assert size == 2
        return [SOURCE_CONDITIONAL, SOURCE_OPAQUE]

    def shuffle(self, values):
        pass


def test_source_only_local_swap_does_not_reorder_native_fallback_or_conditions():
    source = copy.deepcopy(SOURCE_ACTIONS)
    proposed = mutate_apl(
        source, source, SwapFirstTwo(), cold=False,
        preserve_source_conditions=True)
    assert proposed == [SOURCE_CONDITIONAL, SOURCE_FALLBACK, SOURCE_OPAQUE]
    assert source == SOURCE_ACTIONS
    assert proposed[0] is not source[1]


def test_source_only_cold_proposal_does_not_invent_a_python_fallback():
    source = copy.deepcopy(SOURCE_ACTIONS)
    proposed = mutate_apl(
        None, source, ColdWithoutFallback(), cold=True,
        preserve_source_conditions=True)
    assert proposed == [SOURCE_CONDITIONAL, SOURCE_OPAQUE]
    assert source == SOURCE_ACTIONS
    assert all(entry in SOURCE_ACTIONS for entry in proposed)

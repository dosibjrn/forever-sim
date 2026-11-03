"""Unconditional castSpell entries are priority-list fallbacks, not ordinary actions."""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import _ensure_fallback, _is_unconditional_cast, mutate_apl


UNCONDITIONAL_ONE = {
    "action": {"castSpell": {"spellId": {"spellId": 12345}}}
}
CONDITIONAL = {
    "action": {
        "castSpell": {"spellId": {"spellId": 23456}},
        "condition": {
            "cmp": {
                "lhs": {"currentMana": {}},
                "op": "OpLe",
                "rhs": {"const": {"val": "500"}},
            }
        },
    }
}
COOLDOWNS = {"action": {"autocastOtherCooldowns": {}}}
SOURCE_ACTIONS = [UNCONDITIONAL_ONE, CONDITIONAL, COOLDOWNS]


def _fallback_indices(actions):
    return [index for index, entry in enumerate(actions)
            if _is_unconditional_cast(entry)]


def _assert_fallback_suffix(actions):
    indices = _fallback_indices(actions)
    assert indices, "source-backed APL must retain an unconditional cast fallback"
    assert indices == list(range(len(actions) - len(indices), len(actions))), (
        "unconditional castSpell actions must be the stable tail of the priority list",
        indices,
        actions,
    )


def test_ensure_fallback_moves_all_unconditional_casts_after_conditional_and_opaque_actions():
    actions = [
        copy.deepcopy(UNCONDITIONAL_ONE),
        copy.deepcopy(COOLDOWNS),
        copy.deepcopy(CONDITIONAL),
        copy.deepcopy(UNCONDITIONAL_ONE),
        copy.deepcopy(CONDITIONAL),
    ]
    _ensure_fallback(actions, SOURCE_ACTIONS)
    assert actions == [
        copy.deepcopy(COOLDOWNS),
        copy.deepcopy(CONDITIONAL),
        copy.deepcopy(CONDITIONAL),
        copy.deepcopy(UNCONDITIONAL_ONE),
        copy.deepcopy(UNCONDITIONAL_ONE),
    ]
    _assert_fallback_suffix(actions)


def test_cold_apl_generation_never_places_unconditional_cast_before_conditional_actions():
    source_snapshot = copy.deepcopy(SOURCE_ACTIONS)
    for seed in range(128):
        actions = mutate_apl(
            None, SOURCE_ACTIONS, random.Random(seed), cold=True)
        assert 2 <= len(actions) <= 20
        _assert_fallback_suffix(actions)
    assert SOURCE_ACTIONS == source_snapshot, "cold generation must not mutate its grammar"


def test_paid_local_apl_mutation_keeps_unconditional_casts_at_the_tail():
    source_snapshot = copy.deepcopy(SOURCE_ACTIONS)
    starting = [
        copy.deepcopy(UNCONDITIONAL_ONE),
        copy.deepcopy(COOLDOWNS),
        copy.deepcopy(CONDITIONAL),
        copy.deepcopy(UNCONDITIONAL_ONE),
    ]
    for seed in range(128):
        actions = mutate_apl(
            starting, SOURCE_ACTIONS, random.Random(seed), cold=False)
        assert 2 <= len(actions) <= 20
        _assert_fallback_suffix(actions)
    assert SOURCE_ACTIONS == source_snapshot, "local mutations must not mutate their grammar"
    assert starting[0] == UNCONDITIONAL_ONE, "local mutations must not mutate their paid parent"

"""P7.2 starts independently, then improves only its own paid winner.

The prior 300s run redrew policies from scratch, never exploiting its best
source-legal native/2D rotation within the budget.
"""
from copy import deepcopy
import random

import pytest

from tools.wf_gate_p7_2_live import _cold_apl


def _base():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 42}]},
        "talentsString": "fixed",
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": {"spellId": 10}}}},
                                      {"action": {"castSpell": {"spellId": {"spellId": 20}}}}]},
    }]}]}}


def _player(request):
    return request["raid"]["parties"][0]["players"][0]


def test_first_candidate_is_independent_cold_draw():
    base = _base()
    calls = []

    class Grammar:
        @staticmethod
        def mutate_apl(actions, source_actions, rng, *, cold):
            calls.append((actions, deepcopy(source_actions), cold))
            return [{"action": {"castSpell": {"spellId": {"spellId": 20}}}},
                    {"action": {"castSpell": {"spellId": {"spellId": 10}}}}]

    result = _cold_apl(base, random.Random(1), Grammar)
    assert calls == [(None, _player(base)["rotation"]["priorityList"], True)]
    assert _player(result)["equipment"] == _player(base)["equipment"]
    assert _player(result)["talentsString"] == "fixed"


def test_local_mutation_uses_only_paid_elite_rotation_and_reference_grammar():
    base = _base()
    paid = deepcopy(base)
    _player(paid)["rotation"]["priorityList"] = [{"action": {"paid": "winning-action"}}]
    observed = []

    class Grammar:
        @staticmethod
        def mutate_apl(actions, source_actions, rng, *, cold):
            observed.append((deepcopy(actions), deepcopy(source_actions), cold))
            return [{"action": {"castSpell": {"spellId": {"spellId": 20}}}}]

    result = _cold_apl(base, random.Random(3), Grammar, elite=paid)
    assert observed == [(_player(paid)["rotation"]["priorityList"],
                         _player(base)["rotation"]["priorityList"], False)]
    assert _player(result)["rotation"]["priorityList"] != _player(paid)["rotation"]["priorityList"]
    assert _player(result)["equipment"] == _player(base)["equipment"]
    assert _player(base)["rotation"]["priorityList"] != _player(paid)["rotation"]["priorityList"]


@pytest.mark.parametrize("fixed_axis", ["equipment", "talentsString"])
def test_paid_elite_cannot_change_fixed_axes(fixed_axis):
    base = _base()
    paid = deepcopy(base)
    _player(paid)[fixed_axis] = "not-the-fixed-reference"

    class NeverRun:
        @staticmethod
        def mutate_apl(*args, **kwargs):
            raise AssertionError("Illegal paid elite must be rejected before mutation")

    with pytest.raises(ValueError, match="P72_PAID_ELITE_CHANGED_FIXED_DIMENSIONS"):
        _cold_apl(base, random.Random(5), NeverRun, elite=paid)

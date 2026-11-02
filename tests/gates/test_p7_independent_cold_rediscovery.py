"""P7 cold searches must not reject a reference build found without seeding.

The saved reference is a fixed legal comparator, not a forbidden candidate.
The random cold generator must stay independent of the saved configuration.
"""
from __future__ import annotations

from copy import deepcopy
import random

from tools.wf_gate_p7_2_live import _cold_apl
from tools.wf_gate_p7_3_live import _cold_talents


def _saved_request() -> dict:
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 1}]},
        "talentsString": "reference-allocation",
        "rotation": {"priorityList": [{"castSpell": {"spellId": 1}},
                                      {"castSpell": {"spellId": 2}}]},
    }]}]}}


def _player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def test_p72_independent_cold_apl_may_rediscover_saved_policy():
    base = _saved_request()
    called = []

    class ColdAPL:
        @staticmethod
        def mutate_apl(elite, source_actions, rng, *, cold):
            called.append((elite, cold))
            assert isinstance(rng, random.Random)
            # A genuinely independent cold draw can happen to produce the
            # identical policy without the saved policy being a paid seed.
            return deepcopy(source_actions)

    discovered = _cold_apl(base, random.Random(33), ColdAPL)
    assert called == [(None, True)]
    assert _player(discovered) == _player(base)
    assert discovered is not base
    assert _player(discovered) is not _player(base)


def test_p73_independent_cold_talents_may_rediscover_saved_allocation():
    base = _saved_request()
    called = []

    class ColdTalentSource:
        @staticmethod
        def random_build(rng):
            assert isinstance(rng, random.Random)
            called.append("independent")
            return (2, 1)

        @staticmethod
        def validate(allocation):
            assert allocation == (2, 1)
            return True

        @staticmethod
        def encode(allocation):
            return "reference-allocation"

    discovered = _cold_talents(base, random.Random(37), ColdTalentSource)
    assert called == ["independent"]
    assert _player(discovered) == _player(base)
    assert discovered is not base


def test_p73_independent_new_talent_still_keeps_reference_gear_apl():
    base = _saved_request()

    class AlternateTalentSource:
        @staticmethod
        def random_build(rng):
            return (3, 0)

        @staticmethod
        def validate(allocation):
            return allocation == (3, 0)

        @staticmethod
        def encode(allocation):
            return "new-legal-allocation"

    discovered = _cold_talents(base, random.Random(41), AlternateTalentSource)
    assert _player(discovered)["talentsString"] == "new-legal-allocation"
    assert _player(discovered)["equipment"] == _player(base)["equipment"]
    assert _player(discovered)["rotation"] == _player(base)["rotation"]


def test_p72_p75_shared_cold_apl_samples_grammar_not_saved_policy(monkeypatch):
    """A real cold policy must be constructed, not mutate a saved-list copy.

    Both P7.2 and P7.5 call this same production APL generator. This checks
    the generator's actual object provenance, not just inequality of outputs.
    """
    import importlib.util
    from pathlib import Path

    path = (Path(__file__).resolve().parents[2] /
            "integrations/mythicsim-rust/apl_mutation.py")
    spec = importlib.util.spec_from_file_location("work1_apl_mutation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Ten genuine grammar terminals; every saved action has a condition.
    # An implementation that starts with deepcopy(saved_list) cannot pass
    # merely by shuffling or applying at most five later mutations.
    condition = {"cmp": {"lhs": {"remainingTime": {}}, "op": "OpGt",
                         "rhs": {"const": {"val": "2s"}}}}
    source = [
        {"action": {"castSpell": {"spellId": {"spellId": 100 + i}},
                    "condition": deepcopy(condition)}}
        for i in range(10)
    ]
    original = deepcopy(source)
    generated = []
    original_new_cast = module._new_cast

    def traced_new_cast(spells, predicates, rng):
        action = original_new_cast(spells, predicates, rng)
        generated.append(action)
        return action

    monkeypatch.setattr(module, "_new_cast", traced_new_cast)
    candidate = module.mutate_apl(None, source, random.Random(33), cold=True)
    cast_actions = [row for row in candidate
                    if "castSpell" in row.get("action", {})]
    generated_ids = {id(row) for row in generated}
    # Only the independently generated unconditional fallback may bypass
    # _new_cast. In particular, no original reference cast entry is copied.
    assert sum(id(row) not in generated_ids for row in cast_actions) <= 1
    assert any("condition" not in row["action"] for row in cast_actions)
    assert all(row["action"]["castSpell"]["spellId"]["spellId"] in range(100, 110)
               for row in cast_actions)
    assert source == original

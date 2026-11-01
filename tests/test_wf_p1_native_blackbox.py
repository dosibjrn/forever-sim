"""P1 source inventory/black-box native harness contracts.

Only schema tests may use miniature request objects. A passing test here
NEVER asserts native combat success without executing MythicSim Rust.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from tools.p1_native_source_inventory import inventory
from tools.wf_p1_native_effects import native_apl_pair, run_native

ROOT = Path(__file__).resolve().parents[1]


def _sample_request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "Hunter", "talentsString": "123",
            "equipment": {"items": [{"id": 42}]},
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 14282}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 13550}}}},
            ]},
        }]}]},
        "simOptions": {"iterations": 1, "randomSeed": "43123"},
        "encounter": {"duration": 12},
    }


def test_hunter_l20_source_inventory_no_gameir_and_no_false_pass():
    result = inventory("hunter", 20)
    assert result["source_only"] is True
    assert result["game_ir_required"] is False
    assert result["effects_tested"] == 0
    assert result["p1_certified"] is False
    assert result["candidate_count"] > 0
    # Auto Shot is already a native autoattack source, not a missing
    # player ActionDefinition.
    special = {x["spell_id"]: x["status"] for x in result["separate"]}
    assert special[75] == "NATIVE_AUTO_ATTACK"
    assert {14282, 13550} <= {x["spell_id"] for x in result["candidates"]}


@pytest.mark.parametrize("cls", ("druid", "hunter", "mage", "paladin", "priest",
                                   "rogue", "shaman", "warlock", "warrior"))
@pytest.mark.parametrize("level", (20, 60))
def test_class_level_p1_source_inventory_does_not_require_old_python_adapters(cls, level):
    result = inventory(cls, level)
    assert result["class"] == cls
    assert result["level"] == level
    assert result["candidate_count"] + result["separate_count"] > 0
    assert result["p1_certified"] is False


def test_native_apl_control_preserves_all_non_apl_request_content():
    req = _sample_request()
    reference = deepcopy(req)
    baseline, no_spell = native_apl_pair(req, 14282)
    assert req == reference and baseline == reference
    player = no_spell["raid"]["parties"][0]["players"][0]
    assert player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 13550}}}}
    ]
    player["rotation"]["priorityList"] = deepcopy(
        req["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"])
    assert no_spell == req


def test_native_missing_apl_spell_is_not_labeled_missing_engine_implementation():
    with pytest.raises(ValueError, match="SPELL_NOT_IN_SOURCE_NATIVE_APL"):
        native_apl_pair(_sample_request(), 1130)


def test_native_runner_rejects_missing_binary_without_fabricating_native_output():
    with pytest.raises(FileNotFoundError, match="PINNED_RUST_ENGINE_BINARY_MISSING"):
        run_native(ROOT/"nonexistent-forever-engine", _sample_request(),
                   class_key="hunter", level=20, spell_id=14282)


def test_source_only_nonimpact_never_becomes_an_effect_pass():
    result = inventory("druid", 20)
    rows = {x["name"]: x["status"] for x in result["separate"]}
    for name in ("Aquatic Form", "Growl", "Cure Poison", "Rebirth", "Revive"):
        assert rows[name] == "NOT_RELEVANT_TO_SIMULATION"
    assert result["p1_certified"] is False

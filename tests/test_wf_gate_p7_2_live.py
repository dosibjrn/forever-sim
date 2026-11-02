"""P7.2 cold APL mutation contract; no fake gate acceptance or saved-run PASS."""
import copy
import random
from types import SimpleNamespace

import pytest
from tools import wf_gate_p7_2_live as gate


def _request():
    return {
        "raid": {"parties": [{"players": [{
            "equipment": {"items": [{"id": 14}]},
            "talentsString": "source-legal",
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 2}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 3}}}},
            ]},
        }]}]}
    }


def test_cold_apl_keeps_actual_gear_talents_and_saved_request_unmodified():
    base = _request()
    original = copy.deepcopy(base)
    def mutation(actions, source_actions, rng, cold):
        assert actions is None and cold
        return list(reversed(source_actions))
    result = gate._cold_apl(base, random.Random(3),
                            SimpleNamespace(mutate_apl=mutation))
    assert result != base
    assert base == original
    assert result["raid"]["parties"][0]["players"][0]["equipment"] == (
        base["raid"]["parties"][0]["players"][0]["equipment"])
    assert result["raid"]["parties"][0]["players"][0]["talentsString"] == (
        base["raid"]["parties"][0]["players"][0]["talentsString"])


def test_identical_apl_is_not_called_independent_discovery():
    base = _request()
    with pytest.raises(ValueError, match="IDENTICAL_TO_REFERENCE"):
        gate._cold_apl(base, random.Random(3),
                       SimpleNamespace(mutate_apl=lambda a, s, r, cold: copy.deepcopy(s)))


def test_wrong_checkpoint_refuses_before_any_native_run(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_2_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]

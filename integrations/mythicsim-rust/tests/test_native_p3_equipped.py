"""Forever-owned request mutation and native outcome mapping (not game rules)."""
import copy
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from native_matrix import NativeCandidateRefusal
from native_p3_equipped import (compare_equipped_native, first_equipped_proposal,
                                prepared_native_actor)


def _reference():
    return {"raid": {"parties": [{"players": [{
        "class": "ClassRogue", "level": 20, "talentsString": "0-0-0",
        "rotation": {"type": "TypeAPL", "priorityList": []},
        "equipment": {"items": [{"id": 100 + index} for index in range(17)]},
    }]}]}, "encounter": {"duration": 30},
        "simOptions": {"iterations": 1, "randomSeed": "42"}}


def _prepared_actor(_binary, _reference):
    return {"status": "PREPARED", "actor_class": "ClassRogue",
            "actor_level": 20, "engine_revision": "selected-test-engine"}


def _selection():
    return {"chest": {"selected_ids": [104, 512, 513]},
            "head": {"selected_ids": [100]}}


def test_native_p3_mutates_only_native_sourced_equipment_slot():
    reference = _reference()
    original = copy.deepcopy(reference)
    candidate, swap = first_equipped_proposal(reference, _selection())
    assert reference == original
    assert swap == {"slot": "chest", "slot_index": 4, "from_id": 104,
                    "to_id": 512, "source": "SELECTED_NATIVE_P3_ITEM_OPTIONS"}
    player = candidate["raid"]["parties"][0]["players"][0]
    assert player["equipment"]["items"][4] == {"id": 512}
    player["equipment"]["items"][4] = {"id": 104}
    assert candidate == reference


def test_native_p3_pays_both_unmodified_baseline_and_equipped_with_identical_context():
    reference = _reference()
    original = copy.deepcopy(reference)
    calls = []

    def fake_native(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        calls.append(copy.deepcopy(request))
        gear = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        score = 104.0 if gear[4]["id"] == 512 else 100.0
        return score, {"result": {}}, 0.02, "request-sha-" + str(len(calls))

    receipt = compare_equipped_native("pinned-native", reference, _selection(),
                                      evaluator=fake_native, preparer=_prepared_actor)
    assert reference == original
    assert len(calls) == 2
    assert calls[0] == reference
    assert calls[1]["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"] == 512
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["paid_attempts"] == 2
    assert receipt["comparison"]["delta_dps"] == 4.0
    assert receipt["evaluations"][0]["status"] == "VALID"
    assert receipt["evaluations"][1]["status"] == "VALID"
    assert receipt["actor_checkpoint_verified"] is True
    assert receipt["native_prepared_actor"]["actor_level"] == 20


def test_native_p3_preserves_native_refusal_and_does_not_fake_delta():
    def refusal(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        if item == 512:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="engine says unsupported",
                request_sha256="refused-sha", raw_response={"status": "UNSUPPORTED"})
        return 100.0, {}, 0.01, "baseline-sha"

    receipt = compare_equipped_native("pinned-native", _reference(), _selection(),
                                      evaluator=refusal, preparer=_prepared_actor)
    assert receipt["status"] == "PAID_NATIVE_REFUSAL"
    assert receipt["paid_attempts"] == 2
    assert receipt["evaluations"][1]["status"] == "UNSUPPORTED"
    assert receipt["evaluations"][1]["request_sha256"] == "refused-sha"
    assert receipt["comparison"] is None


def test_native_p3_does_not_pay_if_no_distinct_native_item():
    receipt = compare_equipped_native("pinned-native", _reference(),
                                      {"head": {"selected_ids": [100]}},
                                      evaluator=lambda *a, **k: pytest.fail("No native invocation expected"))
    assert receipt["paid_attempts"] == 0
    assert receipt["status"] == "NO_DISTINCT_NATIVE_EQUIPPED_ALTERNATIVE"


def test_native_p3_rejects_non_rogue_reference_without_paying():
    reference = _reference()
    reference["raid"]["parties"][0]["players"][0]["class"] = "ClassWarrior"
    with pytest.raises(ValueError, match="CLASS_MISMATCH"):
        compare_equipped_native("pinned-native", reference, _selection())


def test_native_p3_prioritizes_native_sourced_weapon_over_armor():
    reference = _reference()
    selection = {"head": {"selected_ids": [900]},
                 "weapon": {"selected_ids": [950]}}
    candidate, swap = first_equipped_proposal(reference, selection)
    assert swap["slot"] == "weapon"
    assert swap["slot_index"] == 14
    assert swap["to_id"] == 950
    assert candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][14] == {"id": 950}
    assert candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] == {"id": 100}


@pytest.mark.parametrize("slot,index", [
    ("weapon", 14), ("offhand", 15), ("ranged", 16),
    ("ring1", 10), ("ring2", 11),
    ("trinket1", 12), ("trinket2", 13),
])
def test_native_p3_accepts_native_equipment_positions(slot, index):
    candidate, swap = first_equipped_proposal(
        _reference(), {slot: {"selected_ids": [2000]}})
    assert (swap["slot"], swap["slot_index"], swap["to_id"]) == (slot, index, 2000)
    equipment = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    assert equipment[index] == {"id": 2000}
    assert all(entry["id"] == 100 + i for i, entry in enumerate(equipment)
               if i != index)


def test_native_p3_skips_missing_ranged_slot_in_16_entry_request():
    reference = _reference()
    reference["raid"]["parties"][0]["players"][0]["equipment"]["items"].pop()
    candidate, swap = first_equipped_proposal(
        reference, {"ranged": {"selected_ids": [999]},
                    "chest": {"selected_ids": [812]}})
    assert swap["slot"] == "chest"
    assert candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][4] == {"id": 812}


def test_native_p3_rejects_request_without_explicit_l20_before_paying():
    reference = _reference()
    reference["raid"]["parties"][0]["players"][0]["level"] = 60
    receipt = compare_equipped_native(
        "pinned-native", reference, _selection(),
        preparer=lambda *a: pytest.fail("Must not prepare L60 request"),
        evaluator=lambda *a, **k: pytest.fail("Must not score L60 request"))
    assert receipt["status"] == "NATIVE_L20_SOURCE_REQUEST_REQUIRED"
    assert receipt["paid_attempts"] == 0


def test_native_p3_refuses_prepared_l60_actor_without_spending_paid_budget():
    receipt = compare_equipped_native(
        "pinned-native", _reference(), _selection(),
        preparer=lambda *a: {"status": "PREPARED",
                              "actor_class": "ClassRogue", "actor_level": 60},
        evaluator=lambda *a, **k: pytest.fail("Must not score L60 actor"))
    assert receipt["status"] == "NATIVE_ACTOR_CHECKPOINT_MISMATCH"
    assert receipt["native_prepared_actor"]["actor_level"] == 60
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False


def test_native_p3_preserves_prepare_refusal_without_paid_attempts():
    receipt = compare_equipped_native(
        "pinned-native", _reference(), _selection(),
        preparer=lambda *a: {"status": "NATIVE_PREPARE_REFUSED",
                              "reason": "talents"},
        evaluator=lambda *a, **k: pytest.fail("Must not score refused actor"))
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED"
    assert receipt["reason"] == "talents"
    assert receipt["paid_attempts"] == 0


def test_native_p3_reads_actual_prepared_actor_from_selected_binary():
    calls = []
    class Completed:
        returncode = 0
        stdout = json.dumps({"player": {"class": "ClassRogue", "level": 60},
                             "reference": {"engine_revision": "native-sha"},
                             "request_sha256": "source-proto-sha"})
        stderr = ""
    def fake_runner(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is False
        return Completed()
    actor = prepared_native_actor("pinned-native", _reference(),
                                  runner=fake_runner)
    assert calls[0][1:3] == ["prepare", "--request"]
    assert actor == {"status": "PREPARED", "actor_class": "ClassRogue",
                     "actor_level": 60, "engine_revision": "native-sha",
                     "prepared_request_sha256": "source-proto-sha"}

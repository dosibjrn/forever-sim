"""Forever-owned request mutation and native outcome mapping (not game rules)."""
import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from native_matrix import NativeCandidateRefusal
from native_p3_equipped import compare_equipped_native, first_equipped_proposal


def _reference():
    return {"raid": {"parties": [{"players": [{
        "class": "ClassRogue", "talentsString": "0-0-0",
        "rotation": {"type": "TypeAPL", "priorityList": []},
        "equipment": {"items": [{"id": 100 + index} for index in range(17)]},
    }]}]}, "encounter": {"duration": 30},
        "simOptions": {"iterations": 1, "randomSeed": "42"}}


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
                                      evaluator=fake_native)
    assert reference == original
    assert len(calls) == 2
    assert calls[0] == reference
    assert calls[1]["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"] == 512
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["paid_attempts"] == 2
    assert receipt["comparison"]["delta_dps"] == 4.0
    assert receipt["evaluations"][0]["status"] == "VALID"
    assert receipt["evaluations"][1]["status"] == "VALID"
    assert receipt["actor_checkpoint_verified"] is False


def test_native_p3_preserves_native_refusal_and_does_not_fake_delta():
    def refusal(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        if item == 512:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="engine says unsupported",
                request_sha256="refused-sha", raw_response={"status": "UNSUPPORTED"})
        return 100.0, {}, 0.01, "baseline-sha"

    receipt = compare_equipped_native("pinned-native", _reference(), _selection(),
                                      evaluator=refusal)
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

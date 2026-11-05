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
    assert receipt["actor_requested_level"] == 20
    assert receipt["native_prepared_actor"]["actor_level"] == 20
    assert receipt["promotion"] == "MATCHED_ROGUE_L20_NATIVE_SCORED_DIFFERENCE"


@pytest.mark.parametrize("level", [None, 60, "20", True])
def test_native_p3_rejects_unmatched_rogue_source_without_paid_execution(level):
    reference = _reference()
    if level is None:
        del reference["raid"]["parties"][0]["players"][0]["level"]
    else:
        reference["raid"]["parties"][0]["players"][0]["level"] = level

    def should_not_evaluate(*args, **kwargs):
        pytest.fail("Unmatched source must never consume native paid attempts")

    result = compare_equipped_native(
        "pinned-native", reference, _selection(), evaluator=should_not_evaluate)
    assert result["status"] == "NATIVE_REQUEST_CHECKPOINT_MISMATCH"
    assert result["paid_attempts"] == 0
    assert result["comparison"] is None
    assert result["actor_checkpoint_verified"] is False
    assert result["promotion"] == "NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_L20_ACTOR"


def test_native_p3_preserves_native_refusal_and_does_not_fake_delta():
    def refusal(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        if item in (512, 513):
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="engine says unsupported",
                request_sha256="refused-sha", raw_response={"status": "UNSUPPORTED"})
        return 100.0, {}, 0.01, "baseline-sha"

    receipt = compare_equipped_native("pinned-native", _reference(), _selection(),
                                      evaluator=refusal, preparer=_prepared_actor,
                                      max_paid_attempts=3)
    assert receipt["status"] == "PAID_NATIVE_REFUSAL"
    # The first native ID is the already-equipped chest item (104). Both
    # distinct Rust alternatives must be attempted, not just the first.
    assert receipt["paid_attempts"] == 3
    assert [row["swap"]["to_id"] for row in receipt["native_slot_evaluations"]] == [512, 513]
    assert [row["status"] for row in receipt["native_slot_evaluations"]] == ["UNSUPPORTED", "UNSUPPORTED"]
    assert receipt["evaluations"][1]["request_sha256"] == "refused-sha"
    assert receipt["comparison"] is None
    assert receipt["actor_checkpoint_verified"] is False


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


def test_native_p3_uses_prepared_actor_not_request_level_for_paid_decision():
    """An L20 request backed by an L60 actor must never earn P3 credit."""
    receipt = compare_equipped_native(
        "pinned-native", _reference(), _selection(),
        preparer=lambda *_: {"status": "PREPARED",
                             "actor_class": "ClassRogue", "actor_level": 60},
        evaluator=lambda *a, **k: pytest.fail("Must not score a native L60 proxy"))
    assert receipt["status"] == "NATIVE_ACTOR_CHECKPOINT_MISMATCH"
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False
    assert receipt["native_prepared_actor"]["actor_level"] == 60


def test_native_p3_propagates_selected_prepare_refusal_without_paid_attempts():
    receipt = compare_equipped_native(
        "pinned-native", _reference(), _selection(),
        preparer=lambda *_: {"status": "NATIVE_PREPARE_REFUSED",
                             "reason": "source native actor unavailable"},
        evaluator=lambda *a, **k: pytest.fail("Must not score refused native actor"))
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED"
    assert receipt["reason"] == "source native actor unavailable"
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False


def test_native_p3_reads_prepared_actor_from_the_selected_binary():
    calls = []

    class Completed:
        returncode = 0
        stdout = json.dumps({"player": {"class": "ClassRogue", "level": 60},
                             "reference": {"engine_revision": "native-sha"},
                             "request_sha256": "source-sha"})
        stderr = ""

    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is False
        return Completed()

    actor = prepared_native_actor("pinned-native", _reference(), runner=runner)
    assert calls[0][1:3] == ["prepare", "--request"]
    assert actor == {"status": "PREPARED", "actor_class": "ClassRogue",
                     "actor_level": 60, "engine_revision": "native-sha",
                     "prepared_request_sha256": "source-sha"}


def test_p3_cli_retains_selected_native_prepare_reason_and_actor(monkeypatch, capsys):
    """A P3 FAIL must tell the next worker why Rust refused L20 preparation."""
    from tools import wf_gate

    def gate(*_args, **_kwargs):
        return {
            "status": "FAIL", "reasons": ["P3_NATIVE_L20_EQUIPPED_SCORE_NOT_ESTABLISHED"],
            "native_equipped_paid_receipt": {
                "status": "NATIVE_PREPARE_REFUSED",
                "reason": "player level 20 is unsupported by selected native",
                "paid_attempts": 0,
                "actor_requested_level": 20,
                "actor_checkpoint_verified": False,
                "native_prepared_actor": {"status": "NATIVE_PREPARE_REFUSED",
                                          "reason": "source native refusal"},
            },
        }

    monkeypatch.setattr(wf_gate, "_run_live_gate", gate)
    result = wf_gate.main(["--class", "rogue", "--level", "20",
                           "--spec", "unrestricted", "--gate", "P3"])
    assert result == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FAIL"
    receipt = output["results"][0]["native_equipped_paid_receipt"]
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED"
    assert "player level 20 is unsupported" in receipt["reason"]
    assert receipt["actor_requested_level"] == 20
    assert receipt["native_prepared_actor"]["reason"] == "source native refusal"
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False

def test_native_p3_sweeps_distinct_slots_against_one_shared_baseline():
    """Additional native alternatives are actually paid, not Python weights."""
    reference = _reference()
    original = copy.deepcopy(reference)
    seen = []

    def native(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        assert rng_mode == "balanced"
        assert iterations == 5 and seed == 914
        equipment = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        ids = [item["id"] for item in equipment]
        seen.append(ids)
        changed = [i for i, item_id in enumerate(ids) if item_id != 100 + i]
        assert len(changed) <= 1
        return (100.0 if not changed else 100.0 + changed[0]), {}, 0.01, str(len(seen))

    receipt = compare_equipped_native(
        "pinned-native", reference,
        {"weapon": {"selected_ids": [900]},
         "head": {"selected_ids": [901]},
         "chest": {"selected_ids": [902]}},
        evaluator=native, preparer=_prepared_actor, max_paid_attempts=4)
    assert reference == original
    assert len(seen) == 4
    assert seen[0] == [100 + i for i in range(17)]
    assert [row["swap"]["slot"] for row in receipt["native_slot_evaluations"]] == [
        "weapon", "head", "chest"]
    assert receipt["paid_attempts"] == 4
    assert receipt["native_slots_paid"] == 3
    assert receipt["native_slots_valid"] == 3
    assert receipt["native_slot_evaluations"][1]["delta_dps"] == 0.0
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["actor_checkpoint_verified"] is True


def test_native_p3_slot_sweep_preserves_refusal_without_inventing_a_score():
    def native(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        if items[0]["id"] == 901:
            raise NativeCandidateRefusal(
                "INVALID", reason="native rejected item",
                request_sha256="invalid-native-sha", raw_response={})
        return (110.0 if items[14]["id"] == 900 else 100.0), {}, 0.01, "valid-sha"

    receipt = compare_equipped_native(
        "pinned-native", _reference(),
        {"weapon": {"selected_ids": [900]}, "head": {"selected_ids": [901]}},
        evaluator=native, preparer=_prepared_actor, max_paid_attempts=3)
    assert receipt["paid_attempts"] == 3
    assert receipt["native_slot_evaluations"][1]["status"] == "INVALID"
    assert receipt["native_slot_evaluations"][1]["delta_dps"] is None
    assert receipt["evaluations"][2]["request_sha256"] == "invalid-native-sha"
    assert receipt["native_slots_valid"] == 1
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"


@pytest.mark.parametrize("cap", [0, 1, 45, True, 2.0])
def test_native_p3_rejects_invalid_shared_attempt_cap(cap):
    with pytest.raises(ValueError, match="BUDGET_INVALID"):
        compare_equipped_native(
            "pinned-native", _reference(), _selection(),
            max_paid_attempts=cap,
            evaluator=lambda *a, **k: pytest.fail("Must not evaluate"))

def test_p3_cli_exposes_actual_native_slot_paid_results(monkeypatch, capsys):
    from tools import wf_gate

    def gate(*_args, **_kwargs):
        return {
            "status": "FAIL", "reasons": ["MISSING_WEIGHT:strength"],
            "native_equipped_paid_receipt": {
                "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 3,
                "actor_checkpoint_verified": True,
                "native_slots_paid": 2, "native_slots_valid": 1,
                "native_slot_attempt_cap": 18,
                "native_slot_evaluations": [
                    {"swap": {"slot": "weapon", "to_id": 24071},
                     "status": "VALID", "score": 33.0, "delta_dps": 29.0},
                    {"swap": {"slot": "head", "to_id": 1234},
                     "status": "UNSUPPORTED", "score": None, "delta_dps": None},
                ],
            },
        }

    monkeypatch.setattr(wf_gate, "_run_live_gate", gate)
    assert wf_gate.main(["--class", "rogue", "--level", "20",
                         "--spec", "unrestricted", "--gate", "P3"]) == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    receipt = row["native_equipped_paid_receipt"]
    assert receipt["native_slots_paid"] == 2
    assert receipt["native_slots_valid"] == 1
    assert receipt["native_slot_attempt_cap"] == 18
    assert receipt["native_slot_evaluations"][1]["status"] == "UNSUPPORTED"
    assert receipt["native_slot_evaluations"][1]["delta_dps"] is None


def test_native_p3_uses_second_rust_option_after_first_refusal():
    paid = []
    def scorer(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        assert rng_mode == "balanced"
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        paid.append(item)
        if item == 512:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="native rating unavailable",
                request_sha256="refusal-sha", raw_response={})
        return (120.0 if item == 513 else 100.0), {}, 0.01, "sha-" + str(item)
    receipt = compare_equipped_native(
        "native", _reference(), {"chest": {"selected_ids": [512, 513]}},
        evaluator=scorer, preparer=_prepared_actor, max_paid_attempts=3)
    assert paid == [104, 512, 513]
    assert receipt["paid_attempts"] == 3
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["comparison"]["delta_dps"] == 20.0
    assert receipt["swap"]["to_id"] == 513
    assert receipt["native_slots_verified"] == 1
    assert receipt["native_slots_unscored"] == []
    assert receipt["native_slot_evaluations"][0]["status"] == "UNSUPPORTED"
    assert receipt["native_slot_evaluations"][0]["reason"] == "native rating unavailable"


def test_native_p3_refusal_does_not_bypass_attempt_cap():
    def scorer(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        if item == 512:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="native refusal",
                request_sha256="refusal-sha", raw_response={})
        return 100.0, {}, 0.01, "baseline-sha"
    receipt = compare_equipped_native(
        "native", _reference(), {"chest": {"selected_ids": [512, 513]}},
        evaluator=scorer, preparer=_prepared_actor, max_paid_attempts=2)
    assert receipt["paid_attempts"] == 2
    assert receipt["native_slots_verified"] == 0
    assert receipt["native_slots_unscored"] == ["chest"]
    assert receipt["status"] == "PAID_NATIVE_REFUSAL"

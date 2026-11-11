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


def test_native_p3_third_native_candidate_after_two_source_refusals():
    """Two refused L20 chest swaps must not hide a third Rust-supplied item."""
    paid = []

    def scorer(_binary, request, _iterations, _seed, mode, _deadline, **_kwargs):
        assert mode == "balanced"
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        paid.append(item)
        if item in (512, 513):
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="native L20 rating conversion unavailable",
                request_sha256=f"native-refused-{item}", raw_response={})
        return (115.0 if item == 514 else 100.0), {}, 0.01, f"native-paid-{item}"

    receipt = compare_equipped_native(
        "native", _reference(), {"chest": {"selected_ids": [104, 512, 513, 514]}},
        evaluator=scorer, preparer=_prepared_actor, max_paid_attempts=4)
    assert paid == [104, 512, 513, 514]
    assert receipt["paid_attempts"] == 4
    assert [row["status"] for row in receipt["native_slot_evaluations"]] == [
        "UNSUPPORTED", "UNSUPPORTED", "VALID"]
    assert receipt["native_slots_verified"] == 1
    assert receipt["native_slots_unscored"] == []
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["comparison"]["delta_dps"] == 15.0
    assert receipt["swap"]["to_id"] == 514


def test_native_p3_third_candidate_not_paid_after_finite_equal_slot_scores():
    """Native equal scores are real; do not pay for an unnecessary fallback."""
    paid = []

    def scorer(_binary, request, _iterations, _seed, _mode, _deadline, **_kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        paid.append(item)
        return 100.0, {}, 0.01, f"native-paid-{item}"

    receipt = compare_equipped_native(
        "native", _reference(), {"chest": {"selected_ids": [512, 513, 514]}},
        evaluator=scorer, preparer=_prepared_actor, max_paid_attempts=4)
    assert paid == [104, 512, 513]
    assert receipt["paid_attempts"] == 3
    assert receipt["native_slots_verified"] == 1
    assert receipt["status"] == "PAID_NATIVE_EQUAL"


def test_native_p3_third_candidate_still_obeys_shared_paid_cap():
    """A true native refusal remains visible when the shared budget runs out."""
    paid = []

    def scorer(_binary, request, _iterations, _seed, _mode, _deadline, **_kwargs):
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]["id"]
        paid.append(item)
        if item != 104:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", reason="native refuses", request_sha256="refused")
        return 100.0, {}, 0.01, "baseline"

    receipt = compare_equipped_native(
        "native", _reference(), {"chest": {"selected_ids": [512, 513, 514]}},
        evaluator=scorer, preparer=_prepared_actor, max_paid_attempts=3)
    assert paid == [104, 512, 513]
    assert receipt["paid_attempts"] == 3
    assert receipt["native_slots_unscored"] == ["chest"]
    assert receipt["status"] == "PAID_NATIVE_REFUSAL"


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


def test_feral_l60_native_equipped_uses_prepared_actor_and_go_reference_rules():
    """The saved source omits level; only native prepare can verify level 60."""
    reference = _reference()
    player = reference["raid"]["parties"][0]["players"][0]
    player["class"] = "ClassDruid"
    del player["level"]
    player["equipment"]["items"].pop()  # Real saved Feral request has 16 entries.
    unchanged = copy.deepcopy(reference)
    seen = []

    def prepare(_binary, request, *, go_rules):
        assert go_rules is True
        assert request == unchanged
        return {"status": "PREPARED", "actor_class": "ClassDruid",
                "actor_level": 60, "engine_revision": "selected-feral"}

    def score(_binary, request, _iterations, _seed, mode, _deadline, **kwargs):
        assert kwargs == {"objective": "DPS", "go_rules": True}
        assert mode == "balanced"
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        seen.append(item)
        return (100.0 if item == 114 else 120.0), {}, 0.01, "sha-" + str(item)

    receipt = compare_equipped_native(
        "selected", reference, {"weapon": {"selected_ids": [900]}},
        class_key="druid", level=60, go_rules=True,
        evaluator=score, preparer=prepare)
    assert reference == unchanged
    assert seen == [114, 900]
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["actor_checkpoint_verified"] is True
    assert receipt["native_prepared_actor"]["actor_level"] == 60
    assert receipt["comparison"]["delta_dps"] == 20.0


def test_feral_l60_refuses_wrong_prepared_actor_without_paid_scoring():
    reference = _reference()
    player = reference["raid"]["parties"][0]["players"][0]
    player["class"] = "ClassDruid"
    del player["level"]
    result = compare_equipped_native(
        "selected", reference, {"weapon": {"selected_ids": [900]}},
        class_key="druid", level=60, go_rules=True,
        preparer=lambda *_args, **_kwargs: {
            "status": "PREPARED", "actor_class": "ClassDruid", "actor_level": 40},
        evaluator=lambda *_args, **_kwargs: pytest.fail("No paid wrong-level sim"))
    assert result["status"] == "NATIVE_ACTOR_CHECKPOINT_MISMATCH"
    assert result["paid_attempts"] == 0


def test_feral_native_prepare_forwards_go_rules_to_selected_binary():
    reference = _reference()
    calls = []

    class Completed:
        returncode = 0
        stdout = json.dumps({"player": {"class": "ClassDruid", "level": 60},
                             "reference": {"engine_revision": "selected"},
                             "request_sha256": "source"})
        stderr = ""

    def runner(command, **_kwargs):
        calls.append(command)
        return Completed()

    actor = prepared_native_actor("selected", reference, runner=runner, go_rules=True)
    assert calls[0][-1] == "--go-rules"
    assert actor["actor_class"] == "ClassDruid"
    assert actor["actor_level"] == 60


def test_native_executor_forwards_go_rules_and_preserves_real_refusal(monkeypatch):
    import time
    from native_executor import run

    calls = []

    class Refused:
        returncode = 3
        stdout = json.dumps({"supported": False, "reasons": ["native refusal"]})
        stderr = ""

    def runner(command, **_kwargs):
        calls.append(command)
        return Refused()

    monkeypatch.setattr("native_executor.subprocess.run", runner)
    with pytest.raises(NativeCandidateRefusal, match="native refusal"):
        run("selected", _reference(), 5, 914, "balanced",
            time.monotonic() + 30, go_rules=True)
    assert calls[0][-1] == "--go-rules"
    assert "--rng-mode" in calls[0]


def test_naked_rogue_l20_source_seeds_two_distinct_native_item_options():
    """Only Rust-proposed IDs seed the paid baseline, never a Python gear model."""
    reference = _reference()
    original = copy.deepcopy(reference)
    for entry in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        entry["id"] = 0
    original = copy.deepcopy(reference)
    calls = []

    def source_native(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        calls.append(copy.deepcopy(request))
        assert iterations == 5 and rng_mode == "balanced"
        assert items[14]["id"] in (410, 411)
        return (12.0 if items[14]["id"] == 410 else 15.0), {}, 0.01, (
            "paid-native-" + str(len(calls)))

    receipt = compare_equipped_native(
        "selected-native", reference,
        {"weapon": {"selected_ids": [410, 410, 411]}},
        evaluator=source_native, preparer=_prepared_actor,
        max_paid_attempts=2)
    assert reference == original
    assert len(calls) == 2
    assert [request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
            for request in calls] == [410, 411]
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["paid_attempts"] == 2
    assert receipt["actor_checkpoint_verified"] is True
    assert receipt["native_source_seed"] == {
        "slot": "weapon", "item_id": 410,
        "source": "SELECTED_NATIVE_P3_ITEM_OPTIONS",
        "original_reference_naked": True,
    }
    assert receipt["source_occupied_slots"] == ["weapon"]
    assert receipt["comparison"]["delta_dps"] == 3.0


def test_naked_rogue_builds_multi_slot_baseline_from_native_prepared_options():
    """Rust prepare must approve each new occupied slot before paid comparison."""
    reference = _reference()
    for item in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        item["id"] = 0
    original = copy.deepcopy(reference)
    prepared_ids = []
    paid_gear = []

    def native_prepare(_binary, request):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        prepared_ids.append((items[14]["id"], items[4]["id"]))
        if items[4]["id"] == 700:
            return {"status": "NATIVE_PREPARE_REFUSED",
                    "reason": "native chest 700 not executable"}
        return _prepared_actor(_binary, request)

    def native_paid(_binary, request, _iterations, _seed, rng, _deadline, **kwargs):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        paid_gear.append((items[14]["id"], items[4]["id"]))
        assert rng == "balanced"
        return (float(items[14]["id"]) + items[4]["id"] / 100.0,
                {}, 0.01, "genuine-native-" + str(len(paid_gear)))

    receipt = compare_equipped_native(
        "selected-native", reference,
        {"weapon": {"selected_ids": [410, 411]},
         "chest": {"selected_ids": [700, 701, 702]}},
        preparer=native_prepare, evaluator=native_paid, max_paid_attempts=4)
    assert reference == original
    assert prepared_ids == [(410, 0), (410, 700), (410, 701)]
    assert paid_gear == [(410, 701), (411, 701), (410, 702)]
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["paid_attempts"] == 3
    assert receipt["actor_checkpoint_verified"] is True
    assert receipt["source_occupied_slots"] == ["weapon", "chest"]
    assert receipt["native_slots_verified"] == 2
    assert receipt["native_slots_unscored"] == []
    assert receipt["native_source_additional_seeds"] == [{
        "slot": "chest", "item_id": 701,
        "source": "SELECTED_NATIVE_P3_ITEM_OPTIONS",
        "refused_prepares": [{
            "item_id": 700, "status": "NATIVE_PREPARE_REFUSED",
            "reason": "native chest 700 not executable"}]}]
    assert receipt["native_source_unseeded_slots"] == []


def test_naked_rogue_preserves_unprepared_source_slot_without_paid_coverage():
    reference = _reference()
    for item in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        item["id"] = 0
    paid_ids = []

    def native_prepare(_binary, request):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        if items[4]["id"]:
            return {"status": "NATIVE_PREPARE_REFUSED",
                    "reason": "source-native chest rejected"}
        return _prepared_actor(_binary, request)

    def native_paid(_binary, request, *_args, **_kwargs):
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        paid_ids.append((items[14]["id"], items[4]["id"]))
        return float(items[14]["id"]), {}, 0.01, "paid-native"

    receipt = compare_equipped_native(
        "selected-native", reference,
        {"weapon": {"selected_ids": [410, 411]},
         "chest": {"selected_ids": [700, 701]}},
        preparer=native_prepare, evaluator=native_paid, max_paid_attempts=3)
    assert paid_ids == [(410, 0), (411, 0)]
    assert receipt["source_occupied_slots"] == ["weapon"]
    assert receipt["native_slots_verified"] == 1
    assert receipt["native_source_additional_seeds"] == []
    assert receipt["native_source_unseeded_slots"] == [{
        "slot": "chest", "refused_prepares": [{
            "item_id": 700, "status": "NATIVE_PREPARE_REFUSED",
            "reason": "source-native chest rejected"}]}]


def test_naked_rogue_source_without_two_native_options_never_pays():
    reference = _reference()
    for entry in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        entry["id"] = 0
    receipt = compare_equipped_native(
        "selected-native", reference, {"weapon": {"selected_ids": [410, 410]}},
        evaluator=lambda *a, **k: pytest.fail("no independent native pair"))
    assert receipt["status"] == "NO_DISTINCT_NATIVE_EQUIPPED_ALTERNATIVE"
    assert receipt["paid_attempts"] == 0


def test_native_seed_refusal_is_not_promoted_to_paid_evidence():
    reference = _reference()
    for entry in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        entry["id"] = 0
    receipt = compare_equipped_native(
        "selected-native", reference, {"weapon": {"selected_ids": [410, 411]}},
        preparer=lambda *_args: {
            "status": "NATIVE_PREPARE_REFUSED", "reason": "native item refused"},
        evaluator=lambda *a, **k: pytest.fail("native refusal cannot be paid"))
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED"
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False


def test_naked_rogue_prepares_next_source_seed_after_native_item_refusal():
    """A refused first source item does not strand a genuinely paid Rogue pair."""
    reference = _reference()
    for item in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        item["id"] = 0
    original = copy.deepcopy(reference)
    prepared_ids = []
    paid_ids = []

    def prepare(_binary, request):
        item_id = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        prepared_ids.append(item_id)
        if item_id == 410:
            return {"status": "NATIVE_PREPARE_REFUSED", "reason": "source item 410 refused"}
        return _prepared_actor(_binary, request)

    def paid(_binary, request, _iters, _seed, _rng, _deadline, **_kwargs):
        item_id = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        paid_ids.append(item_id)
        assert item_id in (411, 412)
        return float(item_id), {}, 0.01, f"native-paid-{item_id}"

    receipt = compare_equipped_native(
        "selected-native", reference, {"weapon": {"selected_ids": [410, 411, 412]}},
        preparer=prepare, evaluator=paid, max_paid_attempts=2)
    assert reference == original
    assert prepared_ids == [410, 411]
    assert paid_ids == [411, 412]
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["paid_attempts"] == 2
    assert receipt["actor_checkpoint_verified"] is True
    assert receipt["comparison"]["delta_dps"] == 1.0
    assert receipt["native_source_seed"]["item_id"] == 411
    assert receipt["native_source_seed"]["refused_prepares"] == [{
        "item_id": 410, "status": "NATIVE_PREPARE_REFUSED",
        "reason": "source item 410 refused"}]


def test_naked_rogue_refused_source_seeds_preserve_no_paid_provenance():
    reference = _reference()
    for item in reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]:
        item["id"] = 0
    seen = []

    def prepare(_binary, request):
        item_id = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        seen.append(item_id)
        return {"status": "NATIVE_PREPARE_REFUSED", "reason": f"item {item_id} rejected"}

    receipt = compare_equipped_native(
        "selected-native", reference, {"weapon": {"selected_ids": [410, 411, 412]}},
        preparer=prepare,
        evaluator=lambda *a, **k: pytest.fail("No refused actor may be scored"),
        max_paid_attempts=2)
    # No third baseline: 412 is held for a distinct paid alternative.
    assert seen == [410, 411]
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED"
    assert receipt["paid_attempts"] == 0
    assert receipt["actor_checkpoint_verified"] is False
    assert receipt["native_source_seed"]["refused_prepares"] == [
        {"item_id": 410, "status": "NATIVE_PREPARE_REFUSED",
         "reason": "item 410 rejected"},
        {"item_id": 411, "status": "NATIVE_PREPARE_REFUSED",
         "reason": "item 411 rejected"},
    ]

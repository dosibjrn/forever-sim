"""Selected-native L20 source equipment construction, without Python gear legality."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from tools.wf_native_warlock_l20_equipped import (
    NativeWarlockEquippedError, build_warlock_equipped_request)


def source():
    return {
        "raid": {"parties": [{"players": [{
            "name": "native-troll", "class": "ClassWarlock", "race": "RaceTroll",
            "talentsString": "0-0-0", "equipment": {"items": []},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1088}}}}]},
        }]}]},
        "encounter": {"duration": 12, "targets": [{"level": 20}]},
        "simOptions": {"iterations": 1, "randomSeed": "42"},
    }


def options():
    return {"status": "ok", "source_revision": "pinned-rust",
            "items": [
                {"item_id": 901, "slot": "one_hand", "item_level": 20},
                {"item_id": 902, "slot": "one_hand", "item_level": 19},
                {"item_id": 1001, "slot": "ranged", "item_level": 20},
                {"item_id": 1002, "slot": "ranged", "item_level": 18},
                {"item_id": 1101, "slot": "chest", "item_level": 20},
                {"item_id": 1102, "slot": "chest", "item_level": 17},
            ]}


def player(request):
    return request["raid"]["parties"][0]["players"][0]


def test_rust_probes_construct_equipped_troll_l20_without_mutating_source():
    baseline = source()
    unchanged = copy.deepcopy(baseline)
    seen = []

    def rust_preparer(binary, candidate, *, actor_level):
        assert binary == "pinned-binary" and actor_level == 20
        assert player(candidate)["race"] == "RaceTroll"
        assert player(candidate)["rotation"] == player(baseline)["rotation"]
        ids = [row["id"] for row in player(candidate)["equipment"]["items"]]
        seen.append(ids)
        if 901 in ids:
            return {"status": "NATIVE_PREPARE_REFUSED", "reason": "source native refusal"}
        return {"status": "PREPARED", "actor_class": "ClassWarlock",
                "actor_level": 20, "engine_revision": "tested-engine"}

    candidate, receipt = build_warlock_equipped_request(
        "pinned-binary", baseline, options(), preparer=rust_preparer)
    equipped = player(candidate)["equipment"]["items"]
    assert len(equipped) == 17
    assert equipped[14]["id"] == 902  # second Rust weapon after genuine refusal
    assert equipped[16]["id"] == 1001  # native ranged (wand) position
    assert equipped[4]["id"] == 1101
    assert len(seen) == receipt["native_prepare_attempts"] == 4
    assert receipt["paid_p3_attempts"] == 0  # gate's 44 paid calls stay separate
    assert receipt["native_prepare_refusals"] == [
        {"slot": "weapon", "item_id": 901,
         "status": "NATIVE_PREPARE_REFUSED", "reason": "source native refusal"}]
    assert baseline == unchanged
    assert player(candidate)["talentsString"] == "0-0-0"
    assert player(candidate)["rotation"]["priorityList"][0]["action"]["castSpell"][
        "spellId"]["spellId"] == 1088


def test_native_wrong_level_is_not_pretended_to_be_l20():
    def wrong_actor(_binary, _candidate, *, actor_level):
        assert actor_level == 20
        return {"status": "PREPARED", "actor_class": "ClassWarlock",
                "actor_level": 60}

    with pytest.raises(NativeWarlockEquippedError,
                       match="WARLOCK_L20_NO_NATIVE_PREPARED_EQUIPMENT"):
        build_warlock_equipped_request(
            "selected-engine", source(), options(), preparer=wrong_actor)


def test_source_race_and_level_must_be_the_real_troll_l20_fixture():
    baseline = source()
    player(baseline)["race"] = "RaceOrc"
    with pytest.raises(NativeWarlockEquippedError, match="SOURCE_ACTOR_MISMATCH"):
        build_warlock_equipped_request(
            "selected", baseline, options(),
            preparer=lambda *_args, **_kwargs: pytest.fail("no native request"))
    player(baseline)["race"] = "RaceTroll"
    player(baseline)["level"] = 60
    with pytest.raises(NativeWarlockEquippedError, match="SOURCE_ACTOR_MISMATCH"):
        build_warlock_equipped_request(
            "selected", baseline, options(),
            preparer=lambda *_args, **_kwargs: pytest.fail("no native request"))


def test_source_preexisting_native_equipment_is_preserved():
    baseline = source()
    player(baseline)["equipment"]["items"] = [{"id": 0} for _ in range(17)]
    player(baseline)["equipment"]["items"][14] = {"id": 1234}
    seen = []

    def rust_preparer(_binary, candidate, *, actor_level):
        seen.append([row["id"] for row in player(candidate)["equipment"]["items"]])
        return {"status": "PREPARED", "actor_class": "ClassWarlock",
                "actor_level": actor_level}

    candidate, receipt = build_warlock_equipped_request(
        "selected", baseline, options(), preparer=rust_preparer)
    assert player(candidate)["equipment"]["items"][14]["id"] == 1234
    assert any(x["from_source_fixture"] and x["item_id"] == 1234
               for x in receipt["occupied_slots"])
    assert all(row[14] == 1234 for row in seen)


def test_no_item_options_is_explicit_refusal_not_empty_p3_success():
    with pytest.raises(NativeWarlockEquippedError, match="SOURCE_ITEM_OPTIONS_EMPTY"):
        build_warlock_equipped_request(
            "selected", source(), {"status": "empty", "items": []},
            preparer=lambda *_a, **_kw: pytest.fail("no native call"))

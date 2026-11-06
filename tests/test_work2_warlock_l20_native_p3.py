"""Warlock L20 P3 uses native source/equipment scoring, never the naked IR proxy."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p3_live as p3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))
from native_p3_equipped import compare_equipped_native  # noqa: E402


def source(*, actor="ClassWarlock", level=20):
    return {
        "raid": {"parties": [{"players": [{
            "class": actor, "level": level,
            "equipment": {"items": [{"id": 100 + i} for i in range(14)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 120, "targets": []},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def prepared(*_args, **_kwargs):
    return {"status": "PREPARED", "actor_class": "ClassWarlock",
            "actor_level": 20, "engine_revision": "pinned-test-engine"}


def paid_receipt(*, actor="ClassWarlock", level=20):
    return {
        "status": "PAID_NATIVE_DIFFERENCE", "objective": "DPS",
        "paid_attempts": 2, "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": actor, "actor_level": level,
            "engine_revision": "pinned-test-engine"},
        "source_occupied_slots": ["head"],
        "evaluations": [
            {"status": "VALID", "score": 7.0, "request_sha256": "original"},
            {"status": "VALID", "score": 7.5, "request_sha256": "changed"}],
        "native_slot_evaluations": [{
            "swap": {"slot": "head", "to_id": 900}, "status": "VALID",
            "score": 7.5, "delta_dps": 0.5, "delta_score": 0.5}],
        "native_slots_valid": 1,
    }


def test_warlock_l20_native_p3_selection_is_specific():
    assert p3.native_item_options_required("warlock", 20, "unrestricted")
    assert not p3.native_item_options_required("warlock", 30, "unrestricted")
    assert not p3.native_item_options_required("warlock", 20, "affliction")


def test_unverified_native_warlock_proposals_do_not_false_block(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.delenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", raising=False)
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda *_args: {
                            "status": "ok", "items": [],
                            "unverified_candidate_count": 20,
                            "unverified_item_ids": [900, 901, 902, 903]})
    monkeypatch.setattr(p3, "_paid_native_equipped_probe",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("No native payment without real actor request")))
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "BLOCKED"
    # Real missing executable actor request still blocks. Source metadata alone
    # must never invent a 'proficiency unverified' gameplay legality verdict.
    assert result["reasons"] == ["P3_NATIVE_WARLOCK_L20_REQUEST_REQUIRED"]
    proposals = p3._native_p3_equipped_slot_proposals(
        {"items": [], "unverified_item_ids": [900, 901, 902, 903]})["slots"]
    assert set(proposals) == {"weapon", "offhand", "ranged", "head", "neck",
                             "shoulder", "back", "chest", "wrist", "hands",
                             "waist", "legs", "feet", "ring1", "ring2",
                             "trinket1", "trinket2"}
    assert all(len(row["selected_ids"]) == 3 for row in proposals.values())
    assert all(set(row["selected_ids"]) <= {900, 901, 902, 903}
               for row in proposals.values())
    assert len({tuple(row["selected_ids"]) for row in proposals.values()}) > 1  # varied source samples


def test_missing_native_warlock_actor_request_refuses_without_payment(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.delenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", raising=False)
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda *_args: {"status": "ok", "items": [
                            {"slot": "head", "item_id": 900, "item_level": 20}]})
    monkeypatch.setattr(p3, "_paid_native_equipped_probe",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("Cannot pay without pinned L20 actor request")))
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P3_NATIVE_WARLOCK_L20_REQUEST_REQUIRED"]


def test_warlock_native_options_to_equipped_p3_no_python_ir(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", "source-L20.json")
    calls = []

    def options(root, binary, cls, level):
        calls.append(("options", binary, cls, level))
        return {"status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                "source": "source-revision", "items": [
                    {"slot": "head", "item_id": 900, "item_level": 20}]}

    def paid(root, binary, selection, remaining, *, checkpoint):
        calls.append(("paid", binary, selection, remaining, checkpoint))
        return paid_receipt()

    monkeypatch.setattr(p3, "_query_native_unified_p3_items", options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "PASS", result["reasons"]
    assert result["production_engine"] == "mythicsim_rust"
    assert result["real_source_search_evaluated"] == 0
    assert result["native_equipped_paid_attempts"] == 2
    assert calls == [
        ("options", "selected-engine", "warlock", 20),
        ("paid", "selected-engine",
         {"slots": {"head": {"selected_ids": [900]}}}, 44, "warlock_l20")]


def test_warlock_selected_request_is_forwarded_with_explicit_actor_level(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", "exact-warlock-L20.json")
    commands = []

    def fake_native(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_native)
    receipt = p3._paid_native_equipped_probe(
        ROOT, "selected-engine",
        {"slots": {"head": {"selected_ids": [900]}}}, 44,
        checkpoint="warlock_l20")
    assert receipt["paid_attempts"] == 2
    command, kw = commands[0]
    assert command[command.index("--request") + 1] == "exact-warlock-L20.json"
    assert command[-4:] == ["--class-key", "warlock", "--level", "20"]
    assert json.loads(kw["input"]) == {"head": {"selected_ids": [900]}}


def test_native_warlock_balanced_dps_pays_real_changed_item_only():
    original = source()
    unchanged = copy.deepcopy(original)
    paid = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert binary == "selected-engine"
        assert mode == "balanced"
        assert kwargs["objective"] == "DPS"
        assert kwargs["actor_level"] == 20
        paid.append(copy.deepcopy(request))
        head = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return (7.5 if head == 900 else 7.0), {}, 0.01, f"paid-{len(paid)}"

    def prepare_l20(*args, **kwargs):
        assert kwargs["actor_level"] == 20
        return prepared(*args, **kwargs)

    result = compare_equipped_native(
        "selected-engine", original, {"head": {"selected_ids": [900]}},
        class_key="warlock", level=20, objective="DPS",
        evaluator=evaluator, preparer=prepare_l20)
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["paid_attempts"] == len(paid) == 2
    assert result["actor_checkpoint_verified"]
    assert result["comparison"]["delta_dps"] == 0.5
    assert original == unchanged


def test_native_warlock_l20_actor_level_is_on_real_cli_prepare_and_sim(monkeypatch):
    import time
    import pytest
    from native_executor import run as native_run
    from native_matrix import NativeCandidateRefusal
    from native_p3_equipped import prepared_native_actor

    commands = []
    def rust_cli(command, **_kwargs):
        commands.append(command)
        if command[1] == "prepare":
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                "player": {"class": "ClassWarlock", "level": 20},
                "reference": {"engine_revision": "native-test"},
            }))
        return SimpleNamespace(returncode=4, stderr="actual native refusal",
                               stdout="")

    monkeypatch.setattr(subprocess, "run", rust_cli)
    prepared_receipt = prepared_native_actor(
        "rust-engine", source(), runner=rust_cli, actor_level=20)
    assert prepared_receipt["status"] == "PREPARED"
    assert prepared_receipt["actor_level"] == 20
    with pytest.raises(NativeCandidateRefusal) as caught:
        native_run("rust-engine", source(), 2, 42, "balanced",
                   time.monotonic() + 10, actor_level=20)
    assert caught.value.status == "INVALID"
    assert [cmd[1] for cmd in commands] == ["prepare", "sim"]
    assert all(cmd[cmd.index("--actor-level") + 1] == "20"
               for cmd in commands)
    assert "--rng-mode" in commands[1]
    assert commands[1][commands[1].index("--rng-mode") + 1] == "balanced"


def test_native_warlock_cannot_promote_level60_donor_or_wrong_class():
    called = []
    donor = compare_equipped_native(
        "selected-engine", source(level=60), {"head": {"selected_ids": [900]}},
        class_key="warlock", level=20, objective="DPS",
        evaluator=lambda *_a, **_kw: called.append(True),
        preparer=prepared)
    assert donor["status"] == "NATIVE_REQUEST_CHECKPOINT_MISMATCH"
    assert donor["paid_attempts"] == 0
    import pytest
    with pytest.raises(ValueError, match="P3_NATIVE_EQUIPPED_CLASS_MISMATCH"):
        compare_equipped_native(
            "selected-engine", source(actor="ClassMage"),
            {"head": {"selected_ids": [900]}},
            class_key="warlock", level=20, objective="DPS",
            evaluator=lambda *_a, **_kw: called.append(True), preparer=prepared)
    assert not called

    wrong_native = p3._native_rogue_p3_verdict(
        {"status": "ok", "items": [{"slot": "head", "item_id": 900, "item_level": 20}]},
        paid_receipt(actor="ClassMage"), checkpoint="warlock_l20")
    assert wrong_native["status"] == "FAIL"
    assert any("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED" in reason
               for reason in wrong_native["reasons"])


def test_native_warlock_prepare_refusal_propagates_to_gate_without_payment():
    """A Rust actor refusal is a visible gate reason, not a proxy fallback."""
    options = {"status": "ok", "items": [
        {"slot": "head", "item_id": 900, "item_level": 20}]}
    receipt = {
        "status": "NATIVE_PREPARE_REFUSED", "reason": "native_spell_not_available:686",
        "paid_attempts": 0, "actor_checkpoint_verified": False,
        "native_prepared_actor": {"status": "NATIVE_PREPARE_REFUSED",
                                  "reason": "native_spell_not_available:686"},
    }
    result = p3._native_rogue_p3_verdict(
        options, receipt, checkpoint="warlock_l20")
    assert result["status"] == "BLOCKED"
    assert "P3_NATIVE_EQUIPPED_REFUSAL:NATIVE_PREPARE_REFUSED:native_spell_not_available:686" in result["reasons"]
    assert result["native_equipped_paid_attempts"] == 0
    assert result["real_source_search_evaluated"] == 0
    assert result["native_equipped_paid_receipt"]["reason"] == receipt["reason"]


def test_native_warlock_probe_execution_error_propagates_to_gate():
    """The real native CLI error text survives a paid-probe transport error."""
    options = {"status": "ok", "items": [
        {"slot": "ranged", "item_id": 901, "item_level": 20}]}
    receipt = {"status": "NATIVE_EQUIPPED_PROBE_ERROR", "paid_attempts": 0,
               "error": "native source request file unreadable"}
    result = p3._native_rogue_p3_verdict(
        options, receipt, checkpoint="warlock_l20")
    assert result["status"] == "BLOCKED"
    assert "P3_NATIVE_EQUIPPED_REFUSAL:NATIVE_EQUIPPED_PROBE_ERROR:native source request file unreadable" in result["reasons"]
    assert result["native_equipped_paid_attempts"] == 0


def test_native_warlock_refused_baseline_does_not_spend_gear_budget():
    """If Rust refuses the original build, swaps cannot produce a P3 delta."""
    from native_matrix import NativeCandidateRefusal

    paid = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert mode == "balanced"
        assert kwargs["objective"] == "DPS"
        paid.append(copy.deepcopy(request))
        raise NativeCandidateRefusal(
            "UNSUPPORTED", reason="native Warlock APL unavailable",
            request_sha256="native-refused-original")

    receipt = compare_equipped_native(
        "selected-engine", source(), {"head": {"selected_ids": [900, 901]}},
        class_key="warlock", level=20, objective="DPS", max_paid_attempts=44,
        evaluator=evaluator, preparer=prepared)
    assert len(paid) == 1
    assert receipt["paid_attempts"] == 1
    assert receipt["status"] == "PAID_NATIVE_REFUSAL"
    assert receipt["evaluations"][0]["status"] == "UNSUPPORTED"
    assert receipt["evaluations"][0]["reason"] == "native Warlock APL unavailable"
    assert receipt["evaluations"][0]["request_sha256"] == "native-refused-original"
    assert receipt["native_slot_evaluations"] == []
    assert receipt["native_slots_valid"] == 0
    assert receipt["source_occupied_slots"]
    assert receipt["comparison"] is None
    assert not receipt["actor_checkpoint_verified"]

    # Paid refusal is FAIL, not an invented comparable score or a 0-paid
    # missing-source BLOCKED. Its actual Rust reason reaches the top-level gate.
    gate = p3._native_rogue_p3_verdict(
        {"status": "ok", "items": [
            {"slot": "head", "item_id": 900, "item_level": 20}]},
        receipt, checkpoint="warlock_l20")
    assert gate["status"] == "FAIL"
    assert gate["native_equipped_paid_attempts"] == 1
    assert "P3_NATIVE_BASELINE_REFUSAL:UNSUPPORTED:native Warlock APL unavailable" in gate["reasons"]
    assert "P3_NATIVE_BASELINE_NOT_VALID" in gate["reasons"]
    assert "P3_NATIVE_RELEVANT_SCORE_SENSITIVITY_NOT_MEASURED" in gate["reasons"]
    assert "runtime_proof" not in gate


def test_warlock_p3_pays_occupied_head_not_empty_weapon_or_wand_slot():
    """Rust proposals for empty slots must not starve real occupied P3 comparisons."""
    original = source()
    items = original["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    items.extend({"id": 0} for _ in range(3))
    unchanged = copy.deepcopy(original)
    seen = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert mode == "balanced" and kwargs["objective"] == "DPS"
        current = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        seen.append([row["id"] for row in current])
        assert [row["id"] for row in current[14:]] == [0, 0, 0]
        return (7.5 if current[0]["id"] == 900 else 7.0), {}, 0.01, f"paid-{len(seen)}"

    receipt = compare_equipped_native(
        "selected-engine", original,
        {"weapon": {"selected_ids": [950]},
         "offhand": {"selected_ids": [951]},
         "ranged": {"selected_ids": [952]},
         "head": {"selected_ids": [900]}},
        class_key="warlock", level=20, objective="DPS",
        max_paid_attempts=2, evaluator=evaluator, preparer=prepared)

    assert len(seen) == receipt["paid_attempts"] == 2
    assert seen[0][0] == 100 and seen[1][0] == 900
    assert receipt["native_slots_requested"] == 1
    assert receipt["native_slot_evaluations"][0]["swap"]["slot"] == "head"
    assert receipt["source_occupied_slots"]
    assert not {"weapon", "offhand", "ranged"}.intersection(receipt["source_occupied_slots"])
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["comparison"]["delta_dps"] == 0.5
    assert original == unchanged


def test_warlock_p3_empty_slot_only_proposals_do_not_run_native():
    """Adding gear to an empty slot cannot count as an occupied-item P3 swap."""
    original = source()
    original["raid"]["parties"][0]["players"][0]["equipment"]["items"].extend(
        {"id": 0} for _ in range(3))

    def not_called(*args, **kwargs):
        raise AssertionError("No prepare or paid scoring for unoccupied-only proposals")

    receipt = compare_equipped_native(
        "selected-engine", original,
        {"weapon": {"selected_ids": [950]},
         "offhand": {"selected_ids": [951]},
         "ranged": {"selected_ids": [952]}},
        class_key="warlock", level=20, objective="DPS",
        evaluator=not_called, preparer=not_called)

    assert receipt["status"] == "NO_DISTINCT_NATIVE_EQUIPPED_ALTERNATIVE"
    assert receipt["paid_attempts"] == 0
    assert receipt["comparison"] is None

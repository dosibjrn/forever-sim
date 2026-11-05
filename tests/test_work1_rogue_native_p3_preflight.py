"""Work1 regression: native Rogue P3 scoring survives legacy bounded policy search."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.wf_gate_p3_live import (
    _native_p3_equipped_slot_proposals,
    run_live,
)


def test_native_option_proposals_use_rust_ids_and_request_slot_aliases():
    source = {"items": [
        {"slot": "one_hand", "item_id": 11, "item_level": 4},
        {"slot": "main_hand", "item_id": 12, "item_level": 8},
        {"slot": "off_hand", "item_id": 13, "item_level": 2},
        {"slot": "finger", "item_id": 14, "item_level": 3},
        {"slot": "finger", "item_id": 15, "item_level": 7},
        {"slot": "unsupported_request_slot", "item_id": 16, "item_level": 9},
    ]}
    selection = _native_p3_equipped_slot_proposals(source)["slots"]
    assert selection["weapon"]["selected_ids"] == [12, 11]
    assert selection["offhand"]["selected_ids"] == [13]
    assert selection["ring1"]["selected_ids"] == [15, 14]
    assert selection["ring2"]["selected_ids"] == [15, 14]
    assert "unsupported_request_slot" not in selection


def test_native_option_projection_keeps_spare_if_first_item_is_equipped():
    source = {"items": [
        {"slot": "chest", "item_id": 104, "item_level": 30},
        {"slot": "chest", "item_id": 512, "item_level": 20},
        {"slot": "chest", "item_id": 513, "item_level": 10},
        {"slot": "chest", "item_id": 514, "item_level": 5},
    ]}
    selection = _native_p3_equipped_slot_proposals(source)["slots"]
    assert selection["chest"]["selected_ids"] == [104, 512, 513]


def _paid_receipt(*, delta=29.0, refusal=False):
    slot_rows = [{
        "swap": {"slot": "weapon", "to_id": 24071},
        "status": "VALID", "score": 4.0 + delta, "delta_dps": delta}]
    if refusal:
        slot_rows.append({
            "swap": {"slot": "chest", "to_id": 500},
            "status": "UNSUPPORTED", "score": None, "delta_dps": None,
            "reason": "native rating source missing"})
    return {
        "status": "PAID_NATIVE_DIFFERENCE" if delta else "PAID_NATIVE_EQUAL",
        "paid_attempts": 2 + int(refusal),
        "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": "ClassRogue", "actor_level": 20,
            "engine_revision": "pinned-native"},
        "evaluations": [
            {"status": "VALID", "score": 4.0, "request_sha256": "baseline-sha"},
            {"status": "VALID", "score": 4.0 + delta, "request_sha256": "equipped-sha"}],
        "comparison": {"baseline_dps": 4.0, "equipped_dps": 4.0 + delta,
                       "delta_dps": delta},
        "native_slot_evaluations": slot_rows,
        "native_slots_valid": 1,
    }


def test_native_rogue_p3_uses_paid_scores_not_legacy_policy(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "native-rogue-l20.json")
    options = {"status": "ok", "items": [
        {"slot": "one_hand", "item_id": 24071, "item_level": 20}]}
    calls = []
    def native_probe(_root, binary, selection, remaining):
        calls.append((binary, selection, remaining))
        return _paid_receipt()
    with (
        patch("src.game.native_p3_item_options.query_native_p3_item_options",
              return_value=options),
        patch("src.game.data.forever.registry.build_game_ir_slice",
              side_effect=AssertionError("Legacy GameIR must not execute")),
        patch("src.v2.source_budgeted_gear.run_source_budgeted_gear",
              side_effect=AssertionError("Legacy naked search must not execute")),
        patch("tools.wf_gate_p3_live._paid_native_equipped_probe",
              side_effect=native_probe),
    ):
        result = run_live(Path("."), "rogue", 20, spec="unrestricted")
    assert calls == [("/selected/native", {"slots": {
        "weapon": {"selected_ids": [24071]}}}, 44)]
    assert result["status"] == "PASS"
    assert result["reasons"] == []
    assert result["production_engine"] == "mythicsim_rust"
    assert result["runtime_proof"]["engine_revision"] == "pinned-native"
    assert result["runtime_proof"]["run_id"] == "baseline-sha"
    assert result["real_source_search_evaluated"] == 0
    assert result["native_equipped_paid_attempts"] == 2
    assert result["p3_shared_budget_attempts"] == 2
    assert result["p3_native_pair_reserved_attempts"] == 44


def test_native_rogue_p3_refused_slot_remains_failed():
    from tools.wf_gate_p3_live import _native_rogue_p3_verdict
    options = {"status": "ok", "items": [
        {"slot": "one_hand", "item_id": 24071, "item_level": 20},
        {"slot": "chest", "item_id": 500, "item_level": 20}]}
    result = _native_rogue_p3_verdict(options, _paid_receipt(refusal=True))
    assert result["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:chest:UNSUPPORTED" in result["reasons"]
    assert "runtime_proof" not in result
    assert result["native_equipped_paid_receipt"]["native_slot_evaluations"][-1]["reason"] == (
        "native rating source missing")


def test_native_rogue_p3_requires_real_score_sensitivity():
    from tools.wf_gate_p3_live import _native_rogue_p3_verdict
    options = {"status": "ok", "items": [
        {"slot": "one_hand", "item_id": 24071, "item_level": 20}]}
    result = _native_rogue_p3_verdict(options, _paid_receipt(delta=0.0))
    assert result["status"] == "FAIL"
    assert "P3_NATIVE_RELEVANT_SCORE_SENSITIVITY_NOT_MEASURED" in result["reasons"]
    assert "runtime_proof" not in result

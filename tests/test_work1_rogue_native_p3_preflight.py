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


def test_feral_l60_native_p3_uses_source_actor_and_not_gameir(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    options = {"class": "druid", "level": 60, "spec": "unrestricted",
               "status": "ok", "items": [
                   {"slot": "two_hand", "item_id": 1001, "item_level": 60}]}
    receipt = _paid_receipt()
    receipt["native_prepared_actor"] = {
        "actor_class": "ClassDruid", "actor_level": 60,
        "engine_revision": "selected-feral"}
    calls = []

    def native_probe(_root, binary, selection, remaining, *, checkpoint):
        calls.append((binary, selection, remaining, checkpoint))
        return receipt

    def native_options(binary, class_key, level, *, spec, slot):
        assert (binary, class_key, level, spec, slot) == (
            "/selected/native", "druid", 60, "unrestricted", "all")
        return options

    with (
        patch("src.game.native_p3_item_options.query_native_p3_item_options",
              side_effect=native_options),
        patch("src.game.data.forever.registry.build_game_ir_slice",
              side_effect=AssertionError("No Feral GameIR")),
        patch("tools.wf_gate_p3_live._paid_native_equipped_probe",
              side_effect=native_probe),
    ):
        result = run_live(Path("."), "druid", 60, spec="feral")
    assert calls == [("/selected/native", {
        "slots": {"weapon": {"selected_ids": [1001]}}}, 44, "feral_l60")]
    assert result["status"] == "PASS"
    assert result["runtime_proof"]["engine_revision"] == "selected-feral"
    assert result["real_source_search_evaluated"] == 0


def test_feral_l60_native_options_refusal_stays_blocked_without_paid_sim(monkeypatch):
    from src.game.native_p3_item_options import NativeItemOptionsError
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    with (
        patch("src.game.native_p3_item_options.query_native_p3_item_options",
              side_effect=NativeItemOptionsError(
                  "P3_NATIVE_ITEM_OPTIONS_REFUSED:NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS")),
        patch("tools.wf_gate_p3_live._paid_native_equipped_probe",
              side_effect=AssertionError("Refusal must not be paid")),
    ):
        result = run_live(Path("."), "druid", 60, spec="feral")
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [
        "P3_NATIVE_ITEM_OPTIONS_REFUSED:NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS"]
    assert result["real_source_search_evaluated"] == 0


def test_feral_p3_rejects_mismatched_native_receipt_actor():
    from tools.wf_gate_p3_live import _native_rogue_p3_verdict
    options = {"status": "ok", "items": [
        {"slot": "two_hand", "item_id": 1001, "item_level": 60}]}
    result = _native_rogue_p3_verdict(
        options, _paid_receipt(), checkpoint="feral_l60")
    assert result["status"] == "FAIL"
    assert any(reason.startswith("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED")
               for reason in result["reasons"])


def test_feral_p3_offhand_native_scores_required_and_refusals_not_waived():
    """The paired offhand fix must produce a paid slot, not a cosmetic P3 PASS."""
    from tools.wf_gate_p3_live import _native_rogue_p3_verdict
    options = {"status": "ok", "items": [
        {"slot": "two_hand", "item_id": 22589, "item_level": 60},
        {"slot": "off_hand", "item_id": 19366, "item_level": 60},
    ]}
    receipt = _paid_receipt()
    receipt["native_prepared_actor"] = {
        "actor_class": "ClassDruid", "actor_level": 60,
        "engine_revision": "selected-feral-native"}
    receipt["paid_attempts"] = 3
    receipt["evaluations"].append({
        "status": "VALID", "score": 6.0,
        "request_sha256": "feral-offhand-sha"})
    receipt["native_slot_evaluations"].append({
        "swap": {"slot": "offhand", "to_id": 19366},
        "status": "VALID", "score": 6.0, "delta_dps": 2.0})
    receipt["native_slots_valid"] = 2
    accepted = _native_rogue_p3_verdict(options, receipt, checkpoint="feral_l60")
    assert accepted["status"] == "PASS"
    assert accepted["pass_count"] == accepted["reachability_count"] == 2
    assert accepted["runtime_proof"]["engine_revision"] == "selected-feral-native"

    receipt["native_slot_evaluations"][-1].update(
        status="UNSUPPORTED", score=None, delta_dps=None,
        reason="native paired item swap not supported")
    rejected = _native_rogue_p3_verdict(options, receipt, checkpoint="feral_l60")
    assert rejected["status"] == "FAIL"
    assert rejected["pass_count"] == 1
    assert "P3_NATIVE_SLOT_UNSCORED:offhand:UNSUPPORTED" in rejected["reasons"]
    assert "runtime_proof" not in rejected


def test_rogue_l20_native_gate_uses_shipped_source_without_environment_override(monkeypatch):
    """Source-native scoring is runnable without a caller-supplied request path."""
    from tools.wf_gate_p3_live import _rogue_l20_native_request
    import src.game.native_p3_item_options as native_options

    root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", raising=False)
    fixture = root / "integrations/mythicsim-rust/fixtures/rogue-l20-p3-native.request.json"
    assert _rogue_l20_native_request(root) == str(fixture)
    assert fixture.is_file()
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/native")
    calls = []

    def probe(root, binary, selection, remaining):
        calls.append((binary, selection, remaining))
        return _paid_receipt()

    with (
        patch.object(native_options, "query_native_p3_item_options",
                     return_value={"status": "ok", "items": [
                         {"slot": "one_hand", "item_id": 24071, "item_level": 20}]}),
        patch("tools.wf_gate_p3_live._paid_native_equipped_probe", side_effect=probe),
    ):
        result = run_live(root, "rogue", 20, spec="unrestricted")

    assert calls == [("/selected/native", {"slots": {
        "weapon": {"selected_ids": [24071]}}}, 44)]
    assert result["native_equipped_paid_attempts"] == 2
    assert result["status"] == "PASS"


def test_rogue_l20_explicit_native_request_override_is_preserved(monkeypatch):
    from tools.wf_gate_p3_live import _rogue_l20_native_request
    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/existing-rogue.json")
    assert _rogue_l20_native_request(Path(".")) == "/tmp/existing-rogue.json"


def test_rogue_native_p3_scores_only_source_occupied_slots():
    """ItemSparse can list unoccupied gear slots; native P3 must not demand them."""
    from tools.wf_gate_p3_live import _native_rogue_p3_verdict
    options = {"status": "ok", "items": [
        {"slot": "one_hand", "item_id": 24071, "item_level": 20},
        {"slot": "chest", "item_id": 500, "item_level": 20},
    ]}
    receipt = _paid_receipt()
    # The selected Rust request has only a main-hand equipped; its producer
    # does not attempt an item swap for an empty chest position.
    receipt["source_occupied_slots"] = ["weapon"]
    accepted = _native_rogue_p3_verdict(options, receipt)
    assert accepted["status"] == "PASS"
    assert accepted["reasons"] == []
    assert accepted["real_catalogue_slots_scored"] == 1
    assert "P3_NATIVE_SLOT_UNSCORED:chest:NOT_ATTEMPTED" not in accepted["reasons"]

    # An actually occupied source slot is still required by the P3 contract.
    receipt["source_occupied_slots"] = ["weapon", "chest"]
    missing = _native_rogue_p3_verdict(options, receipt)
    assert missing["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:chest:NOT_ATTEMPTED" in missing["reasons"]
    assert "runtime_proof" not in missing

    # Older receipts without trustworthy occupied-slot provenance keep the
    # existing conservative item-options fallback; no fabricated coverage.
    receipt["source_occupied_slots"] = ["weapon", "weapon"]
    unverified = _native_rogue_p3_verdict(options, receipt)
    assert unverified["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:chest:NOT_ATTEMPTED" in unverified["reasons"]

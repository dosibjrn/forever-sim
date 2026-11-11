"""Rogue L20 P3 native item forwarding, budget and refusal regressions.

Rust owns item legality and scoring; Forever forwards and classifies receipts.
"""
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p3_live as p3


def test_rogue_l20_native_p3_forwards_rust_items_without_legacy_policy(monkeypatch):
    """Native option IDs reach the paid scorer; Rust refusals stay failures."""
    import src.game.data.forever.registry as registry
    import src.game.native_p3_item_options as native_options
    import src.v2.source_budgeted_gear as budgeted

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-native")
    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/rogue-l20.json")
    native_payload = {"status": "ok", "source": "selected-Rust", "items": [
        {"slot": "chest", "item_id": 104, "item_level": 30},
        {"slot": "chest", "item_id": 512, "item_level": 20},
        {"slot": "chest", "item_id": 513, "item_level": 10},
    ]}
    queries = []

    def native_query(binary, class_key, level, **kwargs):
        queries.append((binary, class_key, level, kwargs))
        return native_payload

    def obsolete_route(**_kwargs):
        raise AssertionError("Rogue native P3 must not run legacy source policy")

    monkeypatch.setattr(native_options, "query_native_p3_item_options", native_query)
    monkeypatch.setattr(budgeted, "run_source_budgeted_gear", obsolete_route)
    monkeypatch.setattr(registry, "build_game_ir_slice", obsolete_route)
    paid_calls = []

    def paid_probe(root, binary, selection, remaining):
        paid_calls.append((binary, selection, remaining))
        return {
            "status": "PAID_NATIVE_REFUSAL", "paid_attempts": 3,
            "actor_checkpoint_verified": False,
            "native_prepared_actor": {"engine_revision": "pinned-native"},
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "baseline-sha"},
                {"status": "UNSUPPORTED", "score": None},
                {"status": "UNSUPPORTED", "score": None},
            ],
            "native_slot_evaluations": [
                {"swap": {"slot": "chest", "to_id": 512},
                 "status": "UNSUPPORTED", "reason": "native rating refusal"},
                {"swap": {"slot": "chest", "to_id": 513},
                 "status": "UNSUPPORTED", "reason": "native rating refusal"},
            ],
            "native_slots_valid": 0,
        }

    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid_probe)
    result = p3.run_live(Path("."), "rogue", 20, spec="unrestricted")

    assert queries == [("selected-native", "rogue", 20,
                        {"spec": "unrestricted", "slot": "all"})]
    assert paid_calls == [("selected-native", {"slots": {
        "chest": {"selected_ids": [104, 512, 513]}}}, 44)]
    assert result["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:chest:UNSUPPORTED" in result["reasons"]
    assert result["native_equipped_paid_attempts"] == 3
    assert result["real_source_search_evaluated"] == 0
    assert result["native_equipped_paid_receipt"]["native_slot_evaluations"][-1]["reason"] == (
        "native rating refusal")


def test_native_rogue_item_records_reuse_validated_snapshot_without_second_query():
    from src.game.native_p3_item_options import native_p3_item_records

    snapshot = {
        "status": "ok", "source": "selected-native",
        "unverified_candidate_count": 0,
        "excluded_non_client_item_count": 2775,
        "items": [{
            "item_id": 401, "name": "Native Rogue chest",
            "slot": "chest", "item_level": 12, "required_level": 10,
            "stats": {"Agility": 5.0},
        }],
    }

    def unexpected_query(*args, **kwargs):
        raise AssertionError("P3 must reuse the already accepted native response")

    records, unmapped, metadata = native_p3_item_records(
        "selected-native", "rogue", 20,
        native_response=snapshot, runner=unexpected_query)
    assert len(records) == 1
    assert records[0].item_id == 401
    assert records[0].agility == 5.0
    assert unmapped == {}
    assert metadata["excluded_non_client_item_count"] == 2775


def test_p3_forwards_selected_native_items_to_paid_equipped_executable(monkeypatch):
    import json
    import subprocess

    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/rogue-l20-source.json")
    invocations = []

    def native_script(command, **kwargs):
        invocations.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "comparison": {"baseline_dps": 10.0,
                           "equipped_dps": 11.0, "delta_dps": 1.0},
            "actor_checkpoint_verified": False,
        }))

    monkeypatch.setattr(subprocess, "run", native_script)
    slots = {"chest": {"selected_ids": [101, 102]}}
    result = p3._paid_native_equipped_probe(
        Path("."), "selected-native", {"slots": slots}, remaining=2)
    assert result["paid_attempts"] == 2
    assert result["comparison"]["delta_dps"] == 1.0
    assert len(invocations) == 1
    command, kwargs = invocations[0]
    assert command[-6:] == [
        "--binary", "selected-native", "--request", "/tmp/rogue-l20-source.json",
        "--max-paid-attempts", "2"]
    assert json.loads(kwargs["input"]) == slots
    assert kwargs["timeout"] == 150


def test_p3_native_equipped_pair_does_not_overrun_shared_paid_budget(monkeypatch):
    import subprocess

    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/native.json")
    monkeypatch.setattr(subprocess, "run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("Do not spend beyond 44 evaluations")))
    result = p3._paid_native_equipped_probe(
        Path("."), "selected-native", {"slots": {}}, remaining=1)
    assert result == {
        "status": "NOT_RUN_PAID_BUDGET_EXHAUSTED", "paid_attempts": 0}


def test_p3_direct_native_rogue_uses_full_44_paid_budget_when_requested(monkeypatch):
    monkeypatch.delenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", raising=False)
    # Repo-shipped Rogue L20 fixture now supports a Rust-item-seeded baseline.
    assert p3._native_equipped_p3_reservation("rogue", 20, "unrestricted", "pinned-native") == 44
    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/native-rogue-source.json")
    assert p3._native_equipped_p3_reservation("rogue", 20, "unrestricted", "pinned-native") == 44
    assert p3._native_equipped_p3_reservation("rogue", 20, "unrestricted", None) == 0
    assert p3._native_equipped_p3_reservation("rogue", 60, "unrestricted", "pinned-native") == 0
    assert p3._native_equipped_p3_reservation("mage", 20, "unrestricted", "pinned-native") == 0
    assert p3._native_equipped_p3_reservation("rogue", 20, "combat", "pinned-native") == 0

def test_p3_native_slot_sweep_receipt_cannot_exceed_remaining_paid_budget(monkeypatch):
    import json
    import subprocess

    monkeypatch.setenv("FOREVER_P3_NATIVE_ROGUE_REQUEST", "/tmp/native.json")
    commands = []

    def native_script(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 19,
            "actor_checkpoint_verified": True,
        }))

    monkeypatch.setattr(subprocess, "run", native_script)
    receipt = p3._paid_native_equipped_probe(
        Path("."), "selected-native", {"slots": {}}, remaining=18)
    assert commands[0][-2:] == ["--max-paid-attempts", "18"]
    assert receipt["status"] == "NATIVE_EQUIPPED_PROBE_ERROR"
    assert receipt["paid_attempts"] == 0

"""P6 compares paid frozen Priest L20 native/world receipts, not GameIR scores."""
import copy
import hashlib
import json

from tools import wf_gate_p6_live
from tools import wf_gate_p4_p5_partial
from tools.wf_native_priest_l20_cold import native_cold_p6_verdict


def _cold(t30=42.01, t300=42.01):
    build = {"raid": {"parties": [{"players": [{
        "class": "ClassPriest", "level": 20,
    }]}]}}
    digest = hashlib.sha256(json.dumps(build, sort_keys=True).encode()).hexdigest()

    def selected(elapsed):
        return {"source_build": copy.deepcopy(build),
                "source_request_sha256": digest,
                "paid_completed_elapsed_s": elapsed}

    def finalist(seconds):
        return {**selected(5.0),
                "route_s_per_mob": seconds,
                "real_100mob_receipt": {
                    "native_2d_persistent_actor_verified": True,
                    "native_2d_persistent_world_ack_verified": True,
                    "native_2d_persistent_paid_recovery": True,
                    "native_2d_persistent_world_targets_killed": 100,
                    "native_2d_persistent_source_action_events": 100,
                    "native_2d_persistent_source_action_counts_by_target":
                        [{"native:585": 1} for _ in range(100)],
                    "native_2d_persistent_elapsed_seconds": seconds * 100,
                }}

    return {
        "native_cold_search_wall_s": 300.15,
        "native_cold_300s_reached": True,
        "native_cold_native_paid_after_30": 17,
        "native_cold_paid_world_route_builds": 4,
        "native_cold_30s_paid_selection": selected(5.0),
        "native_cold_300s_paid_selection": selected(75.0),
        "native_cold_snapshot_30": finalist(t30),
        "native_cold_final_300": finalist(t300),
        # P4's unlock evidence is deliberately absent: P6 has no independent
        # talent-action-witness gate, only real finalist comparison.
        "native_cold_talent_action_witnesses": [],
    }


def test_p6_accepts_same_paid_finalist_with_one_percent_tolerance():
    result = native_cold_p6_verdict(_cold(t30=42.01, t300=42.01))
    assert result["status"] == "PASS", result["reasons"]
    assert result["source_replay_T30_T300"] == 1.0
    assert [row["mob_completed"] for row in result["source_replay_results"]] == [
        100, 100]
    assert result["selected_paid_winners"][0]["source_build"] == (
        result["selected_paid_winners"][1]["source_build"])
    assert result["source_replay_numeric_saturation"] is True


def test_p6_rejects_real_ratio_above_one_percent():
    result = native_cold_p6_verdict(_cold(t30=42.01, t300=40.0))
    assert result["status"] == "FAIL"
    assert result["source_replay_T30_T300"] > 1.01
    assert "P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT" in result["reasons"]


def test_p6_cannot_borrow_incomplete_finalist_or_unpaid_continuation():
    cold = _cold()
    cold["native_cold_snapshot_30"]["real_100mob_receipt"][
        "native_2d_persistent_world_targets_killed"] = 99
    result = native_cold_p6_verdict(cold)
    assert result["status"] == "FAIL"
    assert result["source_replay_T30_T300"] is None
    assert result["source_replay_results"][0]["mob_completed"] == 0
    assert "P6_30S_FROZEN_WINNER_REAL_100MOB_RECEIPT_INCOMPLETE" in result["reasons"]

    cold = _cold()
    cold["native_cold_native_paid_after_30"] = 0
    assert "P6_NO_REAL_PAID_CONTINUATION_AFTER_30S" in (
        native_cold_p6_verdict(cold)["reasons"])
    cold = _cold()
    cold["native_cold_300s_reached"] = False
    assert native_cold_p6_verdict(cold)["status"] == "FAIL"


def test_p6_live_routes_one_native_cold_and_exposes_runtime_proof(
        tmp_path, monkeypatch):
    binary = tmp_path / "selected-mythicsim"
    binary.write_bytes(b"paid-native-executable-fixture")
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", str(binary))
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    calls = []

    def native(class_key, level, spec, *, gate):
        calls.append((class_key, level, spec, gate))
        return _cold()

    monkeypatch.setattr(
        wf_gate_p4_p5_partial,
        "_native_cold_options_without_paid_executor", native)
    result = wf_gate_p6_live.run_live(
        tmp_path, "priest", 20, spec="unrestricted")
    assert calls == [("priest", 20, "unrestricted", "P4")]
    assert result["status"] == "PASS", result["reasons"]
    assert result["production_engine"] == "mythicsim-rust-native-world"
    assert result["runtime_proof"]["engine_revision"] == (
        "mythicsim-rust-bin-sha256:"
        + hashlib.sha256(binary.read_bytes()).hexdigest())
    assert result["runtime_proof"]["run_id"] == "123456"
    assert len(result["selected_paid_winners"]) == 2

    binary.unlink()
    denied = wf_gate_p6_live.run_live(tmp_path, "priest", 20)
    assert denied["status"] == "FAIL"
    assert "P6_EXECUTED_NATIVE_BINARY_IDENTITY_UNAVAILABLE" in denied["reasons"]


def test_p6_live_propagates_native_refusal_without_gameir_fallback(
        tmp_path, monkeypatch):
    monkeypatch.setenv("FOREVER_P4_P5_PRIEST_L20_COLD_SEARCH", "1")
    monkeypatch.setattr(
        wf_gate_p4_p5_partial,
        "_native_cold_options_without_paid_executor",
        lambda *args, **kwargs: {
            "status": "BLOCKED", "reasons": ["NATIVE_UNSUPPORTED"]})
    result = wf_gate_p6_live.run_live(
        tmp_path, "priest", 20, spec="unrestricted")
    assert result == {"status": "BLOCKED", "reasons": ["NATIVE_UNSUPPORTED"]}

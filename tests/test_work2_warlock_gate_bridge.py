"""Forever-owned shared official Warlock cold gate dispatch/receipt tests.

Fake only the paid native producer's *transport* output. These are not 100-mob
or P4/P5/P6 acceptance measurements and never assert native game mechanics.
"""
from __future__ import annotations

import copy

from tools import wf_gate
from tools import wf_gate_p4_live as p4
from tools import wf_gate_p5_live as p5
from tools import wf_gate_p6_live as p6
from tools import wf_warlock_l20_gate_bridge as bridge


def _finalist(key: str, score: float) -> dict:
    raw = {
        "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
        "target_count_requested": 100,
        "hostile_player_tank_requested": True,
        "native_enemy_attack_prepared": True,
        "native_actor_continuity_receipt_complete": True,
        "native_recovery_clock_accounted": True,
        "native_recovery_mode": "decisions_food_water",
        "native_2d_paid_objective_eligible": True,
        "seconds_per_mob": score,
    }
    return {
        "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
        "candidate_sha256": key, "seconds_per_mob": score,
        "native_receipt": raw,
    }


def _cold() -> dict:
    return {
        "cold_300_reached": True, "elapsed_search_s": 300.08,
        "source_request_sha256": "a" * 64,
        "engine_binary_sha256": "b" * 64,
        "source_revision": "test-only-rust-source", "search_seed": 7,
        "native_paid_screen_count": 8, "distinct_paid_candidates": 4,
        "native_paid_after_snapshot": 3,
        "snapshot_30": {"candidate_sha256": "first",
                        "paid_completed_elapsed_s": 24.0},
        "final_300": {"candidate_sha256": "last",
                      "paid_completed_elapsed_s": 298.0},
        "finalists": {"30s": _finalist("first", 10.0),
                      "300s": _finalist("last", 9.95)},
        "p6_comparison": {
            "status": "MEASURED_PAID_100_MOB_FINALISTS",
            "t30_over_t300": 10.0 / 9.95,
        },
        "native_representative_unlocked_cast_compared": True,
    }


def test_one_paid_native_cold_invocation_serves_all_three_official_providers(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    calls = []
    monkeypatch.setattr(bridge, "_execute",
                        lambda: calls.append("native-paid") or _cold())
    bridge.set_shared_warlock_l20_cold(True)
    try:
        results = [gate.run_live(tmp_path, "warlock", 20)
                   for gate in (p4, p5, p6)]
        assert calls == ["native-paid"]
        assert [row["status"] for row in results] == ["PASS", "PASS", "PASS"]
        assert len({row["runtime_proof"]["run_id"] for row in results}) == 1
        assert all(row["runtime_proof"]["executed"] is True for row in results)
        assert results[2]["source_replay_T30_T300"] == 10.0 / 9.95
        assert results[1]["native_paid_after_snapshot"] == 3
    finally:
        bridge.set_shared_warlock_l20_cold(False)


def test_explicit_pair_required_and_other_class_not_redirected(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    bridge.set_shared_warlock_l20_cold(False)
    assert p4.run_live(tmp_path, "warlock", 20)["status"] == "BLOCKED"
    called = []
    monkeypatch.setattr(p5, "run_paid_partial",
                        lambda *args, **kwargs: called.append(kwargs) or {
                            "status": "FAIL", "reasons": ["legacy diagnostic"]})
    assert p5.run_live(tmp_path, "druid", 30)["status"] == "FAIL"
    assert called == [{"spec": "unrestricted", "gate": "P5"}]


def test_native_refusal_and_incomplete_finalists_never_score(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    unsupported = {"status": "FAIL", "reasons": ["NATIVE_UNSUPPORTED"],
                   "native_receipt": {"status": "UNSUPPORTED"}}
    monkeypatch.setattr(bridge, "_execute", lambda: copy.deepcopy(unsupported))
    bridge.set_shared_warlock_l20_cold(True)
    try:
        for gate in (p4, p5, p6):
            got = gate.run_live(tmp_path, "warlock", 20)
            assert got["status"] == "FAIL"
            assert "NATIVE_UNSUPPORTED" in got["reasons"]
    finally:
        bridge.set_shared_warlock_l20_cold(False)

    incomplete = _cold()
    incomplete["finalists"]["300s"] = {
        "status": "INCOMPLETE_100_NATIVE_FINALIST", "reason": "NATIVE_INVALID"}
    monkeypatch.setattr(bridge, "_execute", lambda: incomplete)
    bridge.set_shared_warlock_l20_cold(True)
    try:
        # P4 may use its own real completed 30s winner; P5 and P6
        # independently require the missing 300s winner receipt.
        assert p4.run_live(tmp_path, "warlock", 20)["status"] == "PASS"
        for gate in (p5, p6):
            got = gate.run_live(tmp_path, "warlock", 20)
            assert got["status"] == "FAIL"
            assert "P5_NATIVE_100MOB_FINALIST_INCOMPLETE" in got["reasons"]
    finally:
        bridge.set_shared_warlock_l20_cold(False)


def test_p4_unlock_cast_is_not_inferred_from_available_action_ids(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    report = _cold()
    del report["native_representative_unlocked_cast_compared"]
    monkeypatch.setattr(bridge, "_execute", lambda: report)
    bridge.set_shared_warlock_l20_cold(True)
    try:
        got = p4.run_live(tmp_path, "warlock", 20)
        assert got["status"] == "FAIL"
        assert "P4_NATIVE_REPRESENTATIVE_UNLOCK_CAST_UNVERIFIED" in got["reasons"]
        # Missing P4 cast comparison cannot invent a P5 or P6 veto.
        assert p5.run_live(tmp_path, "warlock", 20)["status"] == "PASS"
        assert p6.run_live(tmp_path, "warlock", 20)["status"] == "PASS"
    finally:
        bridge.set_shared_warlock_l20_cold(False)


def test_p6_real_ratio_and_provenance_are_required(monkeypatch, tmp_path):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    report = _cold()
    report["p6_comparison"]["t30_over_t300"] = None
    report["finalists"]["30s"]["native_receipt"]["native_recovery_clock_accounted"] = False
    monkeypatch.setattr(bridge, "_execute", lambda: report)
    bridge.set_shared_warlock_l20_cold(True)
    try:
        got = p6.run_live(tmp_path, "warlock", 20)
        assert got["status"] == "FAIL"
        assert "P6_NATIVE_PAID_100MOB_ONE_PERCENT_NOT_PROVEN" in got["reasons"]
        assert "P4_NATIVE_100MOB_FINALIST_INCOMPLETE" in got["reasons"]
    finally:
        bridge.set_shared_warlock_l20_cold(False)


def test_official_paired_cli_arms_warlock_source_producer(monkeypatch, capsys):
    monkeypatch.setenv(bridge.OPT_IN, "1")
    called = []
    def fake_gate(_root, _class, _level, _spec, gate):
        assert bridge._SHARED_COLD is not None
        called.append(gate)
        return {"status": "FAIL", "reasons": ["NO_PAID_NATIVE_RESULT"]}
    monkeypatch.setattr(wf_gate, "_run_live_gate", fake_gate)
    try:
        assert wf_gate.main(["--class", "warlock", "--level", "20",
                             "--gate", "P4+P5+P6"]) != 0
        assert called == ["P4", "P5", "P6"]
        assert "NO_PAID_NATIVE_RESULT" in capsys.readouterr().out
    finally:
        bridge.set_shared_warlock_l20_cold(False)


def test_only_world_acked_rust_source_effects_are_attributed():
    """Observe native IDs, not Python guesses of casts or spell legality."""
    # The paid Warlock entrypoint installs the maintained native integration
    # import path, as it does in real producer execution.
    from tools import wf_warlock_l20_100mob as _paid_warlock  # noqa: F401
    from live_two_world_pulls import accumulate_acked_native_source_effects

    native = {"native_damage_events": [
        {"event_id": "effect-1", "source_action_id": "Spell-686",
         "native_caster_type": "player"},
        {"event_id": "effect-2", "source_action_id": "Spell-172",
         "native_caster_type": "player"},
        {"event_id": "effect-3", "source_action_id": "Pet-1",
         "native_caster_type": "pet"},
    ]}
    counted = {}
    accumulate_acked_native_source_effects(
        counted, native, {"applied_event_ids": ["effect-1", "effect-3"]})
    assert counted == {"player": {"Spell-686": 1}, "pet": {"Pet-1": 1}}
    # A second ACK for a real event increments the native identity; an
    # unacknowledged effect never receives a fabricated world observation.
    accumulate_acked_native_source_effects(
        counted, native, {"applied_event_ids": ["effect-1"]})
    assert counted == {"player": {"Spell-686": 2}, "pet": {"Pet-1": 1}}


def test_source_damage_effects_are_not_mistaken_for_talent_unlock_casts(
        monkeypatch, tmp_path):
    """Native damage may be periodic or pet damage: no invented P4 PASS."""
    monkeypatch.setenv(bridge.OPT_IN, "1")
    report = _cold()
    del report["native_representative_unlocked_cast_compared"]
    report["finalists"]["30s"]["native_receipt"][
        "native_source_damage_effects_by_caster"] = {
            "player": {"Spell-686": 3}, "pet": {"Pet-1": 4}}
    monkeypatch.setattr(bridge, "_execute", lambda: report)
    bridge.set_shared_warlock_l20_cold(True)
    try:
        got = p4.run_live(tmp_path, "warlock", 20)
        assert got["status"] == "FAIL"
        assert "P4_NATIVE_REPRESENTATIVE_UNLOCK_CAST_UNVERIFIED" in got["reasons"]
    finally:
        bridge.set_shared_warlock_l20_cold(False)

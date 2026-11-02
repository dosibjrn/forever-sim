"""Work2: explicit P4/P5 full-source entrypoint, not formal gate PASS.

These boundary tests never replace the on-demand 30/300s sourced CombatRuntime
run or its selected native<->2D acceptance.
"""
from pathlib import Path

import pytest

from tools import wf_gate_p4_p5_partial as gates
from tools import wf_gate_p6_full_source as executor


def _production_receipt(budget, *, seconds=12.5, kills=100):
    return {
        "class_key": "druid", "level": 30,
        "search_only": True, "requested_wall_budget_s": budget,
        "wall_s": float(budget) - 0.1,
        "source_db_sha256": "a" * 64,
        "source_gear_catalogue_snapshot": {"schema": "source_gear_snapshot_v1"},
        "validation_shortlist": [{"full_source_build": True}],
        "unique_full_builds": 25 if budget == 30 else 250,
        "screen_complete_candidates": 23 if budget == 30 else 235,
        "p4_talent_unlock_coverage": {"some_source_action": "EXECUTED"},
        "validation": {
            "validated_winner_id": "0",
            "rows": [{"id": "0", "status": "COMPLETE",
                      "count": kills, "full_s_per_mob": seconds}],
        },
    }


@pytest.mark.parametrize("gate,budget,timeout", [
    ("P4", 30, 420), ("P5", 300, 720),
])
def test_explicit_full_source_gate_uses_existing_real_production_cli(
        monkeypatch, gate, budget, timeout):
    calls = []

    def execute(root, args, output, time_limit, **kwargs):
        calls.append((root, args, output.name, time_limit, kwargs))
        if args[0] == "--compare-30":
            return {
                "N30_unique_paid": 25, "N300_unique_paid": 250,
                "p5_10x_breadth": True,
                "same_source_legal_candidate_space_proven": True,
                "replays": [
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 13.0},
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 12.5},
                ],
            }, None
        return _production_receipt(int(args[1])), None

    monkeypatch.setattr(executor, "_execute", execute)
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate=gate)
    if gate == "P4":
        assert calls == [(Path("/project"), ["--budget", "30"],
                          "cold.json", timeout, {})]
    else:
        assert len(calls) == 3
        assert calls[0] == (Path("/project"), ["--budget", "30"],
                            "cold-30.json", 420, {})
        assert calls[1] == (Path("/project"), ["--budget", "300"],
                            "cold-300.json", 720, {})
        assert calls[2][1][0] == "--compare-30"
        assert calls[2][1][2] == "--compare-300"
        assert calls[2][2:] == ("comparison.json", 240, {"allowed_codes": (0, 1)})
    assert result["status"] == "FAIL"  # actual native/world not yet proven
    assert result["real_search_wall_s"] == budget - 0.1
    assert result["real_100mob_complete"] is True
    assert result["real_100mob_count"] == 100
    assert result["real_100mob_s_per_mob"] == 12.5
    assert result["selected_backend_integration_pending"] is True
    assert result["real_paid_unique_full_builds"] > 0
    if gate == "P5":
        assert result["independent_N30_unique_paid"] == 25
        assert result["independent_N300_unique_paid"] == 250
        assert result["independent_p5_10x_breadth"] is True
        assert result["independent_same_source_candidate_space"] is True
        assert result["independent_100mob_winner_replays_complete"] is True
        assert "P5_N300_GE_TEN_TIMES_N30_NOT_PROVEN" not in result["reasons"]


@pytest.mark.parametrize("missing", ["breadth", "space", "replay"])
def test_p5_independent_cold_comparison_rejects_incomplete_proof(monkeypatch, missing):
    def execute(root, args, output, time_limit, **kwargs):
        if args[0] != "--compare-30":
            return _production_receipt(int(args[1])), None
        comparison = {
            "N30_unique_paid": 25, "N300_unique_paid": 250,
            "p5_10x_breadth": missing != "breadth",
            "same_source_legal_candidate_space_proven": missing != "space",
            "replays": [
                {"status": "COMPLETE", "count": 100,
                 "mob_completed": 100, "s_per_mob": 13.0},
                {"status": "COMPLETE", "count": 100,
                 "mob_completed": 100, "s_per_mob": 12.5},
            ],
        }
        if missing == "replay":
            comparison["replays"][1]["count"] = 99
        return comparison, None

    monkeypatch.setattr(executor, "_execute", execute)
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P5")
    expected = {
        "breadth": "P5_N300_GE_TEN_TIMES_N30_NOT_PROVEN",
        "space": "P5_INDEPENDENT_COLD_SOURCE_SPACE_NOT_MATCHED",
        "replay": "P5_INDEPENDENT_WINNERS_100MOB_REPLAY_INCOMPLETE",
    }
    assert result["status"] == "FAIL"
    assert expected[missing] in result["reasons"]
    assert result["selected_backend_integration_pending"] is True


def test_p5_stops_before_300s_when_independent_30s_fails(monkeypatch):
    calls = []
    def execute(root, args, output, time_limit, **kwargs):
        calls.append(args)
        return None, "PAID_SOURCE_RUN_FAILED:rc=1"
    monkeypatch.setattr(executor, "_execute", execute)
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P5")
    assert calls == [["--budget", "30"]]
    assert result["reasons"] == ["P5_30S_PAID_SOURCE_RUN_FAILED:rc=1"]


@pytest.mark.parametrize("seconds,kills", [
    (0, 100), (-1, 100), (float("nan"), 100),
    (float("inf"), 100), (True, 100), (12.5, 99),
])
def test_false_paid_winners_never_prove_100_mobs(
        monkeypatch, seconds, kills):
    monkeypatch.setattr(
        executor, "_execute",
        lambda *args, **kw: (_production_receipt(
            30, seconds=seconds, kills=kills), None))
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P4")
    assert result["status"] == "FAIL"
    assert result["real_100mob_complete"] is False
    assert result["real_100mob_count"] == 0
    assert "P4_INCOMPLETE_PAID_100MOB_FINALIST" in result["reasons"]


def test_cold_search_bad_budget_does_not_claim_actual_run(monkeypatch):
    bad = _production_receipt(30)
    bad["requested_wall_budget_s"] = 6
    monkeypatch.setattr(executor, "_execute",
                        lambda *args, **kw: (bad, None))
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P4")
    assert result["reasons"] == ["P4_SOURCE_COLD_SEARCH_RECEIPT_INCOMPLETE"]
    assert "real_100mob_complete" not in result


def test_full_p4_p5_only_for_source_implemented_checkpoint(monkeypatch):
    monkeypatch.setattr(executor, "_execute",
                        lambda *args, **kw: pytest.fail("must not execute"))
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 60, spec="balance", gate="P5")
    assert result["status"] == "BLOCKED"
    assert "P5_FULL_SOURCE_RUNNER_CURRENTLY_SUPPORTS_DRUID_L30_UNRESTRICTED_ONLY" in result["reasons"]


def test_opt_in_routes_and_default_not_eager(monkeypatch):
    monkeypatch.setenv("FOREVER_P4_P5_FULL_SOURCE", "1")
    calls = []
    def full(root, class_key, level, *, spec, gate):
        calls.append((class_key, level, spec, gate))
        return {"status": "FAIL", "production_engine": "gsim_CombatRuntime"}
    monkeypatch.setattr(gates, "run_full_paid_source_search", full)
    result = gates.run_paid_partial(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P4")
    assert result["status"] == "FAIL"
    assert calls == [("druid", 30, "unrestricted", "P4")]


@pytest.mark.parametrize("mode", [
    "source_legal", "illegal_gear", "untyped_effects", "changed_catalogue",
    "membership_attested",
])
def test_source_winner_catalogue_and_equipment_audit(monkeypatch, mode):
    """Boundary regression using the SAME source audit as real P6 replay."""
    from src.v2 import source_paid_cold_comparison as comparison

    report = _production_receipt(30)
    report["validation_shortlist"] = [{
        "allocation": {}, "equipped_gear": {"slots": {}},
        "opening_action_ids": [], "policy_ir": {},
        "policy_signature": "sourced-policy", "recovery": "normal",
    }]
    report["source_gear_catalogue_snapshot"] = {
        "schema": "source_gear_snapshot_v1",
        "class_membership_verified": mode == "membership_attested",
    }
    calls = []

    def snapshot(class_key, level):
        assert (class_key, level) == ("druid", 30)
        if mode == "changed_catalogue":
            return {"schema": "new-catalogue"}
        return report["source_gear_catalogue_snapshot"]

    def gear_audit(winner, *, class_key, level):
        calls.append(("gear", class_key, level))
        if mode == "illegal_gear":
            raise ValueError("COLD_COMPARISON_WINNER_GEAR_NOT_SOURCE_LEGAL")
        return {"equipment_legality_complete": True}

    def effects(winner, *, class_key, level):
        calls.append(("effects", class_key, level))
        return {"ring1": {"unresolved_effects": ["source-extra"]}} if (
            mode == "untyped_effects") else {}

    monkeypatch.setattr(comparison, "source_gear_catalogue_snapshot", snapshot)
    monkeypatch.setattr(comparison, "_verify_winner_gear_legality", gear_audit)
    monkeypatch.setattr(comparison, "_winner_gear_effect_gaps", effects)
    monkeypatch.setattr(executor, "_execute", lambda *a, **kw: (report, None))
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P4")

    assert result["status"] == "FAIL"  # no fake native-2D promotion
    assert result["real_100mob_complete"] is True  # real kills separate from legality
    assert result["saved_full_source_winner_build"] is True
    assert result["gear_source_snapshot_matches_current"] is (
        mode != "changed_catalogue")
    assert result["winning_gear_source_legality_verified"] is (
        mode not in ("illegal_gear", "changed_catalogue"))
    assert result["source_class_gear_membership_attested"] is (
        mode == "membership_attested")
    if mode == "changed_catalogue":
        assert calls == []
        assert "P4_GEAR_CATALOGUE_SNAPSHOT_NOT_VERIFIED" in result["reasons"]
    elif mode == "illegal_gear":
        assert calls == [("gear", "druid", 30)]
        assert "ValueError" in result["winning_gear_audit_error"]
        assert "P4_WINNING_GEAR_SOURCE_LEGALITY_NOT_VERIFIED" in result["reasons"]
    else:
        assert calls == [("gear", "druid", 30), ("effects", "druid", 30)]
    if mode == "untyped_effects":
        assert result["winning_gear_unresolved_effects"]
        assert "P4_WINNER_ITEM_EFFECTS_UNRESOLVED" in result["reasons"]
    if mode == "membership_attested":
        assert "P4_SOURCE_CLASS_ITEM_MEMBERSHIP_NOT_ATTESTED" not in result["reasons"]
    else:
        assert "P4_SOURCE_CLASS_ITEM_MEMBERSHIP_NOT_ATTESTED" in result["reasons"]


def test_paid_shortlist_without_full_source_build_never_calls_gear_audit(monkeypatch):
    from src.v2 import source_paid_cold_comparison as comparison
    monkeypatch.setattr(comparison, "source_gear_catalogue_snapshot",
                        lambda *args: pytest.fail("incomplete saved build"))
    monkeypatch.setattr(executor, "_execute",
                        lambda *args, **kw: (_production_receipt(30), None))
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P4")
    assert result["real_100mob_complete"] is True
    assert result["saved_full_source_winner_build"] is False
    assert result["winning_gear_source_legality_verified"] is False
    assert result["winning_gear_audit_error"] == "SAVED_SOURCE_WINNER_INCOMPLETE"

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
                "N30_unique_paid": 25, "N300_unique_paid": 50,
                "p5_2x_or_exhaustion_breadth": True,
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
        assert result["independent_N300_unique_paid"] == 50
        assert result["independent_p5_2x_or_exhaustion_breadth"] is True
        assert result["independent_same_source_candidate_space"] is True
        assert result["independent_100mob_winner_replays_complete"] is True
        assert "P5_N300_GE_DOUBLE_N30_OR_VERIFIED_UNIVERSE_NOT_PROVEN" not in result["reasons"]


@pytest.mark.parametrize("missing", ["breadth", "space", "replay"])
def test_p5_independent_cold_comparison_rejects_incomplete_proof(monkeypatch, missing):
    def execute(root, args, output, time_limit, **kwargs):
        if args[0] != "--compare-30":
            return _production_receipt(int(args[1])), None
        comparison = {
            "N30_unique_paid": 25, "N300_unique_paid": 50,
            "p5_2x_or_exhaustion_breadth": missing != "breadth",
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
        "breadth": "P5_N300_GE_DOUBLE_N30_OR_VERIFIED_UNIVERSE_NOT_PROVEN",
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


@pytest.mark.parametrize("gate,budget", [("P4", 30), ("P5", 300)])
def test_full_l60_balance_uses_canonical_source_checkpoint_inputs(
        monkeypatch, gate, budget):
    # This is a CLI routing contract, not a substitute for the real 30/300 s
    # source-paid run or the selected native/world runtime.
    calls = []
    def execute(root, args, output, time_limit, **kwargs):
        calls.append(args)
        if args[0] == "--compare-30":
            return {"N30_unique_paid": 25, "N300_unique_paid": 50,
                    "p5_2x_or_exhaustion_breadth": True,
                    "same_source_legal_candidate_space_proven": True,
                    "replays": [{"status": "COMPLETE", "count": 100,
                                 "mob_completed": 100, "s_per_mob": 12.5}] * 2}, None
        report = _production_receipt(int(args[1]))
        report["level"] = 60
        report["spec_constraint"] = {"tree_key": "balance",
                                     "minimum_points": 31,
                                     "required_combat_mode": None}
        return report, None
    monkeypatch.setattr(executor, "_execute", execute)
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 60, spec="balance", gate=gate)
    assert result["status"] == "FAIL"  # gsim-only is never formal P4/P5 PASS
    assert result["real_100mob_complete"] is True
    assert result["real_search_wall_s"] == budget - 0.1
    context = ["--checkpoint-class", "druid",
               "--checkpoint-level", "60", "--checkpoint-spec", "balance"]
    assert len(calls) == (3 if gate == "P5" else 1)
    assert all(call[-len(context):] == context for call in calls)


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
    # Absence of a full external item scrape is a diagnostic, not a P4 veto.
    assert "P4_SOURCE_CLASS_ITEM_MEMBERSHIP_NOT_ATTESTED" not in result["reasons"]


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


@pytest.mark.parametrize("gate", ["P4", "P5"])
@pytest.mark.parametrize("unlocks_complete", [False, True])
def test_approved_gsim_paid_gate_uses_actual_predicates_not_extra_catalogue_or_native_veto(
        monkeypatch, gate, unlocks_complete):
    """Synthetic receipts test predicate wiring only, never certify a real run.

    A real gsim 2D+CombatRuntime result is permitted by COMMON; absence of
    native-hybrid or a complete external item scrape is not its failure.
    Source/legal winner, same paid search, coverage and actual replay still are.
    """
    from src.v2 import source_paid_cold_comparison as comparison

    def report_for(budget):
        report = _production_receipt(budget)
        report.update({
            "pack_size": 2,
            "spatial_mode": "simultaneous_2d_pack",
            "source_search_space": {
                "class_key": "druid", "level": 30,
                "checkpoint_spec": "unrestricted",
            },
            "p4_talent_unlock_coverage_pass": unlocks_complete,
            "source_gear_catalogue_snapshot": {
                "schema": "source_gear_snapshot_v1",
                "class_membership_verified": False,
            },
            "validation_shortlist": [{
                "allocation": {}, "equipped_gear": {"slots": {}},
                "opening_action_ids": [], "policy_ir": {},
                "policy_signature": "synthetic", "recovery": "normal",
            }],
        })
        return report

    def execute(root, args, output, timeout, **kwargs):
        if args[0] == "--compare-30":
            return {
                "same_source_legal_candidate_space_proven": True,
                "p5_2x_or_exhaustion_breadth": True,
                "N30_unique_paid": 25, "N300_unique_paid": 50,
                "replays": [
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 12.5},
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 12.0},
                ],
            }, None
        return report_for(int(args[1])), None

    monkeypatch.setattr(executor, "_execute", execute)
    monkeypatch.setattr(comparison, "source_gear_catalogue_snapshot",
                        lambda class_key, level: report_for(30)[
                            "source_gear_catalogue_snapshot"])
    monkeypatch.setattr(comparison, "_verify_winner_gear_legality",
                        lambda *a, **kw: {"equipment_legality_complete": True})
    monkeypatch.setattr(comparison, "_winner_gear_effect_gaps",
                        lambda *a, **kw: {})
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate=gate)
    assert result["status"] == ("PASS" if unlocks_complete else "FAIL")
    assert result["source_class_gear_membership_attested"] is False
    assert result["real_100mob_complete"] is True
    assert result["selected_production_backend"] == "gsim"
    if unlocks_complete:
        proof = result["runtime_proof"]
        assert proof["executed"] is True
        assert proof["engine_revision"].startswith("gsim-")
        assert len(proof["source_revision"]) == 64
        assert proof["run_id"].startswith("source-paid-" + gate.lower() + "-")
    else:
        assert "runtime_proof" not in result
    assert not any("NATIVE_2D" in reason or "MEMBERSHIP_NOT_ATTESTED" in reason
                   or "LEGAL_SPACE_COMPLETENESS" in reason
                   for reason in result["reasons"])
    if not unlocks_complete:
        assert gate + "_TALENT_UNLOCK_PAID_EVALUATIONS_INCOMPLETE" in result["reasons"]

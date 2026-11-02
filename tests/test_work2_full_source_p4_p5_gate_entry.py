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

    def execute(root, args, output, time_limit):
        calls.append((root, args, output.name, time_limit))
        return _production_receipt(budget), None

    monkeypatch.setattr(executor, "_execute", execute)
    result = gates.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate=gate)
    assert calls == [(Path("/project"), ["--budget", str(budget)],
                      "cold.json", timeout)]
    assert result["status"] == "FAIL"  # actual native/world not yet proven
    assert result["real_search_wall_s"] == budget - 0.1
    assert result["real_100mob_complete"] is True
    assert result["real_100mob_count"] == 100
    assert result["real_100mob_s_per_mob"] == 12.5
    assert result["selected_backend_integration_pending"] is True
    assert result["real_paid_unique_full_builds"] > 0
    if gate == "P5":
        assert "P5_INDEPENDENT_N300_GE_10_N30_NOT_COMPARED" in result["reasons"]


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

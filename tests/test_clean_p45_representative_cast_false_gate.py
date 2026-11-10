"""Clean regression: legacy selected paid P4/P5 must not invent a cast witness gate.

These synthetic receipts exercise Forever's result classification only; they
are not M1 PASS evidence and do not substitute for an actual paid native run.
"""
from pathlib import Path

import pytest

from tools import wf_gate_p4_p5_partial as gate
from tools import wf_gate_p6_full_source as executor
from src.v2 import source_paid_cold_comparison as comparison


def _paid_receipt(*, mobs=100, continuation=1):
    build = {
        "paid_candidate_index": 0,
        "allocation": {},
        "equipped_gear": {"slots": {}},
        "opening_action_ids": [],
        "policy_ir": {},
        "policy_signature": "actual-paid-candidate",
        "recovery": "normal",
    }
    return {
        "class_key": "druid",
        "level": 30,
        "search_only": True,
        "requested_wall_budget_s": 300,
        "wall_s": 300,
        "source_db_sha256": "a" * 64,
        "source_gear_catalogue_snapshot": {"source": "exact-snapshot"},
        "source_search_space": {
            "class_key": "druid", "level": 30,
            "checkpoint_spec": "unrestricted",
        },
        "spatial_mode": "simultaneous_2d_pack",
        "pack_size": 2,
        "unique_full_builds": 2,
        "screen_complete_candidates": 2,
        "validation_shortlist": [build],
        "validation": {
            "validated_winner_id": "0",
            "rows": [{
                "id": "0", "status": "COMPLETE" if mobs == 100 else "FAIL",
                "count": mobs, "mob_completed": mobs,
                "full_s_per_mob": 12.0,
            }],
        },
        "snapshot_30": {
            "winner": {"paid_candidate_index": 0},
            "validation_shortlist_index": 0,
            "cutoff_elapsed_s": 30,
            "source": "PAID_SCREEN_COMPLETION_CLOCK",
            "unique_full_builds_before_cutoff": 1,
            "paid_candidates_after_cutoff": continuation,
        },
        # Diagnostic only: this build has no positive representative
        # talent-unlock cast witness, but actual native/gsim results are paid.
        "p4_talent_unlock_coverage": {
            "optional_unlock": {"status": "NOT_CAST", "executed_casts": 0},
        },
    }


@pytest.fixture
def paid(monkeypatch):
    def use(*, mobs=100, continuation=1):
        receipt = _paid_receipt(mobs=mobs, continuation=continuation)
        calls = []

        def execute(root, args, output, limit, **kwargs):
            calls.append((args, limit))
            return receipt, None

        monkeypatch.setattr(executor, "_execute", execute)
        monkeypatch.setattr(
            comparison, "source_gear_catalogue_snapshot",
            lambda class_key, level: receipt["source_gear_catalogue_snapshot"])
        monkeypatch.setattr(
            comparison, "_verify_winner_gear_legality",
            lambda winner, *, class_key, level: {"equipment_legality_complete": True})
        monkeypatch.setattr(
            comparison, "_winner_gear_effect_gaps",
            lambda winner, *, class_key, level: {})
        return calls
    return use


@pytest.mark.parametrize("name", ["P4", "P5"])
def test_missing_representative_cast_does_not_veto_paid_gate(name, paid):
    calls = paid()
    result = gate.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate=name)
    assert calls == [(["--budget", "300"], 720)]
    assert result["status"] == "PASS"
    assert result["real_100mob_complete"] is True
    assert result["p4_p5_100mob_winner_replays_complete"] is True
    assert result["real_talent_unlocked_actions"]["optional_unlock"]["status"] == "NOT_CAST"
    assert result["reasons"] == []
    assert result["runtime_proof"]["executed"] is True


@pytest.mark.parametrize("name", ["P4", "P5"])
def test_real_incomplete_100mob_remains_a_failure(name, paid):
    paid(mobs=99)
    result = gate.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate=name)
    assert result["status"] == "FAIL"
    assert name + "_INCOMPLETE_PAID_100MOB_FINALIST" in result["reasons"]
    assert "runtime_proof" not in result


def test_real_p5_continuation_still_required(paid):
    paid(continuation=0)
    result = gate.run_full_paid_source_search(
        Path("/project"), "druid", 30, spec="unrestricted", gate="P5")
    assert result["status"] == "FAIL"
    assert "P5_NO_REAL_PAID_EVALUATION_AFTER_30S" in result["reasons"]
    assert "runtime_proof" not in result

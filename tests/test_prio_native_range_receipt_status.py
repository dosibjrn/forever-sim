"""Optimizer must never rank a refused or unclassified native attempt.

The mock receipts test Forever-owned response classification only; they are
not simulated Warcraft combat or substitutes for real native-paid measurements.
"""
from __future__ import annotations

import hashlib

import pytest

from src.v2.native_range_optimizer import optimize


def _receipt(label: str, status: str | None) -> dict:
    row = {
        "level": 20, "mob_count": 3, "targets_killed": 3,
        "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "terminal_recovery_seconds": 1.0, "elapsed_seconds": 5.0,
        "source_request_sha256": hashlib.sha256(label.encode()).hexdigest(),
        "engine_binary_sha256": "a" * 64,
        "candidate_id": label,
    }
    if status is not None:
        row["status"] = status
    return row


@pytest.mark.parametrize("bad_status", [
    None, "NATIVE_REFUSAL", "NATIVE_SCORER_RECEIPT_REFUSAL",
    "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED",
])
@pytest.mark.parametrize("mode", ["independent", "continuing"])
def test_unmeasured_native_status_cannot_be_promoted_by_positive_transport_fields(
    bad_status, mode
):
    """Even contradictory receipt flags must not turn a refusal into time."""
    result = optimize(
        20, 20, 1, 3, 1,
        evaluate=lambda **_: [_receipt("refused", bad_status)],
        mode=mode,
    )
    assert result["sampled_levels_completed"] == []
    assert result["native_candidates_examined"] == 1
    assert len(result["rejected_native_attempts"]) == 1
    assert result["rejected_native_attempts"][0]["reason"] == (
        "native measured full-recovery status missing"
    )
    assert result["rejected_native_attempts"][0]["native_status"] == bad_status
    assert result["ranked_alternatives"] == []
    if mode == "independent":
        assert result["independent_level_rankings"]["20"] == []
        assert result["status"] == "NO_COMPARABLE_NATIVE_ANCHORS"
    else:
        assert result["status"] == "NO_COMPARABLE_NATIVE_PATH"


def test_valid_native_paid_receipt_remains_ranked_beside_refusal():
    result = optimize(
        20, 20, 1, 3, 2,
        evaluate=lambda **_: [
            _receipt("refused", "NATIVE_REFUSAL"),
            _receipt("paid", "MEASURED_NATIVE_FULLY_RECOVERED"),
        ],
        mode="independent",
    )
    assert result["native_candidates_examined"] == 2
    assert result["sampled_levels_completed"] == [20]
    assert result["status"] == "INDEPENDENT_NATIVE_ANCHORS_PARTIAL"
    assert result["competing_qualified_paths_by_level"]["20"] == 1
    assert len(result["independent_level_rankings"]["20"]) == 1
    assert (result["independent_level_rankings"]["20"][0]["receipt"]["candidate_id"]
            == "paid")
    assert result["rejected_native_attempts"][0]["candidate_id"] == "refused"

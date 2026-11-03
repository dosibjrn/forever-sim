"""P7 search wall-window regression: no extra last-step proof is required.

This is not a combat gate PASS. The 300s production search, legal execution,
1,000-stochastic-fight holdout and numeric floor remain separate conditions.
"""
from pathlib import Path

import pytest

from tools.wf_gate_coverage import p7_search_window_completed

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("elapsed", [300.0, 300.000114, 300.082, 301.0])
def test_measured_full_search_window_accepts_old_and_new_receipts(elapsed):
    # The historical 300.082s execution must not fail because a final
    # native search step completed 82ms after a separately invented deadline.
    assert p7_search_window_completed(full_search=True, elapsed_seconds=elapsed)


@pytest.mark.parametrize("elapsed", [0, 299.999, 301.0001, -1, float("nan"),
                                     float("inf"), "300", True])
def test_short_long_or_invalid_wall_window_never_completes(elapsed):
    assert not p7_search_window_completed(full_search=True, elapsed_seconds=elapsed)


def test_bounded_probe_cannot_claim_a_full_independent_search():
    assert not p7_search_window_completed(full_search=False, elapsed_seconds=300.001)


def test_all_live_search_gates_use_wall_window_not_last_step_proof():
    for gate in ("p7_2", "p7_3", "p7_4", "p7_5"):
        source = (REPO_ROOT / "tools" / f"wf_gate_{gate}_live.py").read_text()
        assert "p7_search_window_completed" in source
        assert "search_window_met" in source
        assert "last_search_step_completed_at" not in source
        assert "last_search_step_completed_elapsed_s" not in source
        assert "SEARCH_DEADLINE_NOT_MET" not in source
        assert "search_wall_s" in source

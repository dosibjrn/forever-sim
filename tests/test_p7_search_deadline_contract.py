"""P7.5 cold-search wall-window regression.

Only P7.5 requires a 300s independent cold search and stochastic holdout.
P7.2/P7.3/P7.4 genuinely pay changed native single-axis candidates without
a search deadline or frozen stochastic holdout (PROCESS v2.22).
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


def test_p75_cold_search_uses_wall_window_not_last_step_proof():
    source = (REPO_ROOT / "tools" / "wf_gate_p7_5_live.py").read_text()
    assert "p7_search_window_completed" in source
    assert "search_window_met" in source
    assert "search_wall_s" in source
    assert "last_search_step_completed_at" not in source
    assert "last_search_step_completed_elapsed_s" not in source
    assert "SEARCH_DEADLINE_NOT_MET" not in source


def test_p72_p73_axis_producers_do_not_gate_on_300s_or_stochastic_holdout():
    # Tests of source spelling are only a guard against reviving retired
    # acceptance predicates, not evidence that a native candidate ran.
    for gate in ("p7_2", "p7_3"):
        source = (REPO_ROOT / "tools" / f"wf_gate_{gate}_live.py").read_text()
        assert "winner_native_dps" in source
        assert "3" in source  # balanced native evaluations
        assert "last_search_step_completed_at" not in source
        assert "SEARCH_DEADLINE_NOT_MET" not in source

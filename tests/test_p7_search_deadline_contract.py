from pathlib import Path

from tools.wf_gate_coverage import p7_search_deadline_completed

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_search_step_must_finish_before_exact_300_second_deadline():
    start = 1_000.0
    deadline = start + 300.0
    assert p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_search_step_completed_at=deadline - 0.001,
        observed_at=deadline + 0.000127,
    )


def test_candidate_that_finishes_82ms_after_deadline_is_rejected():
    start = 1_000.0
    deadline = start + 300.0
    assert not p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_search_step_completed_at=deadline + 0.082,
        observed_at=deadline + 0.082,
    )


def test_post_deadline_observation_is_not_an_overrun_when_work_finished_on_time():
    start = 1_000.0
    deadline = start + 300.0
    # P7.4/P7.5 may sleep out an unused tail after their last search step.
    assert p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_search_step_completed_at=deadline - 0.5,
        observed_at=deadline + 0.000127,
    )


def test_short_or_malformed_search_windows_never_complete():
    start = 1_000.0
    deadline = start + 300.0
    common = {
        "search_start": start,
        "search_deadline": deadline,
        "last_search_step_completed_at": deadline - 1.0,
        "observed_at": deadline + 0.001,
    }
    assert not p7_search_deadline_completed(full_search=False, **common)
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "search_deadline": deadline - 1.0},
    )
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "last_search_step_completed_at": start},
    )
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "observed_at": deadline - 0.001},
    )


def test_all_live_search_gates_use_shared_strict_deadline_predicate():
    for gate in ("p7_2", "p7_3", "p7_4", "p7_5"):
        source = (REPO_ROOT / "tools" / f"wf_gate_{gate}_live.py").read_text()
        assert "p7_search_deadline_completed" in source
        assert "search_deadline_met" in source
        assert "300.0 <= search_wall_s <= 301.0" not in source
        assert "search_wall_s > 301.0" not in source
        assert "last_search_step_completed_at = time.monotonic()" in source

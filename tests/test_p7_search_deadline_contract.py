from tools.wf_gate_coverage import p7_search_deadline_completed


def test_paid_step_must_finish_before_exact_300_second_deadline():
    start = 1_000.0
    deadline = start + 300.0
    assert p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_paid_step_completed_at=deadline - 0.001,
        observed_at=deadline + 0.000127,
    )


def test_candidate_that_finishes_82ms_after_deadline_is_rejected():
    start = 1_000.0
    deadline = start + 300.0
    assert not p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_paid_step_completed_at=deadline + 0.082,
        observed_at=deadline + 0.082,
    )


def test_post_deadline_observation_is_not_an_overrun_when_work_finished_on_time():
    start = 1_000.0
    deadline = start + 300.0
    # P7.4/P7.5 may sleep out an unused tail after their last paid step.
    assert p7_search_deadline_completed(
        full_search=True,
        search_start=start,
        search_deadline=deadline,
        last_paid_step_completed_at=deadline - 0.5,
        observed_at=deadline + 0.000127,
    )


def test_short_or_malformed_search_windows_never_complete():
    start = 1_000.0
    deadline = start + 300.0
    common = {
        "search_start": start,
        "search_deadline": deadline,
        "last_paid_step_completed_at": deadline - 1.0,
        "observed_at": deadline + 0.001,
    }
    assert not p7_search_deadline_completed(full_search=False, **common)
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "search_deadline": deadline - 1.0},
    )
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "last_paid_step_completed_at": start},
    )
    assert not p7_search_deadline_completed(
        full_search=True,
        **{**common, "observed_at": deadline - 0.001},
    )

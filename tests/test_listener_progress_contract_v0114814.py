from src import listener


def test_listener_renders_service_authoritative_progress_best_and_stall_state():
    html=listener.DECISIONS_HTML
    assert "progress indeterminate" in html
    assert "best_so_far" in html
    assert "hb.stalled" in html
    assert "progress-fill" in html
    assert "runtime_message" in html
    # No progress inference from process logs in the browser.
    assert "stdout.log" not in html
    assert "stderr.log" not in html

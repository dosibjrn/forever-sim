from src.listener import DECISIONS_HTML


def test_processing_queue_has_relevance_hide_collapse_contract():
    html = DECISIONS_HTML
    assert "function queueRelevantJobs(jobs)" in html
    assert "['running','queued','paused']" in html
    assert "hiddenProcessingJobs" in html
    assert 'data-job-action="hide_local"' in html
    assert "hidden runs ·" in html
    assert 'data-history-toggle="1"' in html
    assert "processingHistoryExpanded" in html
    assert "completedForClass<2" in html
    assert "st==='failed'" in html
    # Active jobs bypass user-hidden history filtering.
    assert "active.concat(visibleHistory)" in html

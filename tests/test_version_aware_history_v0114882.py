from src.listener import DECISIONS_HTML
from src.service.models import JobRequest
from src.version import SOFTWARE_VERSION


def test_new_jobs_are_always_tagged_with_current_producer_version():
    req = JobRequest(ruleset="forever", class_name="druid", start_level=17, end_level=20)
    assert req.config["producer_version"] == SOFTWARE_VERSION

    # A clone/rerun assembled from an old request must be re-tagged as current code,
    # rather than inheriting the old producer identity.
    cloned = JobRequest(
        ruleset="forever",
        class_name="druid",
        start_level=17,
        end_level=20,
        config={"producer_version": "0.11.48.87", "workers": 2},
    )
    assert cloned.config["producer_version"] == SOFTWARE_VERSION
    assert cloned.config["workers"] == 2


def test_listener_hides_legacy_jobs_and_publications_by_default():
    html = DECISIONS_HTML
    assert f"CURRENT_SOFTWARE_VERSION='{SOFTWARE_VERSION}'" in html
    assert "function producerVersionFromRequest(req)" in html
    assert "function isCurrentProducer(req,currentVersion)" in html
    assert "const currentVersion=activeServiceVersion" in html
    assert "const currentHistory=historical.filter(j=>isCurrentProducer(j.request,currentVersion))" in html
    assert "const legacyHistory=historical.filter(j=>!isCurrentProducer(j.request,currentVersion))" in html
    assert "older-version run" in html
    assert "results from older/unknown versions" in html or "result${legacy.length===1?'':'s'} from older/unknown versions" in html
    assert "No publication from current v" in html
    assert "STALE · ${versionTag(producer)}" in html
    assert "data-publication-history-toggle" in html
    assert "legacyPublicationsExpanded" in html

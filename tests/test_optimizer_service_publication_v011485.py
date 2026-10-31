from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.service.models import JobRequest
from src.service.publication import PublicationError, current_publication, publish_attempt, resolve_published_path
from src.service.store import QueueStore
from src.v2.decision_dashboard import build_decision_payload


def _job(store: QueueStore, *, cls: str = "mage") -> tuple[dict, dict]:
    req = JobRequest(ruleset="forever", class_name=cls, start_level=20, end_level=20, endpoint_mode="fast")
    job, _ = store.enqueue(req)
    claimed = store.claim_next(owner="test", runs_root=store.path.parent / "runs", lease_seconds=60)
    assert claimed is not None
    return claimed


def _viewer(attempt: dict, cls: str, marker: str) -> Path:
    p = Path(attempt["run_root"]) / "state" / "games" / f"forever-{cls}" / "v2" / "viewer.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"running": False, "marker": marker, "views": {}}), encoding="utf-8")
    return p


def test_atomic_pointer_preserves_last_good_when_replacement_is_invalid(tmp_path: Path):
    project = tmp_path / "repo"; project.mkdir()
    store = QueueStore(project / "state" / "service" / "queue.sqlite3")
    job1, attempt1 = _job(store)
    _viewer(attempt1, "mage", "good")
    first = publish_attempt(project, job=job1, attempt=attempt1)
    store.record_publication(first)
    assert current_publication(project)["id"] == first["id"]

    store.finish_attempt(attempt1["id"], owner="test", outcome="completed")
    job2, attempt2 = _job(store, cls="druid")
    # No viewer => reject before current pointer is changed.
    with pytest.raises(PublicationError):
        publish_attempt(project, job=job2, attempt=attempt2)
    assert current_publication(project)["id"] == first["id"]
    assert json.loads(resolve_published_path(project, "games/forever-mage/v2/viewer.json").read_text())["marker"] == "good"


def test_publication_overlay_keeps_previous_class_artifacts(tmp_path: Path):
    project = tmp_path / "repo"; project.mkdir()
    store = QueueStore(project / "state" / "service" / "queue.sqlite3")

    mage_job, mage_attempt = _job(store, cls="mage")
    _viewer(mage_attempt, "mage", "mage-v1")
    endpoint = Path(mage_attempt["run_root"]) / "state" / "decisions" / "forever" / "endpoint_paths.json"
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    endpoint.write_text(json.dumps({"schema_version": 1, "classes": {"mage": {"marker": "published-endpoint"}}}), encoding="utf-8")
    pub1 = publish_attempt(project, job=mage_job, attempt=mage_attempt); store.record_publication(pub1)
    assert build_decision_payload(project_root=project)["endpoint_paths"]["mage"]["marker"] == "published-endpoint"
    store.finish_attempt(mage_attempt["id"], owner="test", outcome="completed")

    druid_job, druid_attempt = _job(store, cls="druid")
    _viewer(druid_attempt, "druid", "druid-v1")
    pub2 = publish_attempt(project, job=druid_job, attempt=druid_attempt); store.record_publication(pub2)

    assert current_publication(project)["id"] == pub2["id"]
    assert json.loads(resolve_published_path(project, "games/forever-druid/v2/viewer.json").read_text())["marker"] == "druid-v1"
    assert json.loads(resolve_published_path(project, "games/forever-mage/v2/viewer.json").read_text())["marker"] == "mage-v1"
    rows = store.list_publications()
    assert [r["id"] for r in rows[:2]] == [pub2["id"], pub1["id"]]


def test_shared_decision_artifacts_merge_classes_across_publications(tmp_path: Path):
    """A new class run must not erase named routes from previously published classes."""
    project = tmp_path / "repo"; project.mkdir()
    store = QueueStore(project / "state" / "service" / "queue.sqlite3")

    druid_job, druid_attempt = _job(store, cls="druid")
    _viewer(druid_attempt, "druid", "druid-v1")
    droot = Path(druid_attempt["run_root"]) / "state" / "decisions" / "forever"
    droot.mkdir(parents=True, exist_ok=True)
    for name in ("endpoint_paths", "spec_regret", "dual_spec", "spec_matrix"):
        (droot / f"{name}.json").write_text(json.dumps({"schema_version": 1, "classes": {"druid": {"marker": f"druid-{name}"}}}))
    pub1 = publish_attempt(project, job=druid_job, attempt=druid_attempt); store.record_publication(pub1)
    store.finish_attempt(druid_attempt["id"], owner="test", outcome="completed")

    hunter_job, hunter_attempt = _job(store, cls="hunter")
    _viewer(hunter_attempt, "hunter", "hunter-v1")
    hroot = Path(hunter_attempt["run_root"]) / "state" / "decisions" / "forever"
    hroot.mkdir(parents=True, exist_ok=True)
    for name in ("endpoint_paths", "spec_regret", "dual_spec", "spec_matrix"):
        (hroot / f"{name}.json").write_text(json.dumps({"schema_version": 1, "classes": {"hunter": {"marker": f"hunter-{name}"}}}))
    pub2 = publish_attempt(project, job=hunter_job, attempt=hunter_attempt); store.record_publication(pub2)

    payload = build_decision_payload(project_root=project)
    for key in ("endpoint_paths", "spec_regret", "dual_spec", "spec_matrix"):
        assert payload[key]["druid"]["marker"] == f"druid-{key}"
        assert payload[key]["hunter"]["marker"] == f"hunter-{key}"

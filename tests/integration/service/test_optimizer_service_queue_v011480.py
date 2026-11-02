from pathlib import Path

from src.service.models import JobRequest, JobState
from src.service.store import QueueStore


def req(cls="mage", start=11, end=60):
    return JobRequest(ruleset="forever", class_name=cls, start_level=start, end_level=end)


def test_queue_persists_across_store_instances_and_deduplicates_active_jobs(tmp_path: Path):
    db = tmp_path / "queue.sqlite3"
    a = QueueStore(db)
    first, created = a.enqueue(req())
    assert created is True
    same, created2 = a.enqueue(req())
    assert created2 is False
    assert same["id"] == first["id"]

    b = QueueStore(db)
    recovered = b.get(first["id"])
    assert recovered is not None
    assert recovered["state"] == "queued"
    assert recovered["request"]["class_name"] == "mage"


def test_queue_priority_reorder_and_control_transitions(tmp_path: Path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    mage, _ = store.enqueue(req("mage"), priority=0)
    pal, _ = store.enqueue(req("paladin", 10, 60), priority=0)
    dru, _ = store.enqueue(req("druid", 10, 60), priority=5)

    # Higher priority is first regardless of position; same-priority rows obey reorder.
    queued = store.list_jobs(states=["queued"])
    assert [j["id"] for j in queued][:1] == [dru["id"]]
    store.reorder([pal["id"], mage["id"]])
    queued = store.list_jobs(states=["queued"])
    assert [j["id"] for j in queued] == [dru["id"], pal["id"], mage["id"]]

    store.set_priority(mage["id"], 10)
    assert store.list_jobs(states=["queued"])[0]["id"] == mage["id"]

    paused = store.transition(pal["id"], JobState.PAUSED)
    assert paused["state"] == "paused"
    resumed = store.transition(pal["id"], JobState.QUEUED)
    assert resumed["state"] == "queued"
    cancelled = store.transition(pal["id"], JobState.CANCELLED)
    assert cancelled["state"] == "cancelled"


def test_completed_job_no_longer_blocks_identical_enqueue(tmp_path: Path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job, _ = store.enqueue(req())
    store.transition(job["id"], JobState.RUNNING)
    store.transition(job["id"], JobState.COMPLETED)
    fresh, created = store.enqueue(req())
    assert created is True
    assert fresh["id"] != job["id"]

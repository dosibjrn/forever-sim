"""Failed native sweep receipts are not disposable Actions storage."""
from pathlib import Path

import pytest

from tools.actions_artifact_pins import completed_run_candidates


WORKFLOW = ".github/workflows/native-joint-28-sweep.yml"
NAME = "native-joint-28-stage5-"
SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


def artifact(artifact_id: int, run_id: int) -> dict:
    return {
        "id": artifact_id,
        "name": NAME + SHA,
        "workflow_run": {"id": run_id, "head_sha": SHA},
    }


def run(run_id: int, conclusion, status: str = "completed") -> dict:
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "head_sha": SHA,
        "path": WORKFLOW,
        "event": "pull_request",
    }


@pytest.mark.parametrize("conclusion", [
    "failure", "cancelled", "timed_out", "skipped", "neutral",
    "action_required", None, False, {},
])
def test_failed_or_ambiguous_native_sweep_evidence_is_not_disposable(conclusion):
    ready, deferred = completed_run_candidates(
        [artifact(5, 100)], lambda run_id: run(run_id, conclusion),
        expected_workflow=WORKFLOW,
        expected_name_prefix=NAME,
        allowed_events=("pull_request", "push"),
        require_success_conclusion=True,
    )
    assert ready == []
    assert deferred == 1


def test_only_successful_finished_sweep_is_eligible_and_run_fetched_once():
    artifacts = [artifact(1, 101), artifact(2, 102),
                 artifact(3, 101), artifact(4, 103)]
    runs = {101: run(101, "success"),
            102: run(102, "failure"),
            103: run(103, None, status="in_progress")}
    fetched = []

    def fetch(run_id):
        fetched.append(run_id)
        return runs[run_id]

    ready, deferred = completed_run_candidates(
        artifacts, fetch,
        expected_workflow=WORKFLOW,
        expected_name_prefix=NAME,
        allowed_events=("pull_request", "push"),
        require_success_conclusion=True,
    )
    assert [entry["id"] for entry in ready] == [1, 3]
    assert deferred == 2
    assert fetched == [101, 102, 103]


def test_scheduled_gc_opts_into_success_only_deletion_before_planning():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml"
                ).read_text(encoding="utf-8")
    assert "require_success_conclusion=True" in workflow
    assert workflow.index("require_success_conclusion=True") < workflow.index(
        "planned = []")
    assert workflow.index("require_success_conclusion=True") < workflow.index(
        'request(f"artifacts/{aid}", "DELETE")')

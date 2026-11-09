"""The disposable Actions smoke must verify eventual deletion, not a stale first GET.

The only DELETE is for the uniquely named artifact created by this same run.
This is repository storage safety, never an M1 acceptance gate.
"""
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/actions-storage-clean-smoke.yml"
)


def test_disposable_smoke_polls_both_get_and_listing_after_204():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    delete = 'test "$status" = 204'
    retry = "for attempt in $(seq 1 12); do"
    get = 'if test "$status" != 200 && test "$status" != 404; then'
    listed = 'if test "$status" = 404 && jq -e --argjson id "$artifact_id"'
    succeeded = "PASS: created, listed and deleted own disposable artifact"
    exhausted = "FAIL: deletion did not converge after 12 checks"
    assert delete in workflow
    assert workflow.index(delete) < workflow.index(retry) < workflow.index(get)
    assert workflow.index(get) < workflow.index(listed)
    assert workflow.index(listed) < workflow.index(succeeded)
    assert exhausted in workflow
    assert 'sleep 5' in workflow


def test_disposable_smoke_deletes_only_own_uniquely_named_artifact():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "actions-storage-disposable-${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert '"repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/artifacts?per_page=100"' in workflow
    assert 'if length == 1 then .[0] else error("expected exactly one own artifact") end' in workflow
    assert '"$api"' in workflow
    assert "DELETE failed with HTTP $status" in workflow


def test_disposable_smoke_requires_explicit_dispatch():
    """Do not create a test artifact automatically on ordinary file edits."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:\n" in workflow
    assert "\n  push:\n" not in workflow
    assert "\n  schedule:\n" not in workflow

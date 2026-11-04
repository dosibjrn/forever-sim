from pathlib import Path


def test_m1_invalidation_workflow_is_merge_owned_and_provenance_scoped():
    workflow = Path(".github/workflows/m1-invalidate.yml").read_text()
    assert "issue_comment:" in workflow
    assert "github.actor == 'dosibjrn'" in workflow
    assert "github.event.issue.pull_request" in workflow
    assert "M1_INVALIDATION_REQUIRES_MERGED_PR_TO_MAIN" in workflow
    assert 'target" == "mage:30:unrestricted:P3"' in workflow
    assert 'expected_run" == "41764632715"' in workflow
    assert 'row.get("status") != "PARTIAL"' in workflow
    assert 'row.get("run_url", "")' in workflow
    assert "M1 - Merge-owned batch live gate recorder" in workflow
    assert "python tools/m1_progress.py" in workflow
    assert "--invalidate" in workflow
    assert "--plot-svg" in workflow
    assert "push origin HEAD:refs/heads/main" in workflow
    assert "force=true" not in workflow
    assert "wf_gate.py" not in workflow


def test_general_m1_recorder_does_not_share_invalidation_trigger():
    recorder = Path(".github/workflows/m1-on-demand-record.yml").read_text()
    assert "startsWith(github.event.comment.body, '/m1-run ')" in recorder
    assert "startsWith(github.event.comment.body, '/m1-invalidate ')" not in recorder

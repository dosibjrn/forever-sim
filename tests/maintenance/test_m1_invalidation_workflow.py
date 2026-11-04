"""Current single Merge-owned M1 workflow: recording and explicit invalidation.

The retired m1-invalidate.yml / one-off Mage receipt exception is not a
separate acceptance process. Test the actual main workflow's guardrails.
"""
from pathlib import Path


WORKFLOW = Path(".github/workflows/m1-on-demand-record.yml")


def test_explicit_invalidation_requires_owner_merged_pr_and_live_gate():
    workflow = WORKFLOW.read_text()
    assert "github.actor == 'dosibjrn'" in workflow
    assert "github.event.issue.pull_request" in workflow
    assert '[[ "$(jq -r \'.merged\' <<< "$pr")" == true' in workflow
    assert '$(jq -r \'.base.ref\' <<< "$pr")' in workflow
    assert '$(jq -r \'.base.repo.full_name\' <<< "$pr")' in workflow
    assert '[[ "$COMMENT_BODY" == \'/m1-invalidate \'* ]]' in workflow
    assert "Invalid active M1 invalidation target" in workflow
    assert "M1 invalidation requires a non-empty reason" in workflow
    assert 'python tools/m1_progress.py --invalidate "$class" "$level" "$spec" "$gate"' in workflow
    assert "--plot-svg docs/planning/M1_HISTORY.svg" in workflow


def test_general_m1_recorder_shares_one_dispatch_but_skips_gate_execution_on_invalidation():
    workflow = WORKFLOW.read_text()
    assert "startsWith(github.event.comment.body, '/m1-run ')" in workflow
    assert "startsWith(github.event.comment.body, '/m1-invalidate ')" in workflow
    assert "if: steps.targets.outputs.invalidate != 'true'" in workflow
    assert "python tools/wf_gate.py" in workflow
    assert 'if [[ "$INVALIDATE" == true ]]; then' in workflow


def test_invalidation_uses_fresh_main_and_nonforce_cas_not_a_stale_receipt():
    workflow = WORKFLOW.read_text()
    assert "git reset --hard FETCH_HEAD" in workflow
    assert 'parent="$(git rev-parse HEAD)"' in workflow
    assert 'current="$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"' in workflow
    assert 'if [[ "$current" != "$parent" ]]; then' in workflow
    assert "main advanced during invalidation" in workflow
    assert "force:false" in workflow
    assert "M1 invalidation retry limit exhausted" in workflow

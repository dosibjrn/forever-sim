"""Protect accepted and discussed evidence from automatic artifact GC."""
from pathlib import Path

import pytest

from tools.actions_artifact_pins import collect_local_references, record_references


ROOT = Path(__file__).resolve().parents[2]


def test_local_evidence_includes_merge_owned_ledger_and_document_links(tmp_path):
    for name, contents in {
        "OVERALL_PLAN.md": "plan https://github.com/o/r/actions/runs/12",
        "PROCESS.md": "",
        "README.md": "",
        "docs/planning/M1_PASSES.tsv":
            "run_url\nhttps://github.com/o/r/actions/runs/41504000590\n",
        "docs/repro.md": "https://github.com/o/r/actions/runs/34",
        "evidence/probe/replay.md": "https://github.com/o/r/actions/artifacts/901",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    runs, artifacts = collect_local_references(tmp_path)
    assert runs == {12, 34, 41504000590}
    assert artifacts == {901}


def test_issue_pr_and_inline_review_comments_are_pinned():
    runs, artifacts = set(), set()
    for body in (
        None,
        "PR discussion: https://github.com/o/r/actions/runs/123456",
        "Inline review: https://github.com/o/r/actions/artifacts/987654",
    ):
        record_references(body, runs, artifacts)
    assert runs == {123456}
    assert artifacts == {987654}


def test_missing_canonical_ledger_fails_closed(tmp_path):
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        collect_local_references(tmp_path)


def test_live_gc_fetches_comments_before_eligible_deletion():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8"
    )
    assert "from tools.actions_artifact_pins import collect_local_references, record_references" in workflow
    assert 'gh_collection("issues?state=all")' in workflow
    assert '"issues/comments?sort=created&direction=desc"' in workflow
    assert '"pulls/comments?sort=created&direction=desc"' in workflow
    assert workflow.index('record_references(comment.get("body")') < workflow.index('candidates = []')
    assert "if not apply:" in workflow

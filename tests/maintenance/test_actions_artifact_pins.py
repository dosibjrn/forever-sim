"""Protect accepted and discussed evidence from automatic artifact GC."""
from pathlib import Path

import pytest

from tools.actions_artifact_pins import artifact_run_id, collect_local_references, record_references


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



def test_machine_readable_receipts_pin_run_urls_and_bare_artifact_ids(tmp_path):
    """A JSON-only native evidence pin must survive an evidence-safe GC."""
    for name, contents in {
        "OVERALL_PLAN.md": "",
        "PROCESS.md": "",
        "README.md": "",
        "docs/planning/M1_PASSES.tsv": "",
        "docs/evidence/paid.json":
            '{"workflow_run": "https://github.com/o/r/actions/runs/456", "artifact_id": 9001}',
        "evidence/native/receipt.tsv":
            'run_url\\thttps://github.com/o/r/actions/runs/789\\n',
        "gate_evidence/warlock/L20/P3.json":
            '{"artifact_id": "9002", "irrelevant_number": 2222}',
        "gate_sources/warlock/selected.json":
            '{"run_url": "https://github.com/o/r/actions/runs/999"}',
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    runs, artifacts = collect_local_references(tmp_path)
    assert runs == {456, 789, 999}
    assert artifacts == {9001, 9002}


def test_retained_plaintext_log_pins_artifact_and_run_before_gc(tmp_path):
    """A raw paid receipt may retain the only URL to a native run artifact."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    log = tmp_path / "evidence/native/paid-hostile.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "Native receipt: https://github.com/o/r/actions/runs/42574670709/artifacts/12998142923\n",
        encoding="utf-8",
    )
    runs, artifacts = collect_local_references(tmp_path)
    assert runs == {42574670709}
    assert artifacts == {12998142923}


def test_numeric_actions_run_ids_in_json_pin_evidence_without_url():
    runs, artifacts = set(), set()
    record_references(
        '{"run_id": 42574670709, "workflow_run_id": "42573539316", '
        '"engine_build_run_id": 40969635587, "github_run_id": 42573178806, '
        '"run_id": "native-paid-1", "not_a_run_id": 777, '
        '"run_id": "123abc"}',
        runs, artifacts)
    assert runs == {42574670709, 42573539316, 40969635587, 42573178806}
    assert artifacts == set()



@pytest.mark.parametrize("damaged_path", [
    "docs/evidence/damaged-receipt.json",
    "evidence/native/damaged-paid.log",
    "PROCESS.md",
])
def test_malformed_utf8_paid_receipt_aborts_artifact_pin_scan(tmp_path, damaged_path):
    """Never delete on a lossy decode that can conceal an evidence pin."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    corrupt = tmp_path / damaged_path
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    # Replacement decoding would conceal artifact_id=9001, making GC
    # falsely treat its artifact as unreferenced.
    corrupt.write_bytes(b'{"artifact_id": \xff 9001, "run_id": 42574670709}')
    with pytest.raises(UnicodeDecodeError):
        collect_local_references(tmp_path)


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



def test_submitted_pr_review_body_pins_are_collected():
    # GitHub's /pulls/{number}/reviews bodies are distinct from /pulls/comments.
    runs, artifacts = set(), set()
    submitted_reviews = [
        {"body": "Keep this receipt: https://github.com/o/r/actions/runs/98766"},
        {"body": "Artifact: https://github.com/o/r/actions/artifacts/112233"},
        {"body": None},
    ]
    for review in submitted_reviews:
        record_references(review.get("body"), runs, artifacts)
    assert runs == {98766}
    assert artifacts == {112233}


def test_gc_scans_submitted_reviews_and_fails_closed_before_deleting():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8"
    )
    # A bare /reviews path must be paginated with '?' rather than '&'.
    assert 'separator = "&" if "?" in endpoint else "?"' in workflow
    assert 'all_prs = gh_collection("pulls?state=all")' in workflow
    assert 'for offset in range(0, len(all_prs), 20):' in workflow
    assert '"gh", "api", "graphql", "-f", f"query={query}"' in workflow
    assert 'payload.get("errors")' in workflow
    assert 'connection["pageInfo"]["hasNextPage"]' in workflow
    assert 'if connection["pageInfo"]["hasNextPage"]' in workflow
    assert 'gh_collection(f"pulls/{int(pr[\'number\'])}/reviews")' in workflow
    assert 'record_references(review.get("body"), pinned_runs, pinned_artifacts)' in workflow
    assert workflow.index('record_references(review.get("body")') < workflow.index(
        'candidates = []'
    )
    assert 'if p.get("state") == "open"' in workflow
    assert 'result = subprocess.run(["gh", "api", url], capture_output=True, text=True, check=True)' in workflow


def test_missing_canonical_ledger_fails_closed(tmp_path):
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        collect_local_references(tmp_path)


def test_live_gc_fetches_comments_before_eligible_deletion():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8"
    )
    assert "from tools.actions_artifact_pins import (artifact_run_id, collect_local_references, record_references)" in workflow
    assert 'gh_collection("issues?state=all")' in workflow
    assert '"issues/comments?sort=created&direction=desc"' in workflow
    assert '"pulls/comments?sort=created&direction=desc"' in workflow
    assert workflow.index('record_references(comment.get("body")') < workflow.index('candidates = []')
    assert "if not apply:" in workflow


@pytest.mark.parametrize("workflow_run", [
    None,
    {},
    [],
    "not-a-run",
    {"id": None},
    {"id": 0},
    {"id": -1},
    {"id": True},
    {"id": 42.0},
    {"id": "42"},
])
def test_artifact_without_trustworthy_run_provenance_cannot_be_pruned(workflow_run):
    assert artifact_run_id({"workflow_run": workflow_run}) is None


def test_artifact_run_id_accepts_only_positive_native_numeric_id():
    assert artifact_run_id({"workflow_run": {"id": 42, "head_branch": "main"}}) == 42


def test_live_gc_excludes_unknown_run_provenance_before_age_based_deletion():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8")
    assert "run_id = artifact_run_id(a)" in workflow
    assert 'elif run_id is None:' in workflow
    assert 'protected["unknown-run-provenance"] += 1' in workflow
    assert workflow.index('elif run_id is None:') < workflow.index('elif created(a) >= cutoff:')
    assert 'candidates.append(a)' in workflow

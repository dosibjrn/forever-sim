"""Protect accepted and discussed evidence from automatic artifact GC."""
from pathlib import Path

import pytest

from tools.actions_artifact_pins import (artifact_run_id, collect_local_references,
                                         completed_run_candidates, record_references, protects_open_pr_artifact)


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


def test_key_value_native_log_receipts_pin_evidence_before_gc(tmp_path):
    """Shell-style ID fields in retained native logs must protect run artifacts."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    log = tmp_path / "evidence/native/p4-hostile.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "artifact_id=12998142923 run_id=42574670709\n"
        "workflow_run_id=42573346755 github_run_id=42573178806 "
        "engine_build_run_id=40969635587\n",
        encoding="utf-8",
    )
    runs, artifacts = collect_local_references(tmp_path)
    assert artifacts == {12998142923}
    assert runs == {42574670709, 42573346755, 42573178806, 40969635587}


def test_key_value_pin_parser_ignores_unrelated_or_malformed_ids():
    runs, artifacts = set(), set()
    record_references(
        "not_artifact_id=88 not_run_id=99 artifact_id=0 "
        "artifact_id=123abc workflow_run_id=999abc run_id=0 "
        "github_run_id=notnumeric detached_id=1234",
        runs, artifacts,
    )
    assert runs == set()
    assert artifacts == set()


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



def test_python_repr_receipts_pin_artifacts_and_origin_runs(tmp_path):
    """Paid native .log dictionaries use single quotes, not JSON quoting."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    log = tmp_path / "evidence/native/paid-hostile.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "{'artifact_id': 12998142923, 'run_id': 42574670709, "
        "'workflow_run_id': '42573539316', 'not_a_run_id': 777, "
        "'artifact_id': '12998142924'}", encoding="utf-8")

    runs, artifacts = collect_local_references(tmp_path)
    assert runs == {42574670709, 42573539316}
    assert artifacts == {12998142923, 12998142924}


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
    assert "from tools.actions_artifact_pins import (artifact_run_id, collect_local_references," in workflow
    assert "completed_run_candidates, record_references, protects_open_pr_artifact)" in workflow
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


def test_gc_only_prunes_artifacts_from_finished_runs_and_fetches_each_run_once():
    """Queued/in-progress origin runs cannot lose their artifacts to scheduled GC."""
    artifacts = [
        {"id": 1, "workflow_run": {"id": 100}},
        {"id": 2, "workflow_run": {"id": 101}},
        {"id": 3, "workflow_run": {"id": 100}},
        {"id": 4, "workflow_run": {"id": 102}},
        {"id": 5, "workflow_run": {"id": 103}},
    ]
    states = {100: "completed", 101: "in_progress",
              102: "queued", 103: "waiting"}
    calls = []

    def fetch(run_id):
        calls.append(run_id)
        return {"id": run_id, "status": states[run_id]}

    finished, deferred = completed_run_candidates(artifacts, fetch)
    assert [row["id"] for row in finished] == [1, 3]
    assert deferred == 3
    assert calls == [100, 101, 102, 103]


@pytest.mark.parametrize("run_response", [
    None,
    {},
    {"id": 100},
    {"id": 100, "status": None},
    {"id": 100, "status": ""},
    {"id": 100, "status": True},
    {"id": "100", "status": "completed"},
    {"id": 101, "status": "completed"},
])
def test_gc_run_status_read_must_be_unambiguous_before_deleting(run_response):
    with pytest.raises(ValueError, match="completion status"):
        completed_run_candidates(
            [{"id": 1, "workflow_run": {"id": 100}}],
            lambda _run_id: run_response)


def test_gc_rejects_missing_origin_even_after_age_and_pin_checks():
    with pytest.raises(ValueError, match="valid run ID"):
        completed_run_candidates(
            [{"id": 1, "workflow_run": None}],
            lambda _run_id: {"id": 100, "status": "completed"})


def test_gc_run_status_api_error_aborts_whole_planning_pass():
    def fetch(run_id):
        if run_id == 101:
            raise OSError("Actions API unavailable")
        return {"id": run_id, "status": "completed"}

    with pytest.raises(OSError, match="unavailable"):
        completed_run_candidates(
            [{"workflow_run": {"id": 100}}, {"workflow_run": {"id": 101}}],
            fetch)


def test_scheduled_gc_looks_up_origin_completion_before_any_delete_plan():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8")
    assert "completed_run_candidates, record_references" in workflow
    assert 'status, payload = request(f"runs/{run_id}")' in workflow
    assert 'if status != 200:' in workflow
    assert "candidates, unfinished = completed_run_candidates(" in workflow
    assert 'expected_workflow=".github/workflows/native-joint-28-sweep.yml"' in workflow
    assert workflow.index("completed_run_candidates(") < workflow.index(
        "planned = []")
    assert workflow.index("completed_run_candidates(") < workflow.index(
        'request(f"artifacts/{aid}", "DELETE")')


def test_gc_refuses_name_colliding_artifact_from_other_workflow():
    """A stage5-looking name cannot authorize deletion from a different job."""
    artifact = {"id": 1, "name": "native-joint-28-stage5-" + "a" * 40,
                "workflow_run": {"id": 100}}
    expected = ".github/workflows/native-joint-28-sweep.yml"
    with pytest.raises(ValueError, match="workflow origin"):
        completed_run_candidates(
            [artifact],
            lambda run_id: {"id": run_id, "status": "completed",
                            "path": ".github/workflows/other.yml"},
            expected_workflow=expected)
    with pytest.raises(ValueError, match="workflow origin"):
        completed_run_candidates(
            [artifact],
            lambda run_id: {"id": run_id, "status": "completed"},
            expected_workflow=expected)


def test_gc_accepts_completed_artifacts_from_exact_sweep_workflow():
    expected = ".github/workflows/native-joint-28-sweep.yml"
    artifacts = [{"id": 1, "workflow_run": {"id": 100}},
                 {"id": 2, "workflow_run": {"id": 100}}]
    calls = []

    def fetch(run_id):
        calls.append(run_id)
        return {"id": run_id, "status": "completed", "path": expected}

    ready, deferred = completed_run_candidates(
        artifacts, fetch, expected_workflow=expected)
    assert [artifact["id"] for artifact in ready] == [1, 2]
    assert deferred == 0
    assert calls == [100]


def test_gc_accepts_matching_artifact_and_run_commit_provenance():
    """A finished sweep receipt is deletable only at its genuine originating SHA."""
    sha = "a" * 40
    prefix = "native-joint-28-stage5-"
    artifacts = [
        {"id": 1, "name": prefix + sha,
         "workflow_run": {"id": 100, "head_sha": sha}},
        {"id": 2, "name": prefix + sha,
         "workflow_run": {"id": 100, "head_sha": sha}},
    ]
    calls = []

    def fetch(run_id):
        calls.append(run_id)
        return {"id": run_id, "status": "completed",
                "path": ".github/workflows/native-joint-28-sweep.yml",
                "head_sha": sha}

    ready, deferred = completed_run_candidates(
        artifacts, fetch,
        expected_workflow=".github/workflows/native-joint-28-sweep.yml",
        expected_name_prefix=prefix)
    assert [a["id"] for a in ready] == [1, 2]
    assert deferred == 0
    assert calls == [100]


@pytest.mark.parametrize(("artifact_sha", "name_sha", "run_sha"), [
    ("b" * 40, "a" * 40, "a" * 40),
    ("a" * 40, "b" * 40, "a" * 40),
    ("a" * 40, "a" * 40, "b" * 40),
    (None, "a" * 40, "a" * 40),
    ("a" * 40, None, "a" * 40),
    ("a" * 40, "a" * 40, None),
    ("a" * 40, "a" * 40, "not-a-sha"),
])
def test_gc_refuses_mismatched_commit_provenance(
        artifact_sha, name_sha, run_sha):
    """Fail before deletion if artifact/run metadata or name are inconsistent."""
    prefix = "native-joint-28-stage5-"
    artifact = {
        "id": 1,
        "name": prefix + name_sha if name_sha is not None else None,
        "workflow_run": {"id": 100, "head_sha": artifact_sha},
    }
    with pytest.raises(ValueError, match="commit provenance"):
        completed_run_candidates(
            [artifact],
            lambda run_id: {"id": run_id, "status": "completed",
                            "path": ".github/workflows/native-joint-28-sweep.yml",
                            "head_sha": run_sha},
            expected_workflow=".github/workflows/native-joint-28-sweep.yml",
            expected_name_prefix=prefix)


def test_live_gc_requires_matching_artifact_and_run_sha_before_plan():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml"
                ).read_text(encoding="utf-8")
    assert 'expected_name_prefix="native-joint-28-stage5-"' in workflow
    assert workflow.index("completed_run_candidates(") < workflow.index("planned = []")



@pytest.mark.parametrize("event", [
    "workflow_dispatch", "repository_dispatch", "", None,
])
def test_gc_preserves_manually_requested_and_unknown_event_sweeps(event):
    """Full opt-in native evidence is never disposable PR CI after 72 hours."""
    sha = "a" * 40
    artifact = {
        "id": 15, "name": "native-joint-28-stage5-" + sha,
        "workflow_run": {"id": 100, "head_sha": sha},
    }
    ready, deferred = completed_run_candidates(
        [artifact],
        lambda run_id: {
            "id": run_id, "status": "completed",
            "path": ".github/workflows/native-joint-28-sweep.yml",
            "event": event, "head_sha": sha,
        },
        expected_workflow=".github/workflows/native-joint-28-sweep.yml",
        expected_name_prefix="native-joint-28-stage5-",
        allowed_events=("pull_request", "push"),
    )
    assert ready == []
    assert deferred == 1


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_gc_allows_only_normal_completed_sweep_ci_events(event):
    """Preserve cleanup of confirmed disposable CI while pinning opt-in runs."""
    sha = "b" * 40
    artifacts = [
        {"id": aid, "name": "native-joint-28-stage5-" + sha,
         "workflow_run": {"id": 99, "head_sha": sha}}
        for aid in (5, 6)
    ]
    fetched = []

    def fetch(run_id):
        fetched.append(run_id)
        return {
            "id": run_id, "status": "completed",
            "path": ".github/workflows/native-joint-28-sweep.yml",
            "event": event, "head_sha": sha,
        }

    ready, deferred = completed_run_candidates(
        artifacts, fetch,
        expected_workflow=".github/workflows/native-joint-28-sweep.yml",
        expected_name_prefix="native-joint-28-stage5-",
        allowed_events=("pull_request", "push"),
    )
    assert [a["id"] for a in ready] == [5, 6]
    assert deferred == 0
    assert fetched == [99]


def test_live_gc_does_not_delete_manually_opted_in_full_sweep_evidence():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml"
                ).read_text(encoding="utf-8")
    assert 'allowed_events=("pull_request", "push")' in workflow
    assert workflow.index('allowed_events=("pull_request", "push")') < workflow.index(
        "planned = []")


def test_human_artifact_prose_references_pin_issue_and_review_evidence():
    """A referenced artifact ID does not need a link or JSON property."""
    runs, artifacts = set(), set()
    record_references(
        "Native failure artifact #12940323970; replay artifact ID: 9876; "
        "additional ARTIFACT id=42. Not issue #1052 or 2026 logs.",
        runs, artifacts)
    assert runs == set()
    assert artifacts == {12940323970, 9876, 42}


def test_local_prose_only_artifact_id_survives_pin_scan(tmp_path):
    """The real GC scans retained markdown as well as GitHub discussions."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    evidence = tmp_path / "docs/evidence/p7/receipt.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "Preserved frozen holdout: artifact #12940323970; no link recorded.",
        encoding="utf-8")
    runs, artifacts = collect_local_references(tmp_path)
    assert runs == set()
    assert artifacts == {12940323970}


def test_artifact_prose_parser_does_not_pin_unlabelled_numbers():
    runs, artifacts = set(), set()
    record_references(
        "Issue #12940323970, run 42, version 9876, "
        "a generic artifact without an ID; malformed artifact #0.",
        runs, artifacts)
    assert runs == set()
    assert artifacts == set()


@pytest.mark.parametrize(("reference", "expected_run"), [
    ("Only available Actions run #42573178806 has the native receipt.", 42573178806),
    ("The workflow run ID: 42573346755 must be preserved.", 42573346755),
    ("Reproduce from run #42573539316 before removing diagnostics.", 42573539316),
    ("GitHub Actions run id=42574670709 is the original evidence.", 42574670709),
    ("Only recorded as Actions #42573178806; no URL exists.", 42573178806),
    ("github ACTIONS #42573346755 is the only native receipt.", 42573346755),
])
def test_explicit_prose_actions_run_ids_pin_origin_artifacts(reference, expected_run):
    """An issue/PR prose-only run reference must protect all of its artifacts."""
    runs, artifacts = set(), set()
    record_references(reference, runs, artifacts)
    assert runs == {expected_run}
    assert artifacts == set()


def test_actions_run_prose_requires_unambiguous_id_marker():
    """Do not invent a pin for generic counts, issue numbers or malformed IDs."""
    runs, artifacts = set(), set()
    record_references(
        "run 42; issue #1052; run #0; workflow run: 12345; "
        "2026 runs; version 9876; generic workflow 321; "
        "Actions 9876; Actions #0; Actions #123abc; Action #456",
        runs, artifacts)
    assert runs == set()
    assert artifacts == set()


@pytest.mark.parametrize(("origin", "protected"), [
    ({"id": 1, "head_branch": "work/unmerged"}, True),
    ({"id": 2, "head_branch": "main"}, False),
    ({"id": 3, "head_branch": "work/merged"}, False),
    ({"id": 4, "head_branch": None}, True),
    ({"id": 5}, True),
    ({"id": 6, "head_branch": 7}, True),
    (None, True),
])
def test_gc_keeps_all_open_pr_evidence_and_unknown_branch_origins(origin, protected):
    artifact = {"workflow_run": origin}
    assert protects_open_pr_artifact(artifact, {"work/unmerged"}) is protected


def test_gc_no_longer_limits_unmerged_branch_protection_to_two_artifacts():
    """An older unmerged native receipt must survive even when newer runs exist."""
    artifacts = [
        {"id": i, "workflow_run": {"id": 100 + i,
                                  "head_branch": "work/unmerged"}}
        for i in range(5)
    ]
    assert all(protects_open_pr_artifact(a, {"work/unmerged"}) for a in artifacts)
    assert not protects_open_pr_artifact(
        {"workflow_run": {"id": 200, "head_branch": "main"}},
        {"work/unmerged"})
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8")
    assert "if protects_open_pr_artifact(a, open_branches):" in workflow
    assert "active_branch_counts" not in workflow
    assert workflow.index("if protects_open_pr_artifact(") < workflow.index(
        "candidates = []")


@pytest.mark.parametrize(("artifact_branch", "actual_branch", "open_branches", "expected"), [
    ("work/open", "work/open", {"work/open"}, "protected"),
    ("main", "work/open", {"work/open"}, "mismatch"),
    ("main", "main", {"work/open"}, "eligible"),
    ("work/old", None, {"work/open"}, "protected"),
    (None, "work/open", {"work/open"}, "protected"),
])
def test_gc_confirms_open_pr_protection_with_authoritative_run_branch(
        artifact_branch, actual_branch, open_branches, expected):
    """A stale/mislabelled artifact branch cannot authorize evidence deletion."""
    sha = "a" * 40
    artifact = {
        "id": 31, "name": "native-joint-28-stage5-" + sha,
        "workflow_run": {
            "id": 900, "head_sha": sha, "head_branch": artifact_branch,
        },
    }
    def fetch(run_id):
        return {
            "id": run_id, "status": "completed", "conclusion": "success",
            "event": "pull_request", "run_attempt": 1,
            "path": ".github/workflows/native-joint-28-sweep.yml",
            "head_sha": sha, "head_branch": actual_branch,
        }
    options = dict(
        expected_workflow=".github/workflows/native-joint-28-sweep.yml",
        expected_name_prefix="native-joint-28-stage5-",
        allowed_events=("pull_request", "push"),
        require_success_conclusion=True,
        require_single_attempt=True,
        protected_branches=open_branches,
    )
    if expected == "mismatch":
        with pytest.raises(ValueError, match="artifact branch .* does not match run branch"):
            completed_run_candidates([artifact], fetch, **options)
    else:
        ready, deferred = completed_run_candidates([artifact], fetch, **options)
        assert ([a["id"] for a in ready], deferred) == (
            ([31], 0) if expected == "eligible" else ([], 1)
        )


def test_live_gc_enforces_branch_crosscheck_before_its_delete_plan():
    workflow = (ROOT / ".github/workflows/actions-storage-preventive-gc.yml"
                ).read_text(encoding="utf-8")
    assert "protected_branches=open_branches)" in workflow
    assert workflow.index("protected_branches=open_branches)") < workflow.index(
        "planned = []")
    assert workflow.index("planned = []") < workflow.index(
        'request(f"artifacts/{aid}", "DELETE")')


def test_unquoted_colon_receipts_pin_artifacts_and_runs_before_gc(tmp_path):
    """YAML-style evidence IDs must survive the same complete local pin scan."""
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    receipt = tmp_path / "evidence/native/paid-world-receipt.log"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        "artifact_id: 12998142923\n"
        "workflow_run_id: 42574670709\n"
        "run_id: '42573539316'\n"
        "github_run_id: \"42573346755\"\n"
        "engine_build_run_id: 40969635587\n",
        encoding="utf-8",
    )
    runs, artifacts = collect_local_references(tmp_path)
    assert artifacts == {12998142923}
    assert runs == {42574670709, 42573539316, 42573346755, 40969635587}


def test_colon_pin_parser_rejects_unrelated_and_malformed_ids():
    runs, artifacts = set(), set()
    record_references(
        "not_artifact_id: 88 xworkflow_run_id: 99 "
        "artifact_id: 0 artifact_id: 123abc artifact_id: 321-abc "
        "run_id: 0 run_id: 999abc not_run_id: 123 "
        "artifact_id: 123 # valid explicit receipt ID\n",
        runs, artifacts,
    )
    assert runs == set()
    assert artifacts == {123}

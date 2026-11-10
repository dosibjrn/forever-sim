"""Collect Actions evidence references before evidence-safe artifact pruning.

References in the Merge-owned M1 ledger, retained project documents and
issue/PR discussion protect artifacts. This module never deletes artifacts.
"""
from __future__ import annotations

from pathlib import Path
import re

_RUN = re.compile(r"actions/runs/(\d+)")
_ARTIFACT = re.compile(r"/artifacts/(\d+)")
# Accepted native receipts may preserve an artifact only by its JSON ID.
# Retained .log receipts may contain Python repr dictionaries with single
# quotes rather than strict JSON. Both must pin before irreversible GC.
_ARTIFACT_ID_FIELD = re.compile(
    r"""["']artifact_id["']\s*:\s*["']?([1-9]\d*)["']?\s*(?=[,}])""")
# Human prose in retained evidence and issue/PR discussion often records only
# "artifact #123" or "artifact ID: 123", without a URL or JSON field.
# Those are explicit artifact references and must pin the original evidence.
_ARTIFACT_PROSE_ID = re.compile(
    r"\bartifact\s+(?:#\s*|id\s*[:=#]?\s*)([1-9]\d*)\b",
    flags=re.IGNORECASE,
)
# Machine-readable receipts can reference a workflow run only by numeric ID.
# Non-numeric internal runtime-proof IDs must not be treated as Actions runs.
_RUN_ID_FIELD = re.compile(
    r"""["'](?:run_id|workflow_run_id|github_run_id|engine_build_run_id)["']\s*:\s*"""
    r"""(?:["']([1-9]\d*)["']|([1-9]\d*))\s*(?=[,}])""")

# Raw CI and native receipt logs also use key=value IDs (not JSON or
# prose: "artifact_id=123", "workflow_run_id=456"). Pin these before GC.
# Explicit field names avoid guessing from unrelated numbers.
_ARTIFACT_ASSIGNMENT_ID = re.compile(r"\bartifact_id\s*=\s*([1-9]\d*)\b")
_RUN_ASSIGNMENT_ID = re.compile(
    r"\b(?:run_id|workflow_run_id|github_run_id|engine_build_run_id)"
    r"\s*=\s*([1-9]\d*)\b"
)

# Retained YAML/plain-text receipts can use unquoted colon keys rather than
# JSON-quoted keys or shell key=value pairs. Without these patterns GC can
# silently discard the only artifact/run referenced by a paid receipt.
# Reject prefixes (not_artifact_id), zero and malformed numeric suffixes.
_ARTIFACT_COLON_ID = re.compile(
    r"""(?<!\w)artifact_id\s*:\s*["']?([1-9]\d*)["']?(?=$|[\s,}\]])""")
_RUN_COLON_ID = re.compile(
    r"""(?<!\w)(?:run_id|workflow_run_id|github_run_id|engine_build_run_id)"""
    r"""\s*:\s*["']?([1-9]\d*)["']?(?=$|[\s,}\]])""")

# Issue/PR discussions also cite Actions runs without URLs or JSON fields:
# "Actions run #123", "workflow run ID: 123", and "run #123".
# Require the explicit hash or ID marker; generic "run 42" is ambiguous.
_RUN_PROSE_ID = re.compile(
    r"\b(?:(?:github\s+)?(?:actions?\s+)?(?:workflow\s+)?)run\s+"
    r"(?:#\s*|id\s*[:=#]?\s*)([1-9]\d*)\b",
    flags=re.IGNORECASE,
)

# Issue/PR comments sometimes shorthand a GitHub Actions run as
# "Actions #123", without "run" or a URL. A run-only evidence reference
# must pin its origin artifacts as safely as an Actions URL does.
_ACTIONS_NUMBER = re.compile(r"\bactions\s+#\s*([1-9]\d*)\b", re.IGNORECASE)

# A retained P7.5 receipt cites "Actions run 41108670861 artifact
# 13002676953" without a URL, hash, or ID key. Protect this concrete
# source-evidence syntax, but do not treat ordinary short run/artifact
# counts as GitHub IDs.
_ACTIONS_PLAIN_RUN_ID = re.compile(
    r"\bactions\s+run\s+([1-9]\d{7,})\b", flags=re.IGNORECASE)
_ARTIFACT_PLAIN_ID = re.compile(
    r"\bartifact\s+([1-9]\d{7,})\b", flags=re.IGNORECASE)

# Retained paid/native receipts and PR discussions can give a reproducible
# GitHub CLI command instead of a link: "gh run view 123" or "gh run download
# 123". Both identify an originating Actions run whose artifacts must be pinned.
# Require the explicit command and numeric argument; "gh run list" and
# ordinary numerical counts are not evidence references.
_GH_RUN_COMMAND = re.compile(
    r"\bgh\s+run\s+(?:view|download)\s+([1-9]\d*)\b",
    flags=re.IGNORECASE,
)


def record_references(body: str | None, runs: set[int], artifacts: set[int]) -> None:
    """Add referenced IDs from an issue, review, ledger or document."""
    text = body or ""
    runs.update(int(match) for match in _RUN.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_ID_FIELD.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_PROSE_ID.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_ASSIGNMENT_ID.findall(text))
    runs.update(int(match) for match in _RUN_ASSIGNMENT_ID.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_COLON_ID.findall(text))
    runs.update(int(match) for match in _RUN_COLON_ID.findall(text))
    runs.update(int(quoted or bare) for quoted, bare in _RUN_ID_FIELD.findall(text))
    runs.update(int(match) for match in _RUN_PROSE_ID.findall(text))
    runs.update(int(match) for match in _ACTIONS_NUMBER.findall(text))
    runs.update(int(match) for match in _ACTIONS_PLAIN_RUN_ID.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_PLAIN_ID.findall(text))
    runs.update(int(match) for match in _GH_RUN_COMMAND.findall(text))


def artifact_run_id(artifact: dict) -> int | None:
    """Return a usable GitHub Actions run ID; unknown provenance stays protected.

    Artifact inventory can have missing or malformed workflow_run metadata.
    Without this check an unpinned-run test might silently use ID zero.
    """
    workflow_run = artifact.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return None
    run_id = workflow_run.get("id")
    return run_id if type(run_id) is int and run_id > 0 else None




def unmerged_pr_branch_refs(pull_requests: list[dict], repository: str) -> set[str]:
    """Protect open and closed-without-merge local PR origin branches.

    A closed unmerged PR may still own unique native/failure artifacts.
    GitHub's pulls?state=all exposes merged_at for merged PRs; state=closed
    alone does not make evidence disposable.
    """
    branches: set[str] = set()
    owner = repository.partition("/")[0]
    for pr in pull_requests:
        if pr.get("merged_at") is not None:
            continue
        head = pr.get("head")
        if not isinstance(head, dict):
            continue
        head_repo = head.get("repo")
        if isinstance(head_repo, dict):
            if head_repo.get("full_name") != repository:
                continue
        else:
            # GitHub can return head.repo=null after a local PR branch is
            # deleted. Its owner:branch label still identifies the source;
            # dropping it here would let GC erase an unmerged native receipt.
            label = head.get("label")
            if not isinstance(label, str) or not label.startswith(owner + ":"):
                continue
            ref = head.get("ref")
            if not isinstance(ref, str) or not ref or label != f"{owner}:{ref}":
                raise ValueError("unmerged local PR has no trustworthy head branch")
        ref = head.get("ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("unmerged local PR has no trustworthy head branch")
        branches.add(ref)
    return branches


def protects_open_pr_artifact(artifact: dict, open_branches: set[str]) -> bool:
    """Protect every still-unmerged PR-branch artifact, not only its latest two.

    An absent or malformed origin branch is not proof that no open PR owns
    the receipt; keep it rather than authorize irreversible deletion.
    """
    origin = artifact.get("workflow_run")
    if not isinstance(origin, dict):
        return True
    branch = origin.get("head_branch")
    return not isinstance(branch, str) or not branch or branch in open_branches


def completed_run_candidates(
        candidates: list[dict], fetch_run, *,
        expected_workflow: str | None = None,
        expected_name_prefix: str | None = None,
        allowed_events: tuple[str, ...] | None = None,
        require_success_conclusion: bool = False,
        require_single_attempt: bool = False,
        protected_branches: set[str] | None = None) -> tuple[list[dict], int]:
    """Keep only artifacts from confirmed completed workflow runs.

    Query each distinct originating run once. A missing/malformed/mismatched
    response or unexpected workflow origin aborts planning before any DELETE;
    queued, in-progress, waiting and other non-completed runs stay protected.
    The optional origin constraint prevents name-colliding artifacts from a
    different workflow being deleted as if they were sweep diagnostics.
    When a commit-labelled name prefix is supplied, also require the artifact
    name, embedded origin SHA and fetched run SHA to agree, before deletion.
    Restricting allowed_events preserves deliberately manually dispatched full
    evidence artifacts; absent or unknown event metadata is deferred safely.
    When require_success_conclusion is set, retain all non-success outcomes:
    failed native-sweep artifacts can be the only available failure evidence.
    A missing or ambiguous conclusion also fails closed. When single-attempt
    protection is enabled, an absent/ambiguous run_attempt or a rerun is kept:
    the latest successful conclusion cannot classify earlier attempt artifacts.
    With protected_branches, verify the artifact's branch against the fetched
    authoritative run before considering deletion. Unknown branches stay
    protected; mismatched branch claims abort the entire plan fail-closed.
    """
    runs_by_id: dict[int, dict] = {}
    ready: list[dict] = []
    deferred = 0
    for artifact in candidates:
        run_id = artifact_run_id(artifact)
        if run_id is None:
            raise ValueError("cannot delete an artifact without a valid run ID")
        if run_id not in runs_by_id:
            run = fetch_run(run_id)
            if (not isinstance(run, dict)
                    or type(run.get("id")) is not int
                    or run["id"] != run_id
                    or not isinstance(run.get("status"), str)
                    or not run["status"]):
                raise ValueError(f"run {run_id}: missing or mismatched completion status")
            if expected_workflow is not None and run.get("path") != expected_workflow:
                raise ValueError(
                    f"run {run_id}: workflow origin {run.get('path')!r} "
                    f"does not match {expected_workflow!r}")
            runs_by_id[run_id] = run
        run = runs_by_id[run_id]
        if protected_branches is not None:
            origin_branch = artifact["workflow_run"].get("head_branch")
            actual_branch = run.get("head_branch")
            if (not isinstance(origin_branch, str) or not origin_branch
                    or not isinstance(actual_branch, str) or not actual_branch):
                # No authoritative branch identity: never delete an artifact.
                deferred += 1
                continue
            if origin_branch != actual_branch:
                raise ValueError(
                    f"run {run_id}: artifact branch {origin_branch!r} "
                    f"does not match run branch {actual_branch!r}")
            if actual_branch in protected_branches:
                deferred += 1
                continue
        if allowed_events is not None and run.get("event") not in allowed_events:
            # A manual sweep explicitly opted into retaining full native
            # request/response evidence. Do not treat it as disposable PR CI.
            deferred += 1
            continue
        if require_single_attempt and (
                type(run.get("run_attempt")) is not int
                or run["run_attempt"] != 1):
            # The run ID survives retries. A later successful attempt does
            # not make artifacts from earlier failed attempts disposable.
            deferred += 1
            continue
        if expected_name_prefix is not None:
            run_sha = run.get("head_sha")
            origin_sha = artifact["workflow_run"].get("head_sha")
            artifact_name = artifact.get("name")
            if (not isinstance(run_sha, str)
                    or re.fullmatch(r"[0-9a-f]{40}", run_sha) is None
                    or origin_sha != run_sha
                    or artifact_name != f"{expected_name_prefix}{run_sha}"):
                raise ValueError(
                    f"run {run_id}: artifact commit provenance does not match "
                    "origin run HEAD and artifact name")
        if run["status"] == "completed" and (
                not require_success_conclusion or run.get("conclusion") == "success"):
            ready.append(artifact)
        else:
            # A failed/cancelled native sweep may have the only failure
            # reproduction; only a positive success can make it disposable.
            deferred += 1
    return ready, deferred


def collect_local_references(root: Path) -> tuple[set[int], set[int]]:
    """Read evidence in working tree; unreadable files fail closed."""
    runs: set[int] = set()
    artifacts: set[int] = set()
    # Machine-readable and raw plaintext receipts can hold the sole pin to
    # a paid native run. A file extension is not evidence of disposability.
    # Read them before deciding that an artifact is disposable.
    for folder in ("docs", "evidence", "gate_evidence", "gate_sources"):
        # Raw retained gate/paid run logs can be the sole evidence link.
        # Treat a damaged log like a damaged JSON receipt: abort deletion.
        for pattern in ("*.md", "*.json", "*.jsonl", "*.yaml", "*.yml", "*.tsv", "*.log", "*.txt"):
            for path in (root / folder).rglob(pattern):
                record_references(path.read_text(encoding="utf-8"),
                                  runs, artifacts)
    # Native route observations are live product inputs and can be the only
    # remaining references to paid 100-mob runs or their source artifacts.
    # Scan this bounded receipt pattern, not the large general game-data tree.
    for path in (root / "data").glob("*/native_route_observations.json"):
        record_references(path.read_text(encoding="utf-8"), runs, artifacts)
    # Workflow definitions can be the sole remaining pointer to a paid
    # predecessor artifact used by an active native route. Do not delete it
    # merely because the artifact URL lives in executable YAML, not prose.
    for pattern in ("*.yml", "*.yaml"):
        for path in (root / ".github/workflows").rglob(pattern):
            record_references(path.read_text(encoding="utf-8"),
                              runs, artifacts)
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        record_references((root / name).read_text(encoding="utf-8"),
                          runs, artifacts)
    return runs, artifacts

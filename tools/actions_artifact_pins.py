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
_ARTIFACT_ID_FIELD = re.compile(r'"artifact_id"\s*:\s*"?([0-9]+)"?')
# Machine-readable receipts can reference a workflow run only by numeric ID.
# Non-numeric internal runtime-proof IDs must not be treated as Actions runs.
_RUN_ID_FIELD = re.compile(
    r'"(?:run_id|workflow_run_id|github_run_id|engine_build_run_id)"\s*:\s*'
    r'(?:"([1-9]\d*)"|([1-9]\d*))\s*(?=[,}])')


def record_references(body: str | None, runs: set[int], artifacts: set[int]) -> None:
    """Add referenced IDs from an issue, review, ledger or document."""
    text = body or ""
    runs.update(int(match) for match in _RUN.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT_ID_FIELD.findall(text))
    runs.update(int(quoted or bare) for quoted, bare in _RUN_ID_FIELD.findall(text))


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



def completed_run_candidates(
        candidates: list[dict], fetch_run, *,
        expected_workflow: str | None = None,
        expected_name_prefix: str | None = None,
        allowed_events: tuple[str, ...] | None = None) -> tuple[list[dict], int]:
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
        if allowed_events is not None and run.get("event") not in allowed_events:
            # A manual sweep explicitly opted into retaining full native
            # request/response evidence. Do not treat it as disposable PR CI.
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
        if run["status"] == "completed":
            ready.append(artifact)
        else:
            deferred += 1
    return ready, deferred


def collect_local_references(root: Path) -> tuple[set[int], set[int]]:
    """Read evidence in working tree; unreadable files fail closed."""
    runs: set[int] = set()
    artifacts: set[int] = set()
    # Machine-readable receipts also contain the only link/ID to some paid
    # native runs. Read them before deciding that an artifact is disposable.
    for folder in ("docs", "evidence", "gate_evidence", "gate_sources"):
        # Raw retained gate/paid run logs can be the sole evidence link.
        # Treat a damaged log like a damaged JSON receipt: abort deletion.
        for pattern in ("*.md", "*.json", "*.tsv", "*.log"):
            for path in (root / folder).rglob(pattern):
                record_references(path.read_text(encoding="utf-8"),
                                  runs, artifacts)
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        record_references((root / name).read_text(encoding="utf-8"),
                          runs, artifacts)
    return runs, artifacts

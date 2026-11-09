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


def collect_local_references(root: Path) -> tuple[set[int], set[int]]:
    """Read evidence in working tree; unreadable files fail closed."""
    runs: set[int] = set()
    artifacts: set[int] = set()
    # Machine-readable receipts also contain the only link/ID to some paid
    # native runs. Read them before deciding that an artifact is disposable.
    for folder in ("docs", "evidence", "gate_evidence", "gate_sources"):
        for pattern in ("*.md", "*.json", "*.tsv"):
            for path in (root / folder).rglob(pattern):
                record_references(path.read_text(encoding="utf-8", errors="replace"),
                                  runs, artifacts)
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        record_references((root / name).read_text(encoding="utf-8", errors="replace"),
                          runs, artifacts)
    return runs, artifacts

"""Collect Actions evidence references before evidence-safe artifact pruning.

References in the Merge-owned M1 ledger, retained project documents and
issue/PR discussion protect artifacts. This module never deletes artifacts.
"""
from __future__ import annotations

from pathlib import Path
import re

_RUN = re.compile(r"actions/runs/(\d+)")
_ARTIFACT = re.compile(r"/artifacts/(\d+)")


def record_references(body: str | None, runs: set[int], artifacts: set[int]) -> None:
    """Add referenced IDs from an issue, review, ledger or document."""
    text = body or ""
    runs.update(int(match) for match in _RUN.findall(text))
    artifacts.update(int(match) for match in _ARTIFACT.findall(text))


def collect_local_references(root: Path) -> tuple[set[int], set[int]]:
    """Read evidence in working tree; unreadable files fail closed."""
    runs: set[int] = set()
    artifacts: set[int] = set()
    for folder in ("docs", "evidence"):
        for path in (root / folder).rglob("*.md"):
            record_references(path.read_text(encoding="utf-8", errors="replace"),
                              runs, artifacts)
    for name in ("OVERALL_PLAN.md", "PROCESS.md", "README.md",
                 "docs/planning/M1_PASSES.tsv"):
        record_references((root / name).read_text(encoding="utf-8", errors="replace"),
                          runs, artifacts)
    return runs, artifacts

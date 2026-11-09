"""Artifact upload steps must not silently inherit the 90-day Actions default.

This is an operational storage regression, not a Warcraft gate or an
additional M1 acceptance predicate. Native no-record evidence is still uploaded.
"""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UPLOAD = re.compile(r"\buses:\s*actions/upload-artifact@v4\s*$")
RETENTION = re.compile(r"\s*retention-days:\s*(\d+)\s*$")


def test_actions_upload_steps_set_explicit_bounded_retention():
    uploads = 0
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        lines = workflow.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not UPLOAD.search(line):
                continue
            uploads += 1
            indent = len(line) - len(line.lstrip(" "))
            step_body = []
            for following in lines[index + 1:]:
                if (following.strip()
                        and not following.lstrip().startswith("#")
                        and len(following) - len(following.lstrip(" ")) <= indent):
                    break
                step_body.append(following)
            declared = [int(match.group(1))
                        for row in step_body
                        if (match := RETENTION.fullmatch(row))]
            assert len(declared) == 1, (
                f"{workflow.relative_to(ROOT)}:{index + 1}: "
                "upload-artifact must declare retention-days exactly once"
            )
            assert 1 <= declared[0] <= 30, (
                f"{workflow.relative_to(ROOT)}:{index + 1}: "
                "use a deliberate retention of 1–30 days, not the 90-day default"
            )
    assert uploads > 0

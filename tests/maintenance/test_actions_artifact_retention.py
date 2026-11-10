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
                if following.strip() and not following.lstrip().startswith("#"):
                    following_indent = len(following) - len(following.lstrip(" "))
                    # Same-indent "with:" still belongs to this upload step.
                    # Stop at the next list step or a containing YAML key.
                    if (following_indent < indent
                            or (following_indent == indent
                                and following.lstrip().startswith("- "))):
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


def test_rust_pin_pr_no_record_p3_uploads_expire_after_seven_days():
    """Repeatable no-record native P3 PR diagnostics should not occupy a month.

    This does not prune accepted M1 receipts or issue-pinned evidence; it only
    bounds new artifacts from the selected-Rust-pin verification workflow.
    """
    workflow = ROOT / ".github/workflows/rust-submodule-verify.yml"
    lines = workflow.read_text(encoding="utf-8").splitlines()
    upload_indices = [index for index, line in enumerate(lines)
                      if UPLOAD.search(line)]
    assert len(upload_indices) == 3, "review retention when adding a PR artifact"
    for index in upload_indices:
        indent = len(lines[index]) - len(lines[index].lstrip(" "))
        step_body = []
        for following in lines[index + 1:]:
            if following.strip() and not following.lstrip().startswith("#"):
                following_indent = len(following) - len(following.lstrip(" "))
                if (following_indent < indent or
                        (following_indent == indent and
                         following.lstrip().startswith("- "))):
                    break
            step_body.append(following)
        retention = [int(match.group(1)) for row in step_body
                     if (match := RETENTION.fullmatch(row))]
        assert retention == [7], f"{workflow.name}:{index + 1}: expected seven days"

"""Cancel superseded Warlock forwarding-only PR checks, not native-paid work.

The historical Warlock native optimizer forwarding workflow is PR-only and
runs a cheap Python suite. Updating the PR must not queue or finish a stale
head, while paid native/world runs remain in separate workflows.
"""
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/warlock-native-optimizer-regressions.yml"
)


def test_fast_warlock_optimizer_pr_checks_cancel_superseded_heads():
    source = WORKFLOW.read_text(encoding="utf-8")
    events = source.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "  pull_request:\n" in events
    assert "  workflow_dispatch:" not in events
    assert "  push:" not in events
    assert "  schedule:" not in events
    assert (
        "group: warlock-native-optimizer-fast-pr-"
        "${{ github.event.pull_request.number }}"
    ) in source
    assert "cancel-in-progress: true" in source
    assert "cargo build" not in source
    assert "actions/upload-artifact" not in source
    assert "tests/test_work2_warlock_native_cold.py" in source

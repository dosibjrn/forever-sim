"""Invalid manual 100-mob comparison inputs must fail before any paid setup.

This tests the executable Bash from the workflow, not a duplicate validator.
The native engine still independently verifies its checked-out source SHA.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/native-paid-route-regressions.yml")


def _real_preflight() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = "      - name: Preflight bounded paid comparison inputs\n"
    end = "      - name: Checkout exact comparison source\n"
    assert text.count(start) == text.count(end) == 1
    assert text.index(start) < text.index(end)
    stanza = text.split(start, 1)[1].split(end, 1)[0]
    body = stanza.split("        run: |\n", 1)[1]
    return "\n".join(
        line[10:] for line in body.splitlines()
        if line.startswith("          ")
    ) + "\n"


def test_cross_tree_paid_request_is_checked_before_fetch_and_build():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("Preflight bounded paid comparison inputs") < text.index(
        "Checkout exact comparison source")
    assert text.index("Preflight bounded paid comparison inputs") < text.index(
        "Checkout exact native authority")
    assert text.index("Verify exact checked-out native revision") < text.index(
        "Build exact Rust executor")
    assert 'test "$(git -C engine rev-parse HEAD)" = "$SELECTED_RUST_SHA"' in text
    source = _real_preflight()
    assert "set -euo pipefail" in source
    assert subprocess.run(["bash", "-n"], input=source, text=True,
                          capture_output=True, check=False).returncode == 0


@pytest.mark.parametrize(("name", "value"), [
    ("SELECTED_RUST_SHA", "main"),
    ("SELECTED_RUST_SHA", "A" * 40),
    ("PREDECESSOR_ARTIFACT_ID", "0"),
    ("PREDECESSOR_ARTIFACT_ID", "5bad"),
    ("PREDECESSOR_BINARY_SHA256", "not-a-binary"),
    ("FROM_LEVEL", "9"),
    ("FROM_LEVEL", "60"),
    ("FROM_LEVEL", "20.5"),
    ("MAX_PROPOSALS", "0"),
    ("MAX_PROPOSALS", "1001"),
    ("MAX_FINALISTS", "0"),
    ("MAX_FINALISTS", "7"),
])
def test_invalid_paid_request_fails_before_any_checkout(name, value):
    env = {
        **os.environ,
        "SELECTED_RUST_SHA": "a" * 40,
        "PREDECESSOR_ARTIFACT_ID": "12345",
        "PREDECESSOR_BINARY_SHA256": "b" * 64,
        "FROM_LEVEL": "47",
        "MAX_PROPOSALS": "240",
        "MAX_FINALISTS": "3",
        name: value,
    }
    result = subprocess.run(["bash", "-c", _real_preflight()],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0, (name, value, result.stdout, result.stderr)


def test_valid_paid_request_passes_cheap_preflight():
    env = {
        **os.environ,
        "SELECTED_RUST_SHA": "a" * 40,
        "PREDECESSOR_ARTIFACT_ID": "12345",
        "PREDECESSOR_BINARY_SHA256": "b" * 64,
        "FROM_LEVEL": "47",
        "MAX_PROPOSALS": "240",
        "MAX_FINALISTS": "3",
    }
    result = subprocess.run(["bash", "-c", _real_preflight()],
                            env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

"""The M0.6 original Rust-paid comparison must never be an automatic PR job.

The initial two-sample native measurement is preserved in Actions #43072652469.
New original-paid decisions are opt-in; ordinary PR changes still run fast tests.
"""
from pathlib import Path
import re


WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/native-paid-route-regressions.yml")


def _job(name: str, text: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][a-zA-Z0-9_-]*:|\Z)",
        text,
    )
    assert match, f"missing workflow job: {name}"
    return match.group(1)


def test_original_native_payment_needs_explicit_boolean_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")
    dispatch = text.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    input_block = dispatch.split("      run_m06_original:\n", 1)[1]
    assert "        type: boolean\n" in input_block
    assert "        default: false\n" in input_block
    paid_job = _job("work2-m06-original-native", text)
    assert (
        "    if: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.run_m06_original == true }}\n"
    ) in paid_job
    assert "cargo build --locked" in paid_job
    assert "python -m src.v2.runner optimize" in paid_job


def test_native_paid_pr_regressions_remain_fast_and_not_paid():
    text = WORKFLOW.read_text(encoding="utf-8")
    fast_job = _job("native-paid-route", text)
    assert "    if: github.event_name == 'pull_request'\n" in fast_job
    assert "python -m pytest -q" in fast_job
    assert "cargo build" not in fast_job
    assert "python -m src.v2.runner optimize" not in fast_job

def test_only_superseded_fast_pr_runs_are_cancelled():
    text = WORKFLOW.read_text(encoding="utf-8")
    header = text.split("\njobs:\n", 1)[0]
    fast_job = _job("native-paid-route", text)
    assert "concurrency:" not in header
    assert (
        "    concurrency:\n"
        "      group: native-paid-route-fast-pr-"
        "${{ github.event.pull_request.number }}\n"
        "      cancel-in-progress: true\n"
    ) in fast_job
    # Separate manual original/native 100-mob comparisons must retain their
    # paid receipts even when a faster PR update lands.
    for name in ("work2-m06-original-native", "cross-tree-native-world"):
        manual_job = _job(name, text)
        assert "cancel-in-progress:" not in manual_job
        assert "    if: ${{ github.event_name == 'workflow_dispatch'" in manual_job

def test_fast_native_route_ci_covers_public_m06_optimizer_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")
    pr_paths = text.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
    assert "      - src/v2/native_range_optimizer.py\n" in pr_paths
    assert "      - src/v2/runner.py\n" in pr_paths
    assert "      - tests/maintenance/test_m06_paid_dispatch_boundary.py\n" in pr_paths
    fast_job = _job("native-paid-route", text)
    # A PR changing the real `python -m` entry point must not silently skip
    # CI or substitute library-only mocks for the public command dispatch.
    assert "python -m src.v2.runner optimize --help" in fast_job
    assert "cargo build" not in fast_job
    assert "run_m06_original" not in fast_job

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
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][a-zA-Z0-9_-]*:|\\Z)",
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

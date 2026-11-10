"""Paid P6/P7 no-record diagnostics must not rerun on ordinary PR commits.

This protects compute for the parameterized native optimizer without altering
source-native execution or any Merge-owned M1 gate verdict.
"""
from pathlib import Path
import re


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/generic-source-search-regressions.yml"
)


def _job(name: str) -> str:
    source = WORKFLOW.read_text(encoding="utf-8")
    _, separator, body = source.partition(f"  {name}:\n")
    assert separator, f"missing native diagnostic job {name}"
    # Match a top-level job at exactly two spaces, not nested YAML keys.
    return re.split(r"(?m)^  [a-z][a-z0-9_-]*:[ ]*$", body, maxsplit=1)[0]


def _condition(name: str) -> str:
    job = _job(name)
    match = re.search(r"^    if: >-\n((?:      .*\n)+)", job, re.MULTILINE)
    assert match, f"{name}: paid job must have explicit event condition"
    return match.group(1)


def test_native_paid_diagnostics_run_only_when_explicitly_labeled():
    expected = {
        "work2-p6-shared-cold-no-record": (
            "p6-paid-no-record",
            ("work/work2-p6-shared-cold-", "work/work2-p6-l40-followon-"),
        ),
        "selected-native-p72": (
            "p7-native-paid-no-record",
            ("work/work2-p72-native-axis-", "work/work2-p72-feral-",
             "work/work2-p73-feral-", "work/work2-p74-feral-"),
        ),
        "selected-native-p71": (
            "p7-native-paid-no-record",
            ("work/work2-p71-native-stochastic-",),
        ),
        "selected-native-p75": (
            "p7-native-paid-no-record",
            ("work/work2-p75-unrestricted-native-", "work/work2-feral-p75-native-"),
        ),
    }
    for job_name, (label, branches) in expected.items():
        condition = _condition(job_name)
        assert "github.event_name == 'pull_request'" in condition
        assert "github.event.action == 'labeled'" in condition
        assert f"github.event.label.name == '{label}'" in condition
        assert "contains(github.event.pull_request.labels" not in condition
        for branch in branches:
            assert f"startsWith(github.head_ref, '{branch}')" in condition


def test_regular_pr_regressions_and_real_native_paid_producers_still_exist():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [opened, synchronize, reopened, labeled]" in source
    assert "  source-search:\n" in source
    assert "needs: source-search" not in _job("work2-p6-shared-cold-no-record")
    assert "python tools/wf_gate.py --class druid" in _job("work2-p6-shared-cold-no-record")
    for name in ("selected-native-p71", "selected-native-p72", "selected-native-p75"):
        job = _job(name)
        assert "cargo build --release --locked --bin forever-engine" in job
        assert "python tools/wf_gate.py --class druid" in job



def test_explicit_paid_label_skips_generic_regression_job_without_blocking_paid_probe():
    # Labeled event only authorizes the matching opt-in source-native job.
    # Ordinary PR updates must continue running the generic regression suite.
    source_job = _job("source-search")
    assert "if: github.event.action != 'labeled'" in source_job
    assert "python -m pytest -vv" in source_job
    for name in (
        "work2-p6-shared-cold-no-record",
        "selected-native-p71",
        "selected-native-p72",
        "selected-native-p75",
    ):
        assert "needs: source-search" not in _job(name)
        assert "github.event.action == 'labeled'" in _condition(name)

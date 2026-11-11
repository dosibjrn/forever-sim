"""Retired accepted Druid P6/P7 paid label jobs must not recur.

Those L30/L40 P6 and L60 P7.1-P7.5 results are already recorded by
Merge. The generic PR suite remains cheap and still exercises changed
source-native adapters without launching another optional paid world.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/generic-source-search-regressions.yml"


def test_only_cheap_source_search_job_can_run_on_pr_updates():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    trigger, jobs = workflow.split("\njobs:\n", 1)
    assert "types: [opened, synchronize, reopened]" in trigger
    assert "labeled" not in trigger, "accepted Druid gates have no paid label replay"
    assert re.findall(r"(?m)^  ([a-z][a-z0-9_-]*):$", jobs) == ["source-search"]
    assert "cargo build --release" not in jobs
    assert "python tools/wf_gate.py --class druid" not in jobs
    assert "github.event.action" not in jobs


def test_source_coverage_and_unaccepted_generic_recorder_survive():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest -vv" in workflow
    for path in (
        "tests/maintenance/test_generic_source_paid_dispatch_scope.py",
        "tests/gates/test_wf_gate_p7_5_live.py",
        "tests/gates/test_wf_gate_p7_2_live.py",
        "tests/test_work2_p6_shared_source.py",
        "tests/test_work1_druid_l30_p72.py",
        "tests/test_work1_p71_native_generated.py",
    ):
        assert path in workflow, f"source regression coverage lost: {path}"
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()

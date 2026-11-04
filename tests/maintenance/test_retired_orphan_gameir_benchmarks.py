"""Retired one-off GameIR benchmark CLIs must not return to production.

These standalone report drivers duplicated Python gameplay evaluation. Their
underlying search/runtime regression tests remain available independently.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED = (
    "tools/wf277_real_guarded_benchmark.py",
    "tools/wf281_measured_family_benchmark.py",
    "tools/wf287_real_auto_frontier_benchmark.py",
)
RETAINED_TESTS = (
    "tests/test_wf277_guarded_source_continuation.py",
    "tests/generic/search/test_wf281_measured_family_allocation.py",
)


def test_orphan_gameir_benchmark_clis_remain_retired():
    for relative in RETIRED:
        assert not (ROOT / relative).exists(), relative
    for relative in RETAINED_TESTS:
        assert (ROOT / relative).is_file(), relative

    # A renamed import or workflow invocation would silently resurrect the
    # obsolete Python executor benchmark path.
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        for relative in RETIRED:
            assert relative not in source, f"{relative} in {workflow}"

    this_test = Path(__file__).resolve()
    for folder in ("src", "tools", "tests", "scripts", "integrations"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.resolve() == this_test:
                continue
            source = path.read_text(encoding="utf-8")
            for relative in RETIRED:
                assert Path(relative).stem not in source, f"{relative} in {path}"

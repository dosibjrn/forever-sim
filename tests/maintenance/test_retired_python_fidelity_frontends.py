"""Keep superseded Python-only fidelity report CLIs out of the live surface.

The source facts and historical behavior tests are intentionally preserved; this
only retires orphaned reporting entry points that re-evaluated game mechanics in
Python rather than exercising the selected native P3-P7.5 gate path.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED = (
    "tools/audit_forever_fidelity.py",
    "tools/report_mage_policy_fidelity.py",
)


def test_old_fidelity_report_frontends_remain_retired():
    for relative in RETIRED:
        assert not (ROOT / relative).exists(), relative

    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        source = workflow.read_text(encoding="utf-8")
        jobs = source.split("jobs:", 1)[1] if "jobs:" in source else ""
        for relative in RETIRED:
            assert relative not in jobs, f"retired report in {workflow}: {relative}"

    this_file = Path(__file__).resolve()
    retired_modules = {Path(relative).stem for relative in RETIRED}
    for folder in ("src", "tools", "scripts", "tests", "integrations"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.resolve() == this_file:
                continue
            source = path.read_text(encoding="utf-8")
            for module in retired_modules:
                assert module not in source, f"{module} still referenced in {path}"

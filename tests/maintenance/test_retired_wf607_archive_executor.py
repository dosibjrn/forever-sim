"""The WF607 ZIP-based Go re-executor is not a current P7 producer.

The historical receipts stay in docs/evidence; live P7.2–P7.4 are dispatched
through the selected gate entry points, never by unpacking an external ZIP.
This is a repository-maintenance regression, not an additional M1 gate.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIRED_NAME = "verify_recovered_feral_p7"
RETIRED_PATH = ROOT / "tools" / (RETIRED_NAME + ".py")


def test_orphan_wf607_archive_executor_stays_retired():
    assert not RETIRED_PATH.exists()
    for gate in ("p7_2", "p7_3", "p7_4"):
        assert (ROOT / "tools" / f"wf_gate_{gate}_live.py").is_file()

    # Prevent a workflow or live caller from depending on the removed script.
    this_test = Path(__file__).resolve()
    for folder in ("src", "tools", "tests", "scripts", "integrations"):
        for path in (ROOT / folder).rglob("*.py"):
            if path.resolve() != this_test:
                assert RETIRED_NAME not in path.read_text(encoding="utf-8"), path
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert RETIRED_NAME not in path.read_text(encoding="utf-8"), path

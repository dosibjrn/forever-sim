"""Obsolete standalone acquisition-proof benchmarks must not return as gates.

The selected MythicSim backend owns spell/rank acquisition legality.
The real route and stable gate entrypoints remain separate live code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_historical_acquisition_proof_benchmarks_are_not_live_clis():
    assert not (ROOT / "tools/wf332_druid20_acquisition_evidence.py").exists()
    assert not (ROOT / "tools/wf291_source_acquisition_route_benchmark.py").exists()
    assert (ROOT / "tools/wf_gate.py").is_file()
    assert (ROOT / "src/v2/source_budgeted_level_route.py").is_file()


def test_no_live_python_imports_retired_proof_benchmarks():
    retired = (
        "wf332_druid20_acquisition_evidence",
        "wf291_source_acquisition_route_benchmark",
    )
    for root in (ROOT / "src", ROOT / "tools", ROOT / "tests"):
        for path in root.rglob("*.py"):
            if path == Path(__file__):
                continue
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in retired), path

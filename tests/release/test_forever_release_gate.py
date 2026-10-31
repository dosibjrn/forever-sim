"""Release-only gate for current WoW Forever production decision rows."""

from src.rulesets.forever.release_gate import build_release_gate


def test_forever_production_decisions_release_gate():
    report = build_release_gate()
    assert report["ok"], report["failures"]
    assert len(report["checks"]) == 9
    assert all(row["ok"] for row in report["checks"])
    assert report["druid_independent_oracle_ok"] is True

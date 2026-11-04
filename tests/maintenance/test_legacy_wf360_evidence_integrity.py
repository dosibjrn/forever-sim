"""Keep legacy WF360 evidence readable without retaining its retired runner.

These records are still consumed by focused source/runtime regressions. They
are historical six-gate evidence, not current M1 certification.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "wf360"


def _read(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_legacy_wf360_p4_p5_evidence_remains_consistent():
    p4 = _read("WF360_L30_P4_30S.json")
    p5 = _read("WF360_L30_P5_300S.json")

    assert p4["checkpoint"] == p5["checkpoint"] == "druid:L30:unrestricted"
    assert p4["status"] == p5["status"] == "PASS"
    assert p4["independent_discovery"] and p5["independent_discovery"]
    assert not p4["old_winner_seeded"] and not p5["old_winner_seeded"]
    assert p4["source_db_sha256"] == p5["source_db_sha256"]
    assert p4["recovery_policy"] == p5["recovery_policy"]
    assert p4["end_to_end_wall_s"] <= 30
    assert p5["end_to_end_wall_s"] <= 300
    assert p5["unique_complete_builds_paid_lower_bound"] > p4["unique_complete_builds_paid_lower_bound"]
    assert p5["attempts_total"] > p4["attempts_total"]
    assert p5["events_total"] > p4["events_total"]
    assert p4["winner"]["actual_100mob_s_per_mob"] > 0
    assert p5["winner"]["actual_100mob_s_per_mob"] > 0


def test_legacy_wf360_p6_evidence_remains_a_fresh_100_mob_replay():
    p6 = _read("WF360_L30_P6_FRESH_100MOB.json")

    assert p6["checkpoint"] == "druid:L30:unrestricted"
    assert p6["status"] == "PASS"
    assert p6["p4_replay"]["status"] == p6["p5_replay"]["status"] == "COMPLETE"
    assert p6["p4_replay"]["count"] == p6["p5_replay"]["count"] == 100
    assert p6["t30_s_per_mob"] <= 1.01 * p6["t300_s_per_mob"]
    assert p6["global_optimality_proven"] is False

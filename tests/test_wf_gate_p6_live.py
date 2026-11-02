"""P6 actual paid replay evidence contract, not a mock P6 acceptance gate."""
from tools import wf_gate_p6_live as p6
from tools.wf_gate import _run_live_gate, ROOT


def test_partial_counts_only_really_killed_mobs():
    assert p6._mob_kills({"status": "COMPLETE", "count": 100}) == 100
    assert p6._mob_kills({"status": "BLOCKED_ACTOR_DIED", "mob_completed": 23}) == 23
    assert p6._mob_kills({"status": "COMPLETE", "count": 99}) == 0
    assert p6._mob_kills({"status": "COMPLETE", "count": True}) == 0
    assert p6._mob_kills({"status": "BLOCKED", "count": 1000}) == 0


def test_constrained_p6_never_produces_unsourced_acceptance():
    report = _run_live_gate(ROOT, "druid", 60, "balance", "P6", "")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [
        "P6_SOURCE_SPEC_TREE_SEARCH_CONSTRAINT_NOT_YET_CONNECTED"]

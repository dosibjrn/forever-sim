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


def test_p6_bounded_replay_rejects_ambiguous_or_invalid_paid_receipts(monkeypatch):
    """The production P6 caller must not silently score a corrupted 100-mob row.

    Contract controls only; this is not a source-hydrated CombatRuntime replay.
    """
    from src.v2 import source_bounded_joint_frontier as frontier

    search = {"validation_shortlist": [{"source_candidate": "one"}],
              "bonus_talent_points": 0, "pack_size": 2}
    valid = {"status": "COMPLETE", "count": 100, "mob_completed": 100,
             "full_s_per_mob": 12.5, "events": 5000}
    examples = [
        ([valid, valid], "AMBIGUOUS_SOURCE_PAID_REPLAY", 0),
        (["malformed"], "AMBIGUOUS_SOURCE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": float("nan")}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": float("inf")}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "full_s_per_mob": 0.0}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([{**valid, "count": 99}],
         "INVALID_COMPLETE_PAID_REPLAY", 0),
        ([valid], "COMPLETE", 100),
    ]
    for rows, expected_status, expected_kills in examples:
        monkeypatch.setattr(
            frontier, "replay_joint_shortlist_100mob",
            lambda *args, _rows=rows, **kwargs: {"rows": _rows})
        result = p6._replay_first_paid_winner(
            search, source_ir=None, seed_stage=None,
            class_key="druid", level=30)
        assert result["status"] == expected_status
        assert result["mob_completed"] == expected_kills
        if expected_status == "COMPLETE":
            assert result["mean_s_per_mob"] == 12.5
            assert result["events"] == 5000


def test_p6_bounded_ratio_requires_a_finite_paid_100mob_replay():
    valid = {"status": "COMPLETE", "count": 100, "mob_completed": 100,
             "mean_s_per_mob": 12.5}
    assert p6._complete_finite_paid_replay(valid)
    for bad in (float("nan"), float("inf"), 0.0, -1.0, None, True):
        assert not p6._complete_finite_paid_replay(
            {**valid, "mean_s_per_mob": bad})
    for invalid in ({"count": 99}, {"mob_completed": 99},
                    {"status": "BLOCKED_ACTOR_DIED"}, {"count": True}):
        assert not p6._complete_finite_paid_replay({**valid, **invalid})

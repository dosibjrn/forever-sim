from src import game_context
from src.rulesets.forever.classes.mage import engine as mage
from src.v2 import expected_engine
from tools.report_backend_reconciliation import build_report, _mage_structural_build


def test_expected_backend_executes_structural_arcane_blast_cycle():
    game_context.configure("forever", "mage")
    talents = _mage_structural_build(40, "arcane")
    policies = mage.candidate_policies_for_build(40, talents, focused=True, school="arcane")
    structural = [p for p in policies if p.arcane_blast_to_stacks > 0]
    assert structural
    cfg = mage.SimConfig(seed=7, use_best_water=True)
    spent_am = False
    for policy in structural:
        row = expected_engine.score_policy(40, talents, policy, cfg, cycle_pulls=2)
        assert row.get("casts_arcane_blast", 0.0) > 0.0
        spent_am = spent_am or row.get("casts_arcane_missiles", 0.0) > 0.0
        flags = {f for outcome in row["outcomes"] for f in outcome.approximation_flags}
        assert "missile_barrage_proc_event_authority" in flags
    # A high threshold can legitimately kill the mob before its AM spender.
    # The family as a whole must still exercise the spender path.
    assert spent_am


def test_reviewer_arcane_and_fire_reconciliation_slices_are_covered():
    report = build_report()
    rows = report["mage"]["levels"]
    for school in ("arcane", "fire"):
        school_rows = [r for r in rows if r["school"] == school]
        assert {r["level"] for r in school_rows} == {20, 40, 60}
        assert all(r["shared_candidate_count"] > 0 for r in school_rows)
        assert all(not r["unexplained_material_difference"] for r in school_rows)
        assert all(not r["skipped_candidates"] for r in school_rows)
    assert not report["mage"]["structural_missing"]
    assert "mage_structural_policy_absent_from_fast_backend" not in report["blocking_items"]

"""Real source P2 regression: full-point search builds are not always legal paired controls.

The source-legal Balance profile can contain a Restoration tier-3 talent
whose unlock depends on Gift of Nature rank 2. Its rank-1 control must be
evaluated on a *different legal partial allocation*, while the optimizer's
full-point search witness remains independently verified.
"""
from pathlib import Path

from tools.wf_gate_p2_live import run_live
from src.game.talents import available_talent_points


def test_druid_l60_gift_of_nature_rank_two_has_legal_paired_runtime_control():
    report = run_live(Path(__file__).resolve().parents[1], "druid", 60, spec="balance")
    rows = {row["rank_key"]: row for row in report["ranks"]}
    # One real source run also checks the previously missing Vengeance
    # critical-bonus behavior; no duplicate expensive full-gate invocation.
    vengeance = [row for row in report["ranks"] if row["talent_id"] == "vengeance"]
    assert vengeance, "Vengeance absent from the source P2 denominator"
    for rank in vengeance:
        assert rank["status"] == "PASS", (rank["rank_key"], rank["reasons"])
        assert any(test["probe"] == "paired_production_critical_bonus"
                   and test["actually_executed"] and test["passed"]
                   and test["after_amount"] > test["before_amount"] > 0
                   for test in rank["behavior_tests"]), rank["rank_key"]
    # Nature's Reach has two sourced effects: offensive spell hit AND range.
    # The former must change real CombatRuntime damage at <100% hit with a
    # saturated 100%-hit negative control; the latter is not yet implemented.
    # Never mark the whole talent rank PASS on a hit-only witness.
    for rank in (1, 2):
        reach = rows[f"natures_reach:{rank}"]
        hit = [t for t in reach["behavior_tests"]
               if t["probe"] == "paired_production_spell_hit_probability"]
        assert len(hit) == 1, (reach["rank_key"], reach["reasons"])
        probe = hit[0]
        assert probe["actually_executed"] and probe["passed"]
        assert probe["source_scoped_actions_checked"] > 0
        assert probe["after_amount"] > probe["before_amount"] > 0
        assert abs(probe["saturated_after"] - probe["saturated_before"]) < 1e-6
        assert reach["status"] == "FAIL"
        assert "IMPLEMENTATION_MISSING:source_offensive_range_world_behavior" in reach["reasons"]

    row = rows["gift_of_nature:2"]

    # An illegal rank-1 predecessor must not be accepted, but neither should
    # it prevent testing the rank's real effect in a valid partial setup.
    assert row["status"] == "PASS", row["reasons"]
    assert row["behavior_tests"], "structural talent acceptance is not behavior"
    assert all(test["actually_executed"] and test["passed"]
               for test in row["behavior_tests"])
    assert row["search_reachable"] is True
    assert row["spec_full_point_exact_rank_witness"] is True

    # The selected paired runtime control is deliberately smaller than the
    # legal full-point candidate retained for actual optimizer reachability.
    full_points = available_talent_points(60, bonus_talent_points=0)
    assert sum(row["witness"].values()) < full_points
    assert sum(row["search_witness"].values()) == full_points
    assert row["witness"]["gift_of_nature"] == 2
    assert row["search_witness"]["gift_of_nature"] == 2

    # Conditional defense armor must be tested above the *sourced* level
    # threshold. At base defense this talent legitimately has no extra effect.
    # Both the floor (negative control) and positive excess are executed in
    # ActorState.transition_mode, not inferred from a modifier registration.
    for rank in (1, 2, 3):
        thick=rows[f"thick_hide:{rank}"]
        assert thick["status"] == "PASS", thick["reasons"]
        witnesses=[test for test in thick["behavior_tests"]
                   if test["probe"] == "paired_production_mode_defense_threshold"]
        assert {w["mode_id"] for w in witnesses} == {"bear", "cat"}
        for witness in witnesses:
            assert witness["actually_executed"] and witness["passed"]
            assert witness["test_defense_above_floor"] > witness["source_defense_floor"]
            assert witness["observed_excess_rank_armor_delta"] > 0
            assert abs(witness["observed_excess_rank_armor_delta"]
                       - witness["expected_excess_rank_armor_delta"]) < 1e-6

    # Source-declared rear-position requirements are exercised through real
    # CombatRuntime action eligibility, including the opposite-position
    # negative control. A missing position must not silently waive Shred.
    for talent, ranks in (("savage_fury", (1, 2)),
                          ("shredding_attacks", (1, 2, 3))):
        for rank in ranks:
            positioned=rows[f"{talent}:{rank}"]
            assert positioned["status"] == "PASS", positioned["reasons"]
            shred=[test for test in positioned["behavior_tests"]
                   if test["target"] == "shred"]
            assert len(shred) == 1
            assert shred[0]["actually_executed"] and shred[0]["passed"]
            assert shred[0]["probe"] in {
                "paired_production_resource_spend",
                "isolated_production_combat_runtime_effect",
            }

    # No rank disappears from the canonical P2 denominator to obtain GREEN.
    assert (report["pass_count"] + report["fail_count"]
            + report["unresolved_count"] + report["unreachable_count"]
            == report["source_rank_total"] == 103)


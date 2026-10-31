from src.rulesets.forever.classes.druid import engine
from src.rulesets.forever.classes.druid.reference_builds import reference_build_snapshot
from src.rulesets.forever.classes.druid.talents import Talents
from src.v2.decision_result import DecisionResult, reports


def test_druid_capability_matrix_closes_balance_cat_bear_without_overclaiming():
    fid = engine.MODEL_FIDELITY
    assert engine.VERIFIED_LEVEL_CAP == 30
    assert engine.PLANNING_LEVEL_CAP == 40
    assert fid["verified_level_cap"] == 30
    assert fid["planning_level_cap"] == 40
    matrix = fid["capability_matrix"]
    assert set(matrix) == {"balance", "cat", "bear", "shared"}
    assert matrix["cat"]["energy_combo_points"] == "finite_target_stateful"
    assert matrix["bear"]["multi_pull_without_swipe"] == "fail_closed"
    assert matrix["balance"]["mana_recovery"] == "stateful_shared_recovery"
    assert matrix["shared"]["gear"] == "canonical_sqlite_runtime_selection"
    assert "proxy_components" not in fid["gear"]
    assert "full_recovery" not in fid["survival"]


def test_l40_is_bounded_planning_not_silently_verified():
    row = engine.experimental_level_score(40, Talents(), "balance")
    assert row["verified_level_cap"] == 30
    assert row["planning_level_cap"] == 40
    flags = " ".join(row.get("approximation_flags") or ())
    assert "L31-L40 bounded planning range" in flags


def test_reference_snapshot_exact_build_is_current_schema_validated():
    snap = reference_build_snapshot()
    exact = [b for b in snap["builds"] if b.get("allocation_detail_status") == "exact"]
    assert exact
    for build in exact:
        validation = build["runtime_schema_validation"]
        assert validation["ok"] is True
        assert validation["schema_build"] == snap["source"]["runtime_talent_schema_build"]
        assert validation["points"] == 51


def test_decision_metadata_exposes_druid_planning_capability_matrix():
    result = DecisionResult(class_name="druid", frontiers=tuple(), targets={})
    routes, _ = reports(result, verified_level_cap=engine.VERIFIED_LEVEL_CAP)
    assert routes["verified_level_cap"] == 30
    assert routes["planning_level_cap"] == 40
    assert routes["model_fidelity"]["capability_matrix"]["cat"]["between_mob_energy_carry"] == "stateful"

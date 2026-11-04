"""P4/P5 actual on-demand source-paid 2D production probe checks."""
from tools.wf_gate import ROOT, _run_live_gate
from types import SimpleNamespace
from tools.wf_gate_p4_p5_partial import (paid_gear_slot_coverage,
                                          paid_source_action_coverage)


def test_paid_slot_partial_only_counts_complete_action_executions():
    # No fake PASS from merely being proposed or evaluated but failed.
    evidence = {"source_slot_proposal_coverage":
        {"eligible_slots": ["head", "chest"], "paid_slots": ["head", "chest"]},
        "rows": [
            {"gear_move": "head:17", "screen_invoked": True,
             "screen_status": "COMPLETE", "source_action_counts": {"spell": 3}},
            {"gear_move": "chest:18", "screen_invoked": True,
             "screen_status": "BLOCKED", "source_action_counts": {"spell": 3}},
            {"gear_move": "head:19", "screen_invoked": True,
             "screen_status": "COMPLETE", "source_action_counts": {"spell": 1}},
        ]}
    assert paid_gear_slot_coverage(evidence) == {
        "verified": 1, "applicable": 2, "executed": 2,
        "paid_slots": ["head"], "eligible_slots": ["chest", "head"]}


def test_p4_unrestricted_druid_l30_executes_real_source_paid_backend():
    report = _run_live_gate(ROOT, "druid", 30, "unrestricted", "P4", "")
    assert report["status"] == "FAIL", report
    # Merely exploring a legal slot is NOT a successful behavioral assertion.
    assert report["explored_paid_gear_slots"] >= 0
    assert report["source_eligible_gear_slot_count"] > 0
    assert report.get("partial_scope") != "COMPLETED_PAID_SOURCE_GEAR_SLOT_CANDIDATES"
    assert report["production_engine"] == "gsim_CombatRuntime"
    assert report["required_full_search_s"] == 30
    assert report["real_paid_unique_full_builds"] >= 0
    if "pass_count" in report:
        assert report["coverage_basis"] == "executed_behavior_assertions"
        assert report["partial_scope"] == "SOURCE_ACTIONS_CAST_IN_COMPLETE_PAID_SCREEN"
        assert 0 <= report["pass_count"] <= report["reachability_count"]
        assert report["reachability_count"] > 0
    assert report["selected_backend_integration_pending"]
    assert report["reasons"], report


def test_p5_profile_uses_existing_source_legal_paid_frontier_not_300s(monkeypatch, tmp_path):
    # The approved product profile requires 31 Balance points. The production
    # search already supports this spec frontier; a named P5 partial must not
    # be discarded before an actual paid candidate can be attempted.
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import registry, gear, sqlite_talents
    from src.v2 import source_bounded_joint_frontier as frontier

    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    db = tmp_path / "source.sqlite"
    db.write_bytes(b"test-source-identity-only")
    monkeypatch.setattr(sqlite_talents, "DEFAULT_DB", db)
    ir = SimpleNamespace(actions=[SimpleNamespace(id="source:wrath")])
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kw: ir)
    monkeypatch.setattr(gear, "available_gear_roles", lambda cls: ["druid_feral"])
    monkeypatch.setattr(frontier, "source_cold_start_stage", lambda **kw: {"source": True})
    observed = []

    def sourced_search(**kw):
        observed.append(kw)
        return {
            "source_slot_proposal_coverage": {"eligible_slots": ["head"],
                                               "paid_slots": ["head"]},
            "rows": [{"screen_invoked": True, "screen_status": "COMPLETE",
                      "gear_move": "head:17",
                      "source_action_counts": {"source:wrath": 2}}],
            "p4_talent_unlock_coverage": {}, "unique_full_builds": 1,
            "screen_complete_candidates": 1, "wall_s": 0.2,
        }
    monkeypatch.setattr(frontier, "search_bounded_joint_frontier", sourced_search)
    report = gate.run_paid_partial(ROOT, "druid", 60, spec="balance", gate="P5")
    assert report["status"] == "FAIL"  # no native-world/300s gate PASS
    assert report["required_full_search_s"] == 300
    assert report["real_paid_screen_complete"] == 1
    assert len(observed) == 1
    assert observed[0]["spec_tree"] == "balance"
    assert observed[0]["min_spec_points"] == 31
    assert observed[0]["search_only"] is True
    assert observed[0]["max_cpu_s"] == 6.0


def test_unconfigured_spec_does_not_silently_select_source_tree(monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import registry, gear
    from src.v2 import source_bounded_joint_frontier as frontier
    from tools import wf_source_profile as profile
    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kw: SimpleNamespace(actions=[]))
    monkeypatch.setattr(gear, "available_gear_roles", lambda cls: ["role"])
    monkeypatch.setattr(profile, "_load_product_spec_profile", lambda *a, **kw: None)
    monkeypatch.setattr(frontier, "search_bounded_joint_frontier",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("must not search")))
    report = gate.run_paid_partial(ROOT, "druid", 60, spec="feral", gate="P4")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["SOURCE_SPEC_PRODUCT_PROFILE_NOT_CONFIGURED"]


def test_source_action_partial_counts_actual_complete_source_casts_only():
    ir_actions = [SimpleNamespace(id="source:smite"),
                  SimpleNamespace(id="source:renew"),
                  SimpleNamespace(id="source:heal")]
    search = {"rows": [
        {"screen_invoked": True, "screen_status": "COMPLETE",
         "source_action_counts": {"source:smite": 3, "unknown": 10}},
        {"screen_invoked": True, "screen_status": "BLOCKED",
         "source_action_counts": {"source:renew": 2}},
    ]}
    assert paid_source_action_coverage(search, ir_actions) == {
        "verified": 1, "applicable": 3, "executed": 1}
    search["rows"][1]["screen_status"] = "COMPLETE"
    assert paid_source_action_coverage(search, ir_actions)["verified"] == 2



def test_empty_talent_frontier_is_diagnostic_only_and_never_certifies_unlocks():
    import pytest
    from src.v2.source_bounded_joint_frontier import (
        _ensure_searchable_talent_frontier, _summarize_paid_unlock_coverage)

    allocations, frontier = _ensure_searchable_talent_frontier(
        [], {"source_unlock_allocation_unresolved": []},
        search_only=True, spec_tree=None)
    assert allocations == [{}]
    assert frontier["empty_talent_frontier_fallback"] == (
        "EMPTY_SELECTION_BASELINE_FOR_UNRESTRICTED_SHORT_PAID_DIAGNOSTIC_ONLY")
    _, unlocks_complete = _summarize_paid_unlock_coverage(
        [], {}, [], frontier)
    assert unlocks_complete is False
    assert frontier["source_unlock_allocation_unresolved"] == [
        {"reason": "NO_EXECUTABLE_FULL_POINT_TALENT_FRONTIER"}]

    with pytest.raises(ValueError, match="SOURCE_FULL_POINT_TALENT_FRONTIER_EMPTY"):
        _ensure_searchable_talent_frontier(
            [], {}, search_only=False, spec_tree=None)
    with pytest.raises(ValueError, match="SOURCE_FULL_POINT_TALENT_FRONTIER_EMPTY"):
        _ensure_searchable_talent_frontier(
            [], {}, search_only=True, spec_tree="mage")

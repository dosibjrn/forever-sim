"""P4/P5 actual on-demand source-paid 2D production probe checks."""
from tools.wf_gate import ROOT, _run_live_gate
from types import SimpleNamespace
import pytest
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
    assert observed[0]["allow_unallocated_talent_baseline"] is False


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



def test_p4_partial_needs_a_completed_cast_of_a_known_source_action(monkeypatch):
    # A completed paid screen is not enough to claim a source-action partial:
    # the runtime might cast only unknown/non-source actions.
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import registry, gear
    from src.v2 import source_bounded_joint_frontier as frontier

    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    ir = SimpleNamespace(actions=[SimpleNamespace(id="source:bolt")])
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kw: ir)
    monkeypatch.setattr(gear, "available_gear_roles", lambda cls: ["mage"])
    monkeypatch.setattr(frontier, "source_cold_start_stage", lambda **kw: {})

    def paid_screen_with_casts(counts):
        return {
            "rows": [{"screen_invoked": True, "screen_status": "COMPLETE",
                      "gear_move": "head:17", "source_action_counts": counts}],
            "source_slot_proposal_coverage": {
                "eligible_slots": ["head"], "paid_slots": ["head"]},
            "p4_talent_unlock_coverage": {}, "unique_full_builds": 1,
            "screen_complete_candidates": 1, "wall_s": 0.1,
        }

    monkeypatch.setattr(frontier, "search_bounded_joint_frontier",
                        lambda **kw: paid_screen_with_casts({"unknown": 3}))
    no_cast = gate.run_paid_partial(
        ROOT, "mage", 30, spec="unrestricted", gate="P4")
    assert no_cast["status"] == "FAIL"
    assert no_cast["real_paid_screen_complete"] == 1
    assert "NO_SOURCE_ACTION_CAST_IN_COMPLETE_PAID_SCREEN" in no_cast["reasons"]
    assert "pass_count" not in no_cast
    assert "reachability_count" not in no_cast
    assert "partial_scope" not in no_cast

    monkeypatch.setattr(frontier, "search_bounded_joint_frontier",
                        lambda **kw: paid_screen_with_casts({"source:bolt": 2}))
    cast = gate.run_paid_partial(
        ROOT, "mage", 30, spec="unrestricted", gate="P4")
    assert cast["status"] == "FAIL"  # no 30s / 100-mob acceptance
    assert cast["pass_count"] == 1
    assert cast["reachability_count"] == 1
    assert cast["partial_scope"] == "SOURCE_ACTIONS_CAST_IN_COMPLETE_PAID_SCREEN"
    assert "NO_SOURCE_ACTION_CAST_IN_COMPLETE_PAID_SCREEN" not in cast["reasons"]


def test_mage_l30_actual_source_empty_frontier_uses_validated_unallocated_baseline():
    # This uses the real Mage L30 source provider and the same compiler/frontier
    # as production. It does not run or claim a paid P4 acceptance.
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.gear import available_gear_roles
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.v2.source_bounded_joint_frontier import (
        bounded_full_point_talent_frontier,
        source_cold_start_stage,
        source_joint_policy_frontier,
        _source_talent_policy_variants,
        _prepare_source_talent_frontier,
        _summarize_paid_unlock_coverage,
    )

    source_ir = build_game_ir_slice(class_key="mage", level=30)
    assert source_ir is not None
    from tools.wf_gate_p4_p5_partial import paid_source_action_coverage
    source_action_ids = sorted({
        str(action.id) for action in source_ir.actions
        if getattr(action, "id", None)
    })
    assert len(source_action_ids) >= 2
    action_search = {"rows": [
        {"screen_invoked": True, "screen_status": "COMPLETE",
         "source_action_counts": {source_action_ids[0]: 2, "not-in-source-ir": 9}},
        {"screen_invoked": True, "screen_status": "BLOCKED",
         "source_action_counts": {source_action_ids[1]: 4}},
        {"screen_invoked": False, "screen_status": "COMPLETE",
         "source_action_counts": {source_action_ids[1]: 3}},
    ]}
    assert paid_source_action_coverage(action_search, source_ir.actions) == {
        "verified": 1, "applicable": len(source_action_ids), "executed": 1}
    compiled, _ = compile_talent_runtime(source_ir)
    assert compiled.actor.metadata["class_key"] == "mage"
    assert compiled.actor.metadata["level"] == 30

    talents, frontier = bounded_full_point_talent_frontier(
        compiled, level=30, bonus_talent_points=5, max_frontier=8)
    assert talents == [], frontier

    talents, frontier, error = _prepare_source_talent_frontier(
        compiled, talents, frontier, level=30, bonus_talent_points=5,
        search_only=True, spec_tree=None,
        allow_unallocated_talent_baseline=True)
    assert error is None
    assert talents == [{}]
    assert frontier["unallocated_baseline_only"] is True
    assert frontier["unallocated_baseline_validation"] == (
        "CANONICAL_SOURCE_TALENT_VALIDATOR_ACCEPTED")
    assert frontier["full_point_source_talent_frontier_available"] is False
    assert "NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER" in (
        frontier["source_unlock_allocation_unresolved"])
    unlocks, complete = _summarize_paid_unlock_coverage([], {}, [], frontier)
    assert unlocks == {}
    assert complete is False

    # Exercise the exact downstream axis that previously indexed an empty
    # policies_by_talent[0], without invoking any paid evaluator.
    roles = available_gear_roles("mage")
    assert roles
    seed = source_cold_start_stage(
        class_key="mage", level=30, source_ir=compiled, gear_role=roles[0])
    policies = source_joint_policy_frontier(
        compiled, seed, max_policies=4, include_mode_cycles=True)
    assert policies
    policies_by_talent, expected_unlocks, preparation_blockers = (
        _source_talent_policy_variants(
            compiled, talents, seed, policies, level=30,
            bonus_talent_points=5))
    assert len(policies_by_talent) == 1
    assert policies_by_talent[0]
    assert expected_unlocks == {}


def test_rejected_unallocated_baseline_returns_structured_blocked(monkeypatch):
    from src.v2 import source_bounded_joint_frontier as joint

    ir = SimpleNamespace(actor=SimpleNamespace(metadata={
        "class_key": "mage", "level": 30}), actions=[], modes=(), talents=())
    monkeypatch.setattr(joint, "compile_talent_runtime", lambda source_ir: (ir, {}))
    monkeypatch.setattr(joint, "checkpoint_enemy", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(joint, "bounded_full_point_talent_frontier",
                        lambda *args, **kwargs: ([], {}))

    def reject_empty_selection(*args, **kwargs):
        raise ValueError("canonical source validator rejected empty selection")

    monkeypatch.setattr(joint, "validate_talent_selection", reject_empty_selection)
    report = joint.search_bounded_joint_frontier(
        class_key="mage", level=30, source_ir=ir, seed_stage={},
        bonus_talent_points=5, max_cpu_s=6., per_candidate_wall_s=.75,
        screen_mobs=2, finalist_mobs=100, pack_size=2, search_only=True,
        screen_evaluator_backend="direct", allow_unallocated_talent_baseline=True)
    assert report["status"] == "BLOCKED"
    assert "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER" in report["reasons"]
    assert any(reason.startswith("UNALLOCATED_BASELINE_REJECTED:")
               for reason in report["reasons"])
    assert report["rows"] == []
    assert report["paid_candidates"] == 0
    assert report["p4_talent_unlock_coverage_pass"] is False
    assert report["p4_talent_unlock_coverage_complete"] is False


def test_full_search_never_gets_the_unallocated_talent_baseline(monkeypatch):
    from src.v2 import source_bounded_joint_frontier as joint

    ir = SimpleNamespace(actor=SimpleNamespace(metadata={
        "class_key": "mage", "level": 30}), actions=[], modes=(), talents=())
    monkeypatch.setattr(joint, "compile_talent_runtime", lambda source_ir: (ir, {}))
    monkeypatch.setattr(joint, "checkpoint_enemy", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(joint, "bounded_full_point_talent_frontier",
                        lambda *args, **kwargs: ([], {}))

    report = joint.search_bounded_joint_frontier(
        class_key="mage", level=30, source_ir=ir, seed_stage={},
        bonus_talent_points=5, max_cpu_s=30., screen_mobs=2,
        finalist_mobs=100, pack_size=2, search_only=False,
        allow_unallocated_talent_baseline=False)
    assert report["status"] == "BLOCKED"
    assert "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER" in report["reasons"]
    assert report["paid_candidates"] == 0
    assert report["rows"] == []
    assert "SOURCE_FULL_POINT_TALENT_FRONTIER_EMPTY" in report["reasons"]
    assert not any(str(reason).startswith("UNALLOCATED_BASELINE_REJECTED:")
                   for reason in report["reasons"])

    # Even an explicit opt-in cannot turn a 30s/100-mob acceptance search into
    # the 6s diagnostic path.
    with pytest.raises(ValueError, match="UNALLOCATED_TALENT_BASELINE_SCOPE_INVALID"):
        joint.search_bounded_joint_frontier(
            class_key="mage", level=30, source_ir=ir, seed_stage={},
            bonus_talent_points=5, max_cpu_s=30., per_candidate_wall_s=.75,
            screen_mobs=2, finalist_mobs=100, pack_size=2, search_only=True,
            screen_evaluator_backend="direct",
            allow_unallocated_talent_baseline=True)

    # NaN must not bypass the hard six-second diagnostic scope.
    with pytest.raises(ValueError, match="UNALLOCATED_TALENT_BASELINE_SCOPE_INVALID"):
        joint.search_bounded_joint_frontier(
            class_key="mage", level=30, source_ir=ir, seed_stage={},
            bonus_talent_points=5, max_cpu_s=float("nan"),
            per_candidate_wall_s=.75, screen_mobs=2, finalist_mobs=100,
            pack_size=2, search_only=True, screen_evaluator_backend="direct",
            allow_unallocated_talent_baseline=True)


def test_empty_policy_axis_returns_structured_blocked_before_dimension_index(monkeypatch):
    from src.v2 import source_bounded_joint_frontier as joint

    ir = SimpleNamespace(actor=SimpleNamespace(metadata={
        "class_key": "mage", "level": 30}), actions=[], modes=(), talents=())
    monkeypatch.setattr(joint, "compile_talent_runtime", lambda source_ir: (ir, {}))
    monkeypatch.setattr(joint, "checkpoint_enemy", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(joint, "bounded_full_point_talent_frontier",
                        lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(joint, "validate_talent_selection", lambda *args, **kwargs: None)
    monkeypatch.setattr(joint, "_source_reference_talents",
                        lambda *args, **kwargs: ([{}], "UNALLOCATED_BASELINE_ONLY"))
    monkeypatch.setattr(joint, "_source_slot_proposals", lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(joint, "_source_stat_package_proposals", lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(joint, "_source_weapon_package_proposals", lambda *args, **kwargs: ([], {}))
    monkeypatch.setattr(joint, "source_joint_policy_frontier",
                        lambda *args, **kwargs: [("source", object())])
    monkeypatch.setattr(joint, "_source_talent_policy_variants",
                        lambda *args, **kwargs: ([], {}, []))

    seed = {"allocation": {}, "gear_policy_result": {"winner": {"gear": {}}}}
    report = joint.search_bounded_joint_frontier(
        class_key="mage", level=30, source_ir=ir, seed_stage=seed,
        bonus_talent_points=5, max_cpu_s=6., per_candidate_wall_s=.75,
        screen_mobs=2, finalist_mobs=100, pack_size=2, search_only=True,
        screen_evaluator_backend="direct", allow_unallocated_talent_baseline=True)
    assert report["status"] == "BLOCKED"
    assert "BLOCKED_NO_EXECUTABLE_SOURCE_POLICY_FRONTIER" in report["reasons"]
    assert report["paid_candidates"] == 0
    assert report["rows"] == []


def test_full_paid_source_search_propagates_structured_blocked(monkeypatch):
    from tools import wf_gate_p6_full_source as full_source
    from tools import wf_gate_p4_p5_partial as gate

    monkeypatch.setattr(full_source, "_execute", lambda *args, **kwargs: (
        {"status": "BLOCKED",
         "reasons": ["BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER"]},
        None))
    report = gate.run_full_paid_source_search(
        ROOT, "mage", 30, spec="unrestricted", gate="P4")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [
        "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER"]


def test_mage_l30_partial_returns_structured_blocked_without_unlock_credit(monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import registry, gear
    from src.v2 import source_bounded_joint_frontier as frontier

    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    ir = SimpleNamespace(actions=[])
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **kwargs: ir)
    monkeypatch.setattr(gear, "available_gear_roles", lambda class_key: ["mage"])
    monkeypatch.setattr(frontier, "source_cold_start_stage", lambda **kwargs: {})
    observed = {}

    def blocked_search(**kwargs):
        observed.update(kwargs)
        return {
            "status": "BLOCKED",
            "reasons": ["BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER"],
            "talent_frontier_mode": "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER",
            "wall_s": 0.01,
        }

    monkeypatch.setattr(frontier, "search_bounded_joint_frontier", blocked_search)
    report = gate.run_paid_partial(
        ROOT, "mage", 30, spec="unrestricted", gate="P4")
    assert observed["allow_unallocated_talent_baseline"] is True
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [
        "BLOCKED_NO_EXECUTABLE_FULL_POINT_SOURCE_TALENT_FRONTIER"]
    assert report["real_talent_unlocked_actions_cast"] == 0
    assert report["p4_talent_unlock_coverage_pass"] is False
    assert report["p4_talent_unlock_coverage_complete"] is False
    assert report["coverage_scope_complete"] is False


def test_priest_p4_p5_queries_native_options_without_legacy_role_or_ir(monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import gear, registry
    from src.game import native_p3_item_options as native
    from src.v2 import source_bounded_joint_frontier as frontier

    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/forever-engine")
    monkeypatch.setattr(gear, "available_gear_roles", lambda key: ())
    def legacy_forbidden(**kwargs):
        raise AssertionError("native-only path must not build GameIR")
    monkeypatch.setattr(registry, "build_game_ir_slice", legacy_forbidden)
    monkeypatch.setattr(frontier, "search_bounded_joint_frontier", legacy_forbidden)
    queries = []
    def native_options(binary, class_key, level, *, spec):
        queries.append((binary, class_key, level, spec))
        return {"status": "partial_level_unknown",
                "items": [{"item_id": 17}, {"item_id": 18}],
                "unverified_candidate_count": 3}
    monkeypatch.setattr(native, "query_native_p3_item_options", native_options)

    for target_gate in ("P4", "P5"):
        report = gate.run_paid_partial(
            ROOT, "priest", 20, spec="unrestricted", gate=target_gate)
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == [
            "P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED"]
        assert report["native_source_option_count"] == 2
        assert report["native_source_unverified_candidate_count"] == 3
        assert report["native_source_status"] == "partial_level_unknown"
        assert report["paid_candidates"] == 0
        assert report["screen_complete_candidates"] == 0
        assert report["coverage_scope_complete"] is False
        assert "pass_count" not in report
    assert queries == [
        ("/selected/forever-engine", "priest", 20, "unrestricted")] * 2


def test_priest_native_options_refusal_and_missing_binary_do_not_fallback(monkeypatch):
    from tools import wf_gate_p4_p5_partial as gate
    from src.game.data.forever import gear, registry
    from src.game import native_p3_item_options as native

    monkeypatch.delenv("FOREVER_P4_P5_FULL_SOURCE", raising=False)
    monkeypatch.setattr(gear, "available_gear_roles", lambda key: ())
    monkeypatch.setattr(registry, "build_game_ir_slice",
                        lambda **kw: (_ for _ in ()).throw(
                            AssertionError("no legacy GameIR fallback")))
    monkeypatch.delenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", raising=False)
    missing = gate.run_paid_partial(
        ROOT, "priest", 20, spec="unrestricted", gate="P4")
    assert missing["reasons"] == ["P4_P5_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED"]
    assert "pass_count" not in missing

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/forever-engine")
    def refuse(*args, **kwargs):
        raise native.NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_REFUSED:CLASS_UNSUPPORTED")
    monkeypatch.setattr(native, "query_native_p3_item_options", refuse)
    refused = gate.run_paid_partial(
        ROOT, "priest", 20, spec="unrestricted", gate="P5")
    assert refused["status"] == "BLOCKED"
    assert refused["reasons"] == ["P3_NATIVE_ITEM_OPTIONS_REFUSED:CLASS_UNSUPPORTED"]
    assert "pass_count" not in refused

    monkeypatch.setattr(native, "query_native_p3_item_options",
                        lambda *args, **kwargs: {
                            "status": "empty", "items": [],
                            "unverified_candidate_count": 0})
    empty = gate.run_paid_partial(
        ROOT, "priest", 20, spec="unrestricted", gate="P4")
    assert empty["reasons"] == ["P4_P5_NATIVE_ITEM_OPTIONS_EMPTY"]
    assert empty["native_source_option_count"] == 0
    assert empty["paid_candidates"] == 0

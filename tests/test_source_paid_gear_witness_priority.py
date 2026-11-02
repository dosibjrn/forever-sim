"""Actual source-legal gear slots must receive paid frontier coordinates.

This tests production candidate scheduling using the real Mage/Druid item
catalogue and valid full-equipment substitutions. It does not claim a P4 gate.
"""
from collections import Counter
from itertools import islice

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    _SOURCE_GEAR_SAMPLING_VERSION, _source_gear_witness_probes,
    _source_witness_first_coordinates,
    source_cold_start_stage,
)
from src.v2.source_persistent_slot_search import _source_slot_proposals
from src.v2.source_joint_progress import PaidJointProgressJournal, search_context_sha256
from src.v2.source_persistent_joint_finalists import prepare_candidate
from src.v2.source_bounded_joint_frontier import _quick_joint_evaluation


def test_source_legal_slots_get_early_paid_witnesses_before_generic_cross_product():
    for class_key in ("mage", "druid"):
        source_ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=source_ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=24, slot_offset=0)
        gear_stages = [("incumbent", seed)]
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))

        eligible_slots = {label.split(":", 1)[0] for label, _ in gear_stages[1:]}
        assert len(eligible_slots) >= 6, (class_key, eligible_slots)
        witnesses = _source_gear_witness_probes(gear_stages)
        paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                      for coords in witnesses]
        first_pass = paid_slots[:len(eligible_slots)]
        assert len(first_pass) == len(set(first_pass)), (class_key, first_pass)
        assert set(first_pass) == eligible_slots, (class_key, first_pass, eligible_slots)
        assert len(witnesses) == len(set(witnesses))

        # The actual four-axis scheduler must pay for those gear coordinates
        # before consuming its generic policy/talent cross-product suffix.
        # Only the policy labels are inert here: no mock combat or PASS.
        variants = ((("incumbent", None),),)
        dimensions = (1, len(gear_stages), 1, 1)
        scheduled = list(islice(_source_witness_first_coordinates(
            dimensions, variants, "diagonal", [],
            gear_stages=gear_stages), len(witnesses)))
        assert scheduled == list(witnesses), (class_key, scheduled, witnesses)


def test_real_source_depth_three_enters_joint_paid_witness_prefix():
    # The 300s search can admit more gear moves than the 30s search.
    # A hardcoded per-slot top-two cap used to waste that extra paid budget.
    # This is the same catalogue, legality path and scheduler as production;
    # no simulated scores, fake items or gate-acceptance claims.
    for class_key in ("mage", "druid"):
        source_ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=source_ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        deep, source_counts = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64, slot_offset=0)
        shallow, shallow_counts = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=64, slot_offset=0)
        assert source_counts == shallow_counts
        assert len(deep) <= 64
        assert len({(slot, item.item_id) for slot, item in deep}) == len(deep)
        shallow_ids = {(slot, item.item_id) for slot, item in shallow}
        assert any((slot, item.item_id) not in shallow_ids for slot, item in deep)

        gear_stages = [("incumbent", seed)]
        for slot, item in deep:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))

        slots = [label.split(":", 1)[0] for label, _ in gear_stages[1:]]
        counts = Counter(slots)
        assert any(count >= 3 for count in counts.values()), (class_key, counts)
        witnesses = _source_gear_witness_probes(gear_stages)
        paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                      for coords in witnesses]
        assert len(witnesses) <= 32
        assert set(paid_slots[:len(counts)]) == set(counts)
        assert any(count >= 2 for count in Counter(paid_slots).values()), (
            class_key, paid_slots)
        # Larger explicit witness budgets can reach depth three without
        # changing the legal source inventory or the paid evaluation engine.
        deep_witnesses = _source_gear_witness_probes(
            gear_stages, max_probes=64)
        deep_paid_slots = [gear_stages[coords[1]][0].split(":", 1)[0]
                           for coords in deep_witnesses]
        assert any(count >= 3 for count in Counter(deep_paid_slots).values()), (
            class_key, deep_paid_slots)

        variants = ((("incumbent", None),),)
        dimensions = (1, len(gear_stages), 1, 1)
        scheduled = list(islice(_source_witness_first_coordinates(
            dimensions, variants, "diagonal", [],
            gear_stages=gear_stages), len(witnesses)))
        assert scheduled == list(witnesses), (class_key, scheduled, witnesses)


def test_deeper_source_frontier_cannot_resume_old_paid_search_journal(tmp_path):
    """Older paid journals cannot resume after candidate-order or event schema changes."""
    class_key, level = "mage", 30
    source_ir = build_game_ir_slice(class_key=class_key, level=level)
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=source_ir, gear_role=class_key)
    assert _SOURCE_GEAR_SAMPLING_VERSION == "stratified_source_slots_v5_real_paid_budget"
    new_options = {"gear_slot_sampling_version": _SOURCE_GEAR_SAMPLING_VERSION}
    new_hash = search_context_sha256(
        class_key=class_key, level=level, source_ir=source_ir,
        seed_stage=seed, options=new_options)
    for old_version in ("stratified_source_slots_v1", "stratified_source_slots_v2_depth10",
                        "stratified_source_slots_v3_paid_axis_balance",
                        "stratified_source_slots_v4_paid_events_identity"):
        old_hash = search_context_sha256(
            class_key=class_key, level=level, source_ir=source_ir,
            seed_stage=seed, options={"gear_slot_sampling_version": old_version})
        assert old_hash != new_hash
        path = tmp_path / (old_version + ".json")
        old_journal = PaidJointProgressJournal(path, context_sha256=old_hash)
        old_journal.write(
            status="IN_PROGRESS_NOT_CERTIFIED", phase="PREPARED",
            attempted=[], completed=[], events=0, full_evaluated_candidates=0,
            elapsed_wall_s=0.)
        with pytest.raises(ValueError, match="mismatched input context"):
            PaidJointProgressJournal(path, context_sha256=new_hash, resume=True)


def test_compound_apl_gets_a_paid_coordinate_before_second_item_in_same_slot():
    # Real Mage/Druid source gear stages, production coordinate scheduler.
    # No combat mocks or checkpoint PASS: this establishes the *order* of
    # candidates that can actually reach the paid evaluator.
    for class_key in ("mage", "druid"):
        ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64)
        gear_stages = [("incumbent", seed)]
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            gear_stages.append((f"{slot}:{item.item_id}", stage))
        # Source policy label only, no fake combat scoring.
        variants = ((("incumbent", None), ("multi_dot", None)),)
        dims = (1, len(gear_stages), 2, 1)
        scheduled = list(islice(
            _source_witness_first_coordinates(
                dims, variants, "diagonal", [], gear_stages=gear_stages), 80))
        compound = (0, 0, 1, 0)
        assert compound in scheduled
        def pure_slot(c):
            label = gear_stages[c[1]][0]
            return (c[1] != 0 and c[2] == 0
                    and not label.startswith(("source_stat_package:", "package:")))
        pure_slots = [gear_stages[c[1]][0].split(":", 1)[0]
                      for c in scheduled if pure_slot(c)]
        assert len(pure_slots) > len(set(pure_slots)), (class_key, pure_slots)
        first_repeat = next(
            i for i, c in enumerate(scheduled)
            if pure_slot(c)
            and gear_stages[c[1]][0].split(":", 1)[0] in {
                gear_stages[a[1]][0].split(":", 1)[0]
                for a in scheduled[:i] if pure_slot(a)})
        assert scheduled.index(compound) < first_repeat, (class_key, scheduled[:first_repeat+1])


def test_real_source_third_item_executes_through_paid_combat_runtime():
    # Not a candidate count or a fake green evaluator: execute a true
    # third-ranked legal item through the *production* GameIR+CombatRuntime.
    for class_key in ("mage", "druid"):
        ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=ir, gear_role=class_key)
        base = seed["gear_policy_result"]["winner"]["gear"]
        moves, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=10, max_proposals=64)
        counts = Counter()
        third = None
        for slot, item in moves:
            try:
                stage = substituted_multi_stage(
                    stage=seed, class_key=class_key, level=30,
                    swaps={slot: int(item.item_id)})
            except (ValueError, KeyError):
                continue
            counts[slot] += 1
            if counts[slot] == 3:
                third = (slot, item, stage)
                break
        assert third is not None, (class_key, counts)
        slot, item, stage = third
        candidate = prepare_candidate(
            class_key=class_key, level=30, stage=stage, source_ir=ir,
            allow_partial_gear_stats=True)
        assert int(candidate.source_stage["gear_policy_result"]["winner"]["gear"]
                   ["slots"][slot]["item_id"]) == int(item.item_id)
        result = _quick_joint_evaluation(
            candidate, level=30, mobs=1, recovery_policy=None,
            timeout_s=8., pack_size=1, backend="direct")
        assert result["status"] == "COMPLETE", (class_key, slot, item.item_id, result)
        assert result["count"] == 1
        assert result["events"] > 0


def test_p5_breadth_uses_real_distinct_paid_builds_not_attempted_coordinates():
    """The P5 N denominator cannot include blocked preparations or alias builds."""
    from copy import deepcopy
    from src.v2.source_bounded_joint_frontier import (
        _unique_paid_full_builds, search_bounded_joint_frontier,
    )

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    result = search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=1, max_gear_moves=0, max_policies=1,
        max_recovery_policies=1, max_paid_builds=3, max_cpu_s=6.,
        per_candidate_wall_s=1.5, screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=0)
    paid = [row for row in result["rows"] if row.get("screen_events", 0) > 0]
    assert paid, result["status"]
    assert all(row["equipped_gear"]["slots"] and row["policy_signature"]
               for row in paid)
    assert result["unique_full_builds"] == _unique_paid_full_builds(result["rows"])
    assert result["unique_full_builds"] <= result["paid_candidates"]

    # Negative controls are derived from a genuinely executed source build,
    # not a fake scorer: the same full build reached by another gear label is
    # one build, while a distinct coordinate rejected before combat is zero.
    witness = deepcopy(paid[0])
    duplicate = deepcopy(witness)
    duplicate["gear_move"] = "another_source_path_to_same_items"
    blocked = deepcopy(witness)
    blocked["gear_move"] = "not_a_paid_screen"
    blocked["screen_events"] = 0
    blocked["screen_status"] = "BLOCKED_PREPARATION_OR_EXECUTION"
    assert _unique_paid_full_builds([witness, duplicate, blocked]) == 1
    assert _unique_paid_full_builds([blocked]) == 0


def test_rejected_preflight_cannot_spend_the_only_paid_screen(monkeypatch):
    """One malformed source coordinate must not steal a real CombatRuntime slot.

    Only candidate preparation is fault-injected as a negative control; the
    following legal source candidate uses the unmodified production evaluator.
    """
    import src.v2.source_bounded_joint_frontier as joint

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    prepare = joint._prepare_joint_policy_candidate
    calls = 0

    def reject_first_source_preflight(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("SOURCE_PREFLIGHT_INVALID_GEAR_NEGATIVE_CONTROL")
        return prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        reject_first_source_preflight)
    result = joint.search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=2, max_gear_moves=0, max_policies=2,
        max_recovery_policies=2, max_paid_builds=1, max_cpu_s=8.,
        per_candidate_wall_s=2., screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=0)

    assert calls >= 2, result["rows"]
    assert result["rows"][0]["status"] == "BLOCKED_PREPARATION_OR_EXECUTION"
    assert not result["rows"][0].get("screen_invoked")
    assert result["paid_candidates"] >= 2  # attempts are journalled for resume
    assert result["initial_frontier_paid_candidates"] == 1
    assert sum(bool(row.get("screen_invoked")) for row in result["rows"]) == 1
    assert any(row.get("screen_events", 0) > 0 for row in result["rows"][1:])
    assert result["unique_full_builds"] >= 1  # real paid, source-legal build
    assert not result["eligible_for_checkpoint_acceptance"]


def test_rejected_source_preflight_resumes_without_repaying_it(monkeypatch, tmp_path):
    """A journalled rejection occupies a coordinate, not a paid slot."""
    from src.v2.source_joint_progress import load_verified_joint_progress
    import src.v2.source_bounded_joint_frontier as joint

    ir = build_game_ir_slice(class_key="druid", level=20)
    seed = source_cold_start_stage(
        class_key="druid", level=20, source_ir=ir, gear_role="druid_feral")
    real_prepare = joint._prepare_joint_policy_candidate
    calls = 0

    def reject_then_interrupt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("SOURCE_PREFLIGHT_INVALID_GEAR_NEGATIVE_CONTROL")
        if calls == 2:
            raise KeyboardInterrupt("interrupt before next paid screen")
        return real_prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        reject_then_interrupt)
    journal = tmp_path / "real-source-preflight.json"
    options = dict(
        class_key="druid", level=20, source_ir=ir, seed_stage=seed,
        max_talents=2, max_gear_moves=0, max_policies=2,
        max_recovery_policies=2, max_paid_builds=1, max_cpu_s=12.,
        per_candidate_wall_s=3., screen_mobs=1,
        screen_then_finalists=True, max_finalists=1,
        progress_path=journal)
    with pytest.raises(KeyboardInterrupt, match="interrupt before next paid"):
        joint.search_bounded_joint_frontier(**options)
    snapshot = load_verified_joint_progress(journal)
    assert snapshot["paid_candidates"] == 1  # one journalled preflight reject
    assert snapshot["rows"][0]["status"] == "BLOCKED_PREPARATION_OR_EXECUTION"
    assert snapshot["rows"][0]["screen_invoked"] is False

    prepared_on_resume = 0

    def count_real_preparations(**kwargs):
        nonlocal prepared_on_resume
        prepared_on_resume += 1
        return real_prepare(**kwargs)

    monkeypatch.setattr(joint, "_prepare_joint_policy_candidate",
                        count_real_preparations)
    result = joint.search_bounded_joint_frontier(**options, resume_progress=True)
    assert prepared_on_resume == 1, result["rows"]
    assert result["paid_candidates"] >= 2
    assert sum(bool(row.get("screen_invoked")) for row in result["rows"]) == 1
    assert result["initial_frontier_paid_candidates"] == 1
    assert any(row.get("screen_events", 0) > 0 for row in result["rows"][1:])
    assert result["unique_full_builds"] >= 1
    assert not result["eligible_for_checkpoint_acceptance"]


def test_refinement_never_spends_a_second_real_screen_past_paid_budget():
    # Genuine source-backed Druid L20 cold search, no mocked scorer.
    # Before the fix the first real frontier screen exhausted the one-call
    # budget, but the Top-N refinement still paid another CombatRuntime call.
    from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier

    source_ir = build_game_ir_slice(class_key="druid", level=20)
    stage = source_cold_start_stage(
        class_key="druid", level=20, source_ir=source_ir,
        gear_role="druid_feral")
    result = search_bounded_joint_frontier(
        class_key="druid", level=20, source_ir=source_ir,
        seed_stage=stage, max_paid_builds=1, max_cpu_s=9.,
        per_candidate_wall_s=3., max_talents=1,
        max_gear_moves=0, max_policies=1, max_recovery_policies=1,
        screen_mobs=1, search_only=True,
        screen_evaluator_backend="direct", refinement_rounds=1,
        refinement_top_n=1, refinement_stat_axes=("strength",),
        refinement_probe_delta=20., refinement_gear_candidates=1,
        refinement_policy_candidates=1, refinement_talent_neighbors=0,
        screen_budget_fraction=.4)
    assert result["screen_complete_candidates"] == 1, result["rows"]
    assert result["events"] > 0
    assert result["first_pass_screen_candidates"] == 1
    assert result["refinement"]["paid_evaluations"] == 0
    assert result["all_quick_evaluations_including_stat_probes"] == 1
    assert result["search_budget_exhausted"] is True

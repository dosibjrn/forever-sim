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
    """A v1 top-two journal must not be reused with v2 top-ten coordinates."""
    class_key, level = "mage", 30
    source_ir = build_game_ir_slice(class_key=class_key, level=level)
    seed = source_cold_start_stage(
        class_key=class_key, level=level, source_ir=source_ir, gear_role=class_key)
    assert _SOURCE_GEAR_SAMPLING_VERSION == "stratified_source_slots_v3_paid_axis_balance"
    new_options = {"gear_slot_sampling_version": _SOURCE_GEAR_SAMPLING_VERSION}
    new_hash = search_context_sha256(
        class_key=class_key, level=level, source_ir=source_ir,
        seed_stage=seed, options=new_options)
    for old_version in ("stratified_source_slots_v1", "stratified_source_slots_v2_depth10"):
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

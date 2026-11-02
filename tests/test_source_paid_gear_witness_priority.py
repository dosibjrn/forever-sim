"""Actual source-legal gear slots must receive paid frontier coordinates.

This tests production candidate scheduling using the real Mage/Druid item
catalogue and valid full-equipment substitutions. It does not claim a P4 gate.
"""
from collections import Counter

import pytest
from itertools import islice

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    _SOURCE_GEAR_SAMPLING_VERSION, _source_gear_witness_probes,
    _source_witness_first_coordinates,
    source_cold_start_stage,
)
from src.v2.source_persistent_slot_search import _source_slot_proposals
from src.v2.source_joint_progress import PaidJointProgressJournal, search_context_sha256


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
    assert _SOURCE_GEAR_SAMPLING_VERSION == "stratified_source_slots_v2_depth10"
    old_options = {"gear_slot_sampling_version": "stratified_source_slots_v1"}
    new_options = {"gear_slot_sampling_version": _SOURCE_GEAR_SAMPLING_VERSION}
    old_hash = search_context_sha256(
        class_key=class_key, level=level, source_ir=source_ir,
        seed_stage=seed, options=old_options)
    new_hash = search_context_sha256(
        class_key=class_key, level=level, source_ir=source_ir,
        seed_stage=seed, options=new_options)
    assert old_hash != new_hash

    path = tmp_path / "paid-joint-progress.json"
    old_journal = PaidJointProgressJournal(path, context_sha256=old_hash)
    old_journal.write(
        status="IN_PROGRESS_NOT_CERTIFIED", phase="PREPARED",
        attempted=[], completed=[], events=0, full_evaluated_candidates=0,
        elapsed_wall_s=0.)
    with pytest.raises(ValueError, match="mismatched input context"):
        PaidJointProgressJournal(path, context_sha256=new_hash, resume=True)

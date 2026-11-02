"""Actual source-legal gear slots must receive paid frontier coordinates.

This tests production candidate scheduling using the real Mage/Druid item
catalogue and valid full-equipment substitutions. It does not claim a P4 gate.
"""
from itertools import islice

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import (
    _source_gear_witness_probes, _source_witness_first_coordinates,
    source_cold_start_stage,
)
from src.v2.source_persistent_slot_search import _source_slot_proposals


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
        assert len(paid_slots) == len(set(paid_slots)), (class_key, paid_slots)
        assert set(paid_slots) == eligible_slots, (class_key, paid_slots, eligible_slots)

        # The actual four-axis scheduler must pay for those gear coordinates
        # before consuming its generic policy/talent cross-product suffix.
        # Only the policy labels are inert here: no mock combat or PASS.
        variants = ((("incumbent", None),),)
        dimensions = (1, len(gear_stages), 1, 1)
        scheduled = list(islice(_source_witness_first_coordinates(
            dimensions, variants, "diagonal", [],
            gear_stages=gear_stages), len(witnesses)))
        assert scheduled == list(witnesses), (class_key, scheduled, witnesses)

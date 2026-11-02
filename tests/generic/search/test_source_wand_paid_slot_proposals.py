"""Source-paid equipment frontier must propose the same legal wands as P3.

The catalogue publishes wands as ranged items; the simulator equips them in
the virtual 'wand' slot. Both the search and whole-gear legality audit must
agree on that mapping, without hardcoded item IDs or synthetic item effects.
"""
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.rulesets.forever.items.runtime_selection import available_items
from src.v2.source_bounded_joint_frontier import source_cold_start_stage
from src.v2.source_persistent_slot_search import _physical_slot, _source_slot_proposals


def test_mage_source_wands_enter_real_paid_slot_frontier_and_remain_legal():
    ir = build_game_ir_slice(class_key='mage', level=30)
    seed = source_cold_start_stage(
        class_key='mage', level=30, source_ir=ir, gear_role='mage')
    base = seed['gear_policy_result']['winner']['gear']
    assert 'wand' in base['slots']
    current_id = int(base['slots']['wand']['item_id'])
    source_wands = [item for item in available_items(
        'mage', 30, required_level_policy='observed')
        if item.slot == 'ranged' and item.weapon_type == 'wand'
        and int(item.item_id) != current_id]
    assert source_wands, 'source catalogue must contain an actual alternative wand'

    # per_slot=2 is also used by the real bounded joint paid frontier.
    proposals, counts = _source_slot_proposals(
        class_key='mage', level=30, base=base,
        per_slot=2, max_proposals=100)
    wand_proposals = [item for slot, item in proposals if slot == 'wand']
    assert counts['wand'] == len(source_wands)
    assert wand_proposals
    assert all(item.slot == 'ranged' and item.weapon_type == 'wand'
               and int(item.item_id) != current_id for item in wand_proposals)

    # The actual production source swap and whole-equipment audit must accept
    # each proposed item, not just a standalone slot predicate.
    for item in wand_proposals:
        changed = substituted_multi_stage(
            stage=seed, class_key='mage', level=30,
            swaps={'wand': int(item.item_id)})
        gear = changed['gear_policy_result']['winner']['gear']
        assert gear['slots']['wand']['item_id'] == item.item_id
        assert audit_named_gear_source(
            class_key='mage', level=30, gear=gear)['equipment_legality_complete']


def test_source_wand_slot_rejects_other_ranged_weapon_families():
    hunter_ranged = [item for item in available_items(
        'hunter', 30, required_level_policy='observed')
        if item.slot == 'ranged' and item.weapon_type in ('bow', 'crossbow', 'gun')]
    assert hunter_ranged
    assert not _physical_slot('wand', hunter_ranged[0])
    assert _physical_slot('ranged', hunter_ranged[0])


def test_small_paid_budget_interleaves_real_source_slots_across_classes():
    # The joint optimizer passes a *global* slot quota, not per-slot quota.
    # Before this fix, 6 moves meant two items each from alphabetically first
    # slots, and every later slot (including wand) was invisible to L2.
    for class_key in ('mage', 'druid'):
        ir = build_game_ir_slice(class_key=class_key, level=30)
        seed = source_cold_start_stage(
            class_key=class_key, level=30, source_ir=ir, gear_role=class_key)
        base = seed['gear_policy_result']['winner']['gear']
        full, counts = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=100)
        legal_slots = sorted(slot for slot, count in counts.items() if count)
        assert len(legal_slots) > 6, (class_key, counts)
        # A budget below the legal slot count must cover the source range,
        # not always select the same alphabetically earliest slots.
        # This is the real six-move paid frontier, not an invented item list.
        chosen_by_offset = []
        for offset in (0, 1):
            small, small_counts = _source_slot_proposals(
                class_key=class_key, level=30, base=base,
                per_slot=2, max_proposals=6, slot_offset=offset)
            assert small_counts == counts
            assert len(small) == 6
            selected_slots = [slot for slot, _ in small]
            expected_slots = [legal_slots[(offset + (i*len(legal_slots))//6)
                                          % len(legal_slots)] for i in range(6)]
            assert selected_slots == expected_slots
            assert len(set(selected_slots)) == 6
            assert all(_physical_slot(slot, item) for slot, item in small)
            # Every sampled item is still a genuine legal source replacement.
            assert all(any(slot == full_slot and item.item_id == full_item.item_id
                           for full_slot, full_item in full)
                       for slot, item in small)
            chosen_by_offset.append(set(selected_slots))
        assert len(chosen_by_offset[0] | chosen_by_offset[1]) > 6
        # Same source, same explicit offset, same proposal identities.
        repeated, _ = _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=6, slot_offset=0)
        assert repeated == _source_slot_proposals(
            class_key=class_key, level=30, base=base,
            per_slot=2, max_proposals=6, slot_offset=0)[0]

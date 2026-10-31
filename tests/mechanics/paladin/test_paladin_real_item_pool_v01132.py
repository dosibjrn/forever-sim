from __future__ import annotations

from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot, reroll_body_items
from src.rulesets.forever.shared.crafted_itemization import paladin_role_slot_candidates


def test_l20_paladin_candidate_pool_covers_real_body_and_accessory_slots():
    pools = paladin_role_slot_candidates(20)
    expected = {
        'head', 'neck', 'shoulder', 'back', 'chest', 'wrist', 'hands',
        'waist', 'legs', 'feet', 'ring1', 'ring2', 'trinket1', 'trinket2',
    }
    assert expected <= set(pools)
    assert any(x.name == 'Silvered Bronze Shoulders' for x in pools['shoulder'])
    assert any(x.name == "Battle Healer's Cloak" for x in pools['back'])
    assert any(x.name == 'First Mate Band' for x in pools['ring1'])
    assert any(x.name == 'Rune of Perfection' for x in pools['trinket2'])


def test_reroll_can_fill_slots_missing_from_sparse_profession_baseline():
    gear = next(g for g in archetypes(20) if g.name == '2h_normal')
    base = gear_snapshot(gear)
    assert 'neck' in base['body_field_missing_slots']
    assert 'back' in base['body_field_missing_slots']

    rerolled = reroll_body_items(
        gear,
        20,
        {
            'strength': 1.0,
            'stamina': 1.0,
            'intellect': 1.0,
            'spirit': 1.0,
            'spell_power': 1.0,
            'healing': 0.25,
            'defense': 0.5,
            'armor': 0.001,
        },
    )
    snap = gear_snapshot(rerolled)
    assert snap['body_field_missing_slots'] == []
    assert snap['slots']['neck']['name'] in {'Mark of the Pack Leader', 'Tarnished Locket'}
    assert snap['slots']['back']['name'] in {"Battle Healer's Cloak", 'Raptor Hide Cloak'}
    assert snap['slots']['wrist']['name'] in {'Rift Bracers', 'Cryptwalker Bracers', 'Cavedweller Bracers'}
    assert snap['slots']['ring1']['name'] in {'First Mate Band', "Advisor's Ring"}
    assert snap['slots']['trinket1']['name'] == "Lookie's Spyglass"
    assert snap['reconciliation_ok'] is True
    assert not any(x.get('modeled') for x in snap['items'])


def test_l20_profession_baseline_now_has_real_head_and_shoulders():
    snap = gear_snapshot(next(g for g in archetypes(20) if g.name == '2h_normal'))
    assert snap['slots']['head']['name'] == "Crusader's Silvered Chain Helm"
    assert snap['slots']['shoulder']['name'] == 'Silvered Bronze Shoulders'
    assert snap['reconciliation_ok'] is True


def test_midlevel_real_item_ladder_and_shield_samples_are_not_stuck_at_l20():
    from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot
    from src.rulesets.forever.shared.crafted_itemization import paladin_role_slot_candidates

    c30 = paladin_role_slot_candidates(30)
    assert {x.name for x in c30["shoulder"]} >= {"Golden Scale Shoulders"}
    assert {x.name for x in c30["neck"]} >= {"Kaleidoscope Chain", "Scorn's Icy Choker"}

    c58 = paladin_role_slot_candidates(58)
    assert {x.name for x in c58["back"]} >= {
        "Spritecaster Cape", "Blackveil Cape", "Stoneskin Gargoyle Cape",
        "Crystalline Threaded Cape",
    }
    assert "Star of Mystaria" in {x.name for x in c58["neck"]}

    g36 = next(g for g in archetypes(36) if g.name == "1h_shield_normal")
    g39 = next(g for g in archetypes(39) if g.name == "1h_shield_normal")
    assert gear_snapshot(g36)["slots"]["offhand"]["name"] == "The Green Tower"
    assert gear_snapshot(g39)["slots"]["offhand"]["name"] == "Aegis of the Scarlet Commander"


def test_current_seedcloud_and_evergreen_spell_power_values_are_used():
    from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot
    g20 = next(g for g in archetypes(20) if g.name == "1h_shield_normal")
    g60 = next(g for g in archetypes(60) if g.name == "1h_shield_normal")
    assert gear_snapshot(g20)["slots"]["offhand"]["spell_power"] == 4.0
    assert gear_snapshot(g60)["slots"]["offhand"]["spell_power"] == 7.0
    assert gear_snapshot(g60)["slots"]["offhand"]["healing"] == 22.0


def test_l20_paladin_pool_contains_real_mp5_spell_power_and_mp5_shoulders():
    pools = paladin_role_slot_candidates(20)
    ring_names = {x.name for x in pools['ring1']} | {x.name for x in pools['ring2']}
    assert "Advisor's Ring" in ring_names or "Lorekeeper's Ring" in ring_names
    mp5_rings = [x for slot in ('ring1','ring2') for x in pools[slot] if x.name in {"Advisor's Ring", "Lorekeeper's Ring"}]
    assert mp5_rings
    assert all(x.mp5 == 2 for x in mp5_rings)
    assert all(x.damage_power == 5 for x in mp5_rings)
    assert any(x.name == 'Talbar Mantle' and x.mp5 == 2 for x in pools['shoulder'])


def test_paladin_mp5_is_aggregated_reconciled_and_can_drive_reroll():
    gear = next(g for g in archetypes(20) if g.name == '1h_shield_normal')
    rerolled = reroll_body_items(
        gear, 20,
        {'mp5': 10.0, 'spell_power': 5.0, 'stamina': 0.1, 'intellect': 0.1},
    )
    snap = gear_snapshot(rerolled)
    assert snap['combat_totals']['mp5'] == snap['slot_totals']['mp5']
    assert snap['combat_totals']['mp5'] > 0
    assert snap['reconciliation_ok'] is True
    names = {x['name'] for x in snap['items']}
    assert names & {"Advisor's Ring", "Lorekeeper's Ring", 'Talbar Mantle'}

from __future__ import annotations

from src.rulesets.forever.items.runtime_selection import available_items
from src.rulesets.forever.classes.mage import real_gear
from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot
from src.rulesets.forever.classes.hunter.mechanics import _gear_from_catalogue


def _gaps(gear):
    return [s for s,m in gear["catalogue_coverage"].items() if m["status"] in {"catalogue_gap", "query_gap"}]


def test_mage_uses_shared_runtime_pool_and_shared_coverage_at_l20():
    gear = real_gear.snapshot(20)
    legal = available_items("mage", 20)
    assert gear["catalogue_coverage_authority"] == "shared_gear_requirements_v1"
    assert gear["catalogue_candidate_counts"]["weapon"] == sum(x.slot in {"one_hand","main_hand","two_hand"} for x in legal)
    assert gear["catalogue_candidate_counts"]["wand"] == sum(x.slot == "ranged" and x.weapon_type == "wand" for x in legal)
    assert gear["catalogue_coverage"]["wand"]["status"] == "available"
    assert gear["catalogue_coverage"]["ranged"]["status"] == "proficiency_blocked"
    assert gear["catalogue_coverage"]["relic"]["status"] == "proficiency_blocked"
    assert gear["missing_slots"] == _gaps(gear) == []
    # Local Mage wrapper now consumes exactly the shared legal runtime rows it can map.
    shared_ids = {x.item_id for x in legal if x.slot not in {"relic","shirt","tabard","ranged"} or x.weapon_type == "wand"}
    local_ids = {x.item_id for x in real_gear.available_items(20)}
    assert local_ids == shared_ids


def test_paladin_ret_and_tank_share_one_coverage_authority():
    ret, tank = (gear_snapshot(x) for x in archetypes(20))
    for gear in (ret, tank):
        assert gear["catalogue_coverage_authority"] == "shared_gear_requirements_v1"
        assert gear["catalogue_coverage"]["relic"]["status"] == "available"
        assert gear["catalogue_candidate_counts"]["relic"] == 4
        assert gear["catalogue_coverage"]["relic"]["scorer_modeled"] is False
        assert gear["catalogue_coverage"]["ranged"]["status"] == "proficiency_blocked"
        assert gear["catalogue_coverage"]["wand"]["status"] == "proficiency_blocked"
        assert _gaps(gear) == []
    assert ret["catalogue_coverage"]["offhand"]["status"] == "setup_blocked"
    assert tank["catalogue_coverage"]["offhand"]["status"] == "available"
    assert tank["catalogue_coverage"]["offhand"]["selected"] is True


def test_hunter_ranged_and_two_hand_setup_use_shared_coverage():
    gear = _gear_from_catalogue(20, {})
    legal = available_items("hunter", 20)
    assert gear["catalogue_coverage_authority"] == "shared_gear_requirements_v1"
    assert gear["catalogue_candidate_counts"]["ranged"] == sum(
        x.slot == "ranged" and x.weapon_type in {"bow","crossbow","gun"} for x in legal
    )
    assert gear["catalogue_coverage"]["ranged"]["status"] == "available"
    assert gear["catalogue_coverage"]["wand"]["status"] == "proficiency_blocked"
    assert gear["catalogue_coverage"]["relic"]["status"] == "proficiency_blocked"
    assert gear["catalogue_coverage"]["offhand"]["status"] == "setup_blocked"
    assert _gaps(gear) == []

from __future__ import annotations

from src.rulesets.forever.classes.druid.mechanics import _balance_gear, _bear_gear, _feral_gear
from src.rulesets.forever.items.runtime_selection import available_items


def test_druid_l20_coverage_uses_same_proficiency_filtered_pool_as_scorer():
    legal = available_items("druid", 20)
    expected_weapons = sum(1 for x in legal if x.slot in {"one_hand", "main_hand", "two_hand"})
    assert expected_weapons == 213
    for gear in (_balance_gear(20), _feral_gear(20), _bear_gear(20)):
        assert gear["catalogue_coverage_authority"] == "shared_gear_requirements_v1"
        assert gear["catalogue_candidate_counts"]["weapon"] == expected_weapons
        assert gear["catalogue_candidate_counts"]["relic"] == 6
        assert gear["catalogue_coverage"]["relic"]["status"] == "available"
        assert gear["catalogue_coverage"]["relic"]["scorer_modeled"] is False
        assert gear["catalogue_coverage"]["ranged"]["status"] == "proficiency_blocked"
        assert gear["catalogue_coverage"]["wand"]["status"] == "proficiency_blocked"
        assert not [
            slot for slot, meta in gear["catalogue_coverage"].items()
            if meta["status"] in {"catalogue_gap", "query_gap"}
        ]


def test_druid_two_hand_setup_blocks_offhand_but_balance_one_hand_does_not():
    feral = _feral_gear(20)
    bear = _bear_gear(20)
    balance = _balance_gear(20)
    assert feral["catalogue_coverage"]["offhand"]["status"] == "setup_blocked"
    assert bear["catalogue_coverage"]["offhand"]["status"] == "setup_blocked"
    assert balance["catalogue_coverage"]["offhand"]["status"] == "available"
    assert balance["catalogue_coverage"]["offhand"]["selected"] is True

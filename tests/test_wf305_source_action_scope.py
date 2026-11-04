"""Keep the small classifier used by source_rune_policy; retire the source-audit pipeline."""
import json

import pytest

from src.game.data.forever.source_action_scope import classify_indexed_ability


def test_index_mismatch_fails_closed():
    record = {
        "spell_id": 410025,
        "name": "Engrave Gloves - Mangle",
        "level_hint": 1,
        "source_url": "https://www.wowhead.com/forever/spell=410025",
    }
    with pytest.raises(ValueError, match="SOURCE_LISTVIEW_SPELL_ID_MISMATCH"):
        classify_indexed_ability(
            record, json.dumps({"id": 410024, "name": record["name"], "level": 1})
        )
    with pytest.raises(ValueError, match="SOURCE_LISTVIEW_LEVEL_MISMATCH"):
        classify_indexed_ability(
            record, json.dumps({"id": 410025, "name": record["name"], "level": 20})
        )


def test_engraving_recipe_is_classified_as_setup_not_a_combat_cast():
    record = {
        "spell_id": 410025,
        "name": "Engrave Gloves - Mangle",
        "level_hint": 1,
        "source_url": "https://www.wowhead.com/forever/spell=410025",
    }
    role = classify_indexed_ability(
        record, json.dumps({"id": 410025, "name": record["name"], "level": 1})
    )
    assert role["role"] == "SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP"
    assert role["slot_hint"] == "gloves"
    assert role["gameplay_coverage_complete"] is False
    assert role["source_acquisition_verified"] is False


def test_nonsetup_status_not_claimed_action_legal():
    record = {
        "spell_id": 123,
        "name": "Foo",
        "level_hint": 1,
        "source_url": "https://www.wowhead.com/forever/spell=123",
    }
    role = classify_indexed_ability(
        record, json.dumps({"id": 123, "name": "Foo", "level": 1})
    )
    assert role["role"] == "UNRESOLVED_POSITIVE_LEVEL_ENTRY"
    assert role["gameplay_coverage_complete"] is False
    assert role["source_acquisition_verified"] is False

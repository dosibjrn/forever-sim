"""Fail-closed source fact validation for native P2 rank receipts."""
from tools import wf_gate_p2_live as p2


def test_native_rank_diagnostic_requires_checkpoint_source_l0_before_execution():
    result = p2._native_p2_rank_diagnostic(
        None, "moonkin_form", 1,
        {"source_rank_facts": {"talent_id": "moonkin_form"}},
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "CANONICAL_CHECKPOINT_SOURCE_L0_MISSING"


def test_native_rank_diagnostic_checks_source_prerequisite_on_both_pair_members():
    source_url = "https://example.invalid/druid-talent-source"
    source = {
        "class_key": "druid",
        "level": 60,
        "talent_id": "predatory_strikes",
        "rank": 1,
        "tree_key": "feral",
        "tree_row": 3,
        "rank_cap": 3,
        "source_build": "1.60.1.70338",
        "source_url": source_url,
        "tree_members": ["ferocity", "feral_swiftness", "predatory_strikes"],
        "points_per_row": 5,
        "checkpoint_source_l0": {
            "source_url": source_url,
            "prerequisite": {
                "talent_id": "feral_swiftness",
                "required_rank": 2,
            },
            "expected_clause_count": 1,
            "effects": [{
                "domain": "form_melee_attack_power_from_level",
                "target": "attack_power",
                "sourced_value": 0.02,
                "condition": "cat_form",
                "source": source_url,
            }],
        },
    }
    result = p2._native_p2_rank_diagnostic(
        None,
        "predatory_strikes",
        1,
        {
            "source_rank_facts": source,
            "control_witness": {"ferocity": 5, "feral_swiftness": 1},
            "witness": {"ferocity": 5, "feral_swiftness": 1, "predatory_strikes": 1},
        },
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_RANK_PAIR_PREREQUISITE_NOT_SATISFIED"


def test_druid_l30_plus_defaults_to_the_staged_source_catalogue(tmp_path):
    from src.game.data.forever.sqlite_talents import DEFAULT_DB

    staged = tmp_path / "data" / "forever" / "staged_druid_l30_talents_70338.sqlite"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"sqlite-fixture")
    assert p2._default_p2_source_db(tmp_path, "druid", 60) == staged
    assert p2._default_p2_source_db(tmp_path, "druid", 20) == DEFAULT_DB
    override = tmp_path / "explicit.sqlite"
    assert p2._default_p2_source_db(tmp_path, "druid", 60, override) == override


def test_druid_l30_plus_fails_closed_without_staged_source_catalogue(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="DRUID_P2_STAGED_SOURCE_DB_MISSING"):
        p2._default_p2_source_db(tmp_path, "druid", 60)


def test_native_rank_diagnostic_requires_source_tree_tier_points_in_both_pair_members():
    source_url = "https://example.invalid/druid-talent-source"
    source = {
        "class_key": "druid",
        "level": 60,
        "talent_id": "predatory_strikes",
        "rank": 1,
        "tree_key": "feral",
        "tree_row": 3,
        "rank_cap": 3,
        "tree_members": ["ferocity", "feral_swiftness", "predatory_strikes"],
        "points_per_row": 5,
        "source_build": "1.60.1.70338",
        "source_url": source_url,
        "prerequisite": None,
        "checkpoint_source_l0": {
            "source_url": source_url,
            "expected_clause_count": 1,
            "effects": [{
                "domain": "form_melee_attack_power_from_level",
                "target": "attack_power",
                "sourced_value": 0.02,
                "condition": "cat_form",
                "source": source_url,
            }],
        },
    }
    result = p2._native_p2_rank_diagnostic(
        None,
        "predatory_strikes",
        1,
        {
            "source_rank_facts": source,
            "control_witness": {"ferocity": 5, "feral_swiftness": 9},
            "witness": {"ferocity": 5, "feral_swiftness": 9, "predatory_strikes": 1},
        },
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_RANK_PAIR_TIER_NOT_SATISFIED"

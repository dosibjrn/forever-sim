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
        "prerequisite": {
            "talent_id": "feral_swiftness",
            "required_rank": 2,
        },
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
            "control_witness": {"feral_swiftness": 1},
            "witness": {"feral_swiftness": 1, "predatory_strikes": 1},
        },
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_RANK_PAIR_PREREQUISITE_NOT_SATISFIED"

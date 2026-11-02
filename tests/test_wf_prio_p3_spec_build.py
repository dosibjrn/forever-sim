"""P3 production gear scorer must use the *actual* source-legal spec build."""
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import (
    talented_bonus_for_level, validate_talent_selection,
)
from tools.wf_gate_p3_live import _source_profile_build_ir, run_live


ROOT = Path(__file__).resolve().parents[1]


def test_druid_l60_balance_real_full_point_source_profile_changes_runtime_ir():
    naked = build_game_ir_slice(class_key="druid", level=60)
    selected, ctx = _source_profile_build_ir(ROOT, naked, "druid", 60, "balance")
    compiled, _ = compile_talent_runtime(naked)
    allocation = ctx["full_point_source_allocation"]
    validate_talent_selection(
        compiled, allocation, level=60,
        bonus_talent_points=talented_bonus_for_level(60))
    assert sum(allocation.values()) == 51
    assert ctx["source_profile_contract"] == "PRODUCT_PROFILE_CONSTRAINT"
    assert ctx["source_profile_candidate_count"] > 0
    assert ctx["applied_modifiers"] > 0
    assert selected != naked, "P3 must evaluate the selected talent-modified IR"
    assert selected.actor.metadata["class_key"] == "druid"


def test_unknown_spec_never_falls_back_to_unrestricted_gear_context():
    ir = build_game_ir_slice(class_key="druid", level=60)
    with pytest.raises(ValueError, match="SPEC_PROFILE_NOT_A_SOURCE_TREE"):
        _source_profile_build_ir(ROOT, ir, "druid", 60, "imaginary")


def test_real_p3_balance_paid_gear_evaluates_selected_source_profile():
    result = run_live(ROOT, "druid", 60, spec="balance")
    assert result["status"] != "PASS", "Other P3 stat weights are still incomplete"
    assert result["real_source_search_evaluated"] > 0, result
    assert result["real_catalogue_top5_items_scored"] > 0, result
    assert result["source_profile_production_build"]["full_point_source_allocation"]
    assert result["source_profile_production_build"]["applied_modifiers"] > 0
    assert not any("SPEC_CONSTRAINED_PRODUCTION_BUILD_NOT_EVALUATED" in reason
                   for reason in result["reasons"]), result

"""P3 production gear scorer must use the *actual* source-legal spec build."""
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_stat_delta, executable_gear_stats
from src.game.runtime.state import ActorState
from src.game.runtime import CombatRuntime, TargetState
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
    # The real paid source sensitivity must include the HP5 channel exposed
    # by the canonical item scorer, not silently omit it from P3 weights.
    assert "health_regeneration_per_5s" in result["real_measured_stat_weight_axes"], result
    assert result["source_profile_production_build"]["full_point_source_allocation"]
    assert result["source_profile_production_build"]["applied_modifiers"] > 0
    assert not any("SPEC_CONSTRAINED_PRODUCTION_BUILD_NOT_EVALUATED" in reason
                   for reason in result["reasons"]), result


def test_p3_hp5_probe_reaches_real_actor_health_regeneration():
    """The probed source item HP5 stat must change production runtime state."""
    ir = build_game_ir_slice(class_key="druid", level=60)
    stat = "health_regeneration_per_5s"
    assert stat in executable_gear_stats(ir)
    before = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    after_ir = apply_stat_delta(ir, stat, 10.0)
    after = ActorState.from_ir(after_ir.actor, after_ir.resources, after_ir.modes)
    assert after.resource_regeneration_per_s["health"] == pytest.approx(
        before.resource_regeneration_per_s["health"] + 2.0)


def test_p3_real_source_weapon_dps_marginal_changes_bear_combat_damage():
    """Pinned Forever Druid source facts and real CombatRuntime, no mock facts."""
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert "weapon_dps" in executable_gear_stats(ir)
    before = next(a for a in ir.auto_attacks if a.required_mode_id == "bear")
    assert before.damage_source.flat_dps > 0
    selected = apply_stat_delta(ir, "weapon_dps", 5.0)
    after = next(a for a in selected.auto_attacks if a.id == before.id)
    assert after.damage_source.flat_dps == pytest.approx(
        before.damage_source.flat_dps + 5.0)
    assert after.damage_source.dps_stat_id is None

    def swing_damage(source_ir, attack):
        actor = ActorState.from_ir(source_ir.actor, source_ir.resources,
                                   source_ir.modes)
        actor.transition_mode("bear")
        target = TargetState.with_health("source_bear_target", 100000., armor=0.)
        runtime = CombatRuntime(actor=actor, target=target, auto_attacks=(attack,))
        runtime.advance_to(float(attack.swing_time_s) + 0.01)
        return 100000. - target.health

    original = swing_damage(ir, before)
    improved = swing_damage(selected, after)
    assert original > 0
    assert improved > original

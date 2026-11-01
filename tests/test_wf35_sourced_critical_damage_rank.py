"""Execute a source-captured spell-school critical bonus in the real GameIR.

This is a production talent-effect regression, not a P2 gate certification.
"""
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.v2.source_bounded_joint_frontier import _source_unlock_full_point_allocation


def test_source_captured_critical_damage_bonus_changes_real_spell_effect():
    ir = build_game_ir_slice(class_key="druid", level=60)
    talent = next(t for t in ir.talents if t.id == "vengeance")
    rank = next(r for r in talent.ranks if r.rank == 1)
    # No value or school is inferred from the talent name: both were parsed
    # from the actual pinned SQLite source tooltip.
    assert "Arcane and Nature spells by 20%" in rank.provenance["raw_tooltip"]
    assert len(rank.modifiers) == 1
    modifier = rank.modifiers[0]
    assert modifier.kind == "critical_damage_bonus_pct"
    assert modifier.target_type == "action_filter"
    assert modifier.target_id == "damage_schools:arcane,nature"
    assert modifier.value == 0.20

    compiled, _ = compile_talent_runtime(ir)
    witness = _source_unlock_full_point_allocation(
        compiled, next(t for t in compiled.talents if t.id == "vengeance"),
        level=60)
    assert witness is not None and witness["vengeance"] == 1
    selected, application = apply_talent_selection(compiled, witness, level=60)
    assert any(x["talent_id"] == "vengeance" for x in application.applied_modifiers)

    before = {
        (action.id, index): effect.crit_multiplier
        for action in compiled.actions
        for index, effect in enumerate(action.effects)
        if hasattr(effect, "crit_multiplier")
        and getattr(effect, "school", "").lower() in ("arcane", "nature")
    }
    after = {
        (action.id, index): effect.crit_multiplier
        for action in selected.actions
        for index, effect in enumerate(action.effects)
        if hasattr(effect, "crit_multiplier")
        and getattr(effect, "school", "").lower() in ("arcane", "nature")
    }
    assert before and before.keys() == after.keys()
    assert any(after[key] > value for key, value in before.items())

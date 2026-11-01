"""Sourced cast-time + control proc must execute through the real GameIR runtime."""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import _parse_rank_tooltip
from src.game.model.ir import ControlEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.v2.source_bounded_joint_frontier import _source_unlock_full_point_allocation


def test_druid_starfire_source_rank_changes_cast_and_emits_control_event():
    ir = build_game_ir_slice(class_key="druid", level=60)
    talent = next(t for t in ir.talents if t.id == "improved_starfire")
    rank = next(r for r in talent.ranks if r.rank == 1)
    tooltip = rank.provenance["raw_tooltip"]
    assert "chance to stun its target" in tooltip
    assert len(rank.modifiers) == 2
    cast, proc = rank.modifiers
    assert (cast.kind, cast.target_id) == ("cast_time_delta_s", "starfire")
    assert (proc.kind, proc.target_id) == ("action_control_proc", "starfire")
    assert cast.value == pytest.approx(-0.1)
    assert proc.value == pytest.approx(0.03)
    assert proc.provenance["duration_s"] == pytest.approx(3.0)

    compiled, _ = compile_talent_runtime(ir)
    selected_talent = next(t for t in compiled.talents if t.id == "improved_starfire")
    allocation = _source_unlock_full_point_allocation(compiled, selected_talent, level=60)
    assert allocation is not None and allocation["improved_starfire"] == 1
    after, receipt = apply_talent_selection(compiled, allocation, level=60)
    assert any(m["kind"] == "action_control_proc" for m in receipt.applied_modifiers
               if m["talent_id"] == "improved_starfire")
    baseline = dict(allocation)
    baseline.pop("improved_starfire")
    before, _ = apply_talent_selection(compiled, baseline, level=60)
    original = next(a for a in before.actions if a.family_key == "starfire")
    modified = next(a for a in after.actions if a.family_key == "starfire")
    assert modified.cast_time_s == pytest.approx(original.cast_time_s - 0.1)
    controls = [e for e in modified.effects if isinstance(e, ControlEffect)]
    assert len(controls) == 1
    assert controls[0].control_id == "stun"
    assert controls[0].proc_chance == pytest.approx(0.03)
    assert controls[0].prevents_enemy_actions is True

    def execute(source_ir, action):
        actor = ActorState.from_ir(source_ir.actor, source_ir.resources, source_ir.modes)
        runtime = CombatRuntime(actor=actor,
                                target=TargetState.with_health("source_target", 100000.0))
        end = runtime.schedule_action(action)
        runtime.advance_to(end + 0.01)
        return end, [e for e in runtime.trace if e.kind == "ControlApplied"], runtime

    old_end, old_control, old_runtime = execute(before, original)
    new_end, new_control, new_runtime = execute(after, modified)
    assert new_end == pytest.approx(old_end - 0.1)
    assert not old_control
    assert len(new_control) == 1
    assert new_control[0].payload["control_id"] == "stun"
    assert new_control[0].payload["duration_s"] == pytest.approx(3.0)
    assert new_control[0].payload["proc_chance"] == pytest.approx(0.03)
    assert isinstance(new_control[0].payload["proc_triggered"], bool)
    assert old_runtime.target.health < 100000.0
    assert new_runtime.target.health < 100000.0


def test_source_stun_rank_fails_closed_without_its_named_action():
    ir = build_game_ir_slice(class_key="druid", level=60)
    rank = next(r for t in ir.talents if t.id == "improved_starfire"
                for r in t.ranks if r.rank == 1)
    modifiers, missing, reason = _parse_rank_tooltip(
        rank.provenance["raw_tooltip"], action_families=set(),
        source=rank.provenance["source"])
    assert modifiers == ()
    assert "starfire" in missing
    assert reason == "source_cast_stun_target_missing"

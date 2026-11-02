from pathlib import Path

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import PeriodicEffect
from src.game.runtime import ActorState, TargetState, execute_action_timeline
from src.v2.generic_backend import build_partial_generic_records


def _moonfire_ir(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-05")
    monkeypatch.setenv("WOW_FOREVER_BUILD_SOURCE", "g09_test")
    ir = build_game_ir_slice(class_key="druid", level=28)
    assert ir is not None
    action = next(a for a in ir.actions if a.family_key == "moonfire")
    return ir, action


def test_source_backed_moonfire_is_direct_plus_periodic_game_ir(monkeypatch):
    ir, action = _moonfire_ir(monkeypatch)
    assert ir.schema_version >= 5
    assert action.id == "moonfire:8927"
    assert action.costs[0].amount == 150.0
    assert action.cast_time_s == 0.0
    direct, periodic = action.effects
    assert direct.base_min == 70.0 and direct.base_max == 82.0
    assert direct.spell_power_coefficient == pytest.approx(0.15)
    assert isinstance(periodic, PeriodicEffect)
    assert periodic.total_base_damage == 124.0
    assert periodic.duration_s == 12.0
    assert periodic.tick_interval_s == 3.0
    assert periodic.spell_power_coefficient_per_tick == pytest.approx(0.13)
    assert periodic.refresh_rule == "replace"
    raw = next(x for x in ir.source_facts if x["family_key"] == "moonfire")
    assert raw["source"]["url"] == "https://www.wowhead.com/forever/spell=8927/moonfire"


def test_single_moonfire_ticks_and_expires_from_event_queue(monkeypatch):
    ir, action = _moonfire_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("durable", 10000.0)
    result = execute_action_timeline(
        scheduled_actions=((0.0, action),), actor=actor, target=target
    )
    assert result.direct_damage == pytest.approx(76.0)
    assert result.periodic_damage == pytest.approx(124.0)
    assert result.total_damage == pytest.approx(200.0)
    assert result.resources_before["mana"] == 934.0
    assert result.resources_after["mana"] == 784.0
    ticks = [e for e in result.events if e.kind == "Damage" and e.payload.get("periodic")]
    assert [e.time_s for e in ticks] == [3.0, 6.0, 9.0, 12.0]
    assert [e.payload["amount"] for e in ticks] == [31.0] * 4
    assert sum(e.kind == "AuraApplied" for e in result.events) == 1
    assert sum(e.kind == "AuraExpired" for e in result.events) == 1
    assert target.active_auras == {}


def test_replace_refresh_invalidates_old_generation_ticks(monkeypatch):
    ir, action = _moonfire_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("durable", 10000.0)
    result = execute_action_timeline(
        scheduled_actions=((0.0, action), (6.0, action)), actor=actor, target=target
    )
    assert result.direct_damage == pytest.approx(152.0)
    assert result.periodic_damage == pytest.approx(186.0)
    assert result.total_damage == pytest.approx(338.0)
    assert result.resources_after["mana"] == 634.0
    assert sum(e.kind == "AuraApplied" for e in result.events) == 1
    replaced = [e for e in result.events if e.kind == "AuraReplaced"]
    assert len(replaced) == 1
    assert replaced[0].payload["replaced_generation"] == 1
    assert replaced[0].payload["generation"] == 2
    landed = [e for e in result.events if e.kind == "Damage" and e.payload.get("periodic")]
    assert len(landed) == 6
    assert [e.time_s for e in landed] == [3.0, 6.0, 9.0, 12.0, 15.0, 18.0]
    skipped = [e for e in result.events if e.kind == "PeriodicTickSkipped"]
    assert len(skipped) == 2


def test_target_death_clears_aura_and_blocks_future_periodic_damage(monkeypatch):
    ir, action = _moonfire_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("mortal", 150.0)
    result = execute_action_timeline(
        scheduled_actions=((0.0, action),), actor=actor, target=target
    )
    assert result.target_defeated is True
    assert result.target_death_s == pytest.approx(9.0)
    landed = [e for e in result.events if e.kind == "Damage" and e.payload.get("periodic")]
    assert [e.time_s for e in landed] == [3.0, 6.0, 9.0]
    assert not [e for e in landed if e.time_s > result.target_death_s]
    assert any(e.kind == "PeriodicTickSkipped" and e.time_s == 12.0 for e in result.events)
    assert target.active_auras == {}


def test_generic_backend_publishes_periodic_runtime_without_legacy_fallback(monkeypatch):
    _moonfire_ir(monkeypatch)
    druid, mage = build_partial_generic_records(
        class_names=("druid", "mage"), selected_level=28
    )
    assert druid.capability["status"] == "combat_recovery_evaluation"
    assert druid.capability["recovery_evaluation"] is True
    assert druid.capability["combat_evaluation"] is True
    assert druid.capability["periodic_effect_runtime"] is True
    assert druid.capability["periodic_effect_runtime"] is True
    assert druid.capability["aura_refresh_replace"] is True
    assert "periodic_effect_runtime" not in druid.unsupported_mechanics
    assert "aura_refresh_replace" not in druid.unsupported_mechanics
    assert druid.provenance["legacy_fallback"] is False
    probe = druid.provenance["periodic_runtime"]
    assert probe["direct_damage"] == pytest.approx(152.0)
    assert probe["periodic_damage"] == pytest.approx(186.0)
    assert probe["aura_applied_count"] == 1
    assert probe["aura_replaced_count"] == 1
    assert probe["periodic_tick_count"] == 6
    assert druid.provenance["periodic_runtime_probe"]["refresh_at_s"] == 6.0
    assert mage.capability["periodic_effect_runtime"] is False


def test_runtime_and_listener_periodic_surface_stay_class_neutral():
    from src import listener

    # Class-specific source-backed probes are not part of the shared runtime.
    runtime_source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (Path("src/game/runtime/simulator.py"), Path("src/game/runtime/state.py"))
    ).lower()
    assert "druid" not in runtime_source
    assert "moonfire" not in runtime_source

    html = listener.DECISIONS_HTML
    start = html.index("function genericPeriodicRuntimeSummary(r)")
    end = html.index("function genericHealingRuntimeSummary(r)", start)
    renderer = html[start:end].lower()
    assert "aura / periodiceffect" in renderer
    assert "aurareplaced" in renderer
    assert "druid" not in renderer
    assert "moonfire" not in renderer
    assert "&level=${encodeuricomponent(number(state.level))}" in html.lower()

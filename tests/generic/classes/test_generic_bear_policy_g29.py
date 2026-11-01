from __future__ import annotations

from pathlib import Path

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import PeriodicResourceEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.generic_backend import build_partial_generic_records


def test_g29_bear_is_real_canonical_mode_with_actions_rage_and_autoattack():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    assert ir.schema_version == 16
    assert [m.id for m in ir.modes] == ["caster", "cat", "bear"]
    bear = next(m for m in ir.modes if m.id == "bear")
    assert any(x.resource_id == "rage" and x.active for x in bear.resource_rules)
    assert bear.stat_modifiers == ()
    assert bear.metadata["derived_attack_power"] == "explicit_gap_pending_canonical_primary_stat_conversion"

    action_ids = {a.id for a in ir.actions}
    assert {"bear_form:5487", "enrage:5229", "swipe:24", "primal_bite:25"} <= action_ids
    assert any(a.id == "auto_attack:bear" and a.required_mode_id == "bear" for a in ir.auto_attacks)
    policy = next(p for p in ir.policies if p.provenance.get("g29_scope") == "mode_action_policy_seed")
    assert policy.provenance["entry_action_id"] == "bear_form:5487"
    assert [r.id for r in policy.rules] == ["bear_enrage", "bear_swipe", "bear_primal_bite"]


def test_g29_periodic_resource_effect_executes_enrage_without_class_dispatch():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health("g29-enrage-probe", 100000.0)
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=())
    enter = next(a for a in ir.actions if a.id == "bear_form:5487")
    enrage = next(a for a in ir.actions if a.id == "enrage:5229")
    periodic = next(e for e in enrage.effects if isinstance(e, PeriodicResourceEffect))
    assert periodic.resource_id == "rage"
    assert periodic.amount_per_tick == pytest.approx(2.0)
    assert periodic.duration_s == pytest.approx(10.0)

    runtime.schedule_action(enter)
    runtime.advance_to(actor.gcd_ready_s)
    runtime.schedule_action(enrage)
    assert actor.resource_amount("rage") == pytest.approx(10.0)
    runtime.advance_to(11.5)
    assert actor.resource_amount("rage") == pytest.approx(30.0)
    ticks = [e for e in runtime.result().events if e.kind == "PeriodicTick" and e.payload.get("resource_id") == "rage"]
    assert len(ticks) == 10

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    policy_source = Path("src/game/policy.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "bear form" not in runtime_source
    assert "druid" not in policy_source
    assert "bear form" not in policy_source


def test_g29_generic_policy_search_selects_real_bear_action_and_beats_seed():
    record = build_partial_generic_records(class_names=("Druid",), selected_level=25)[0]
    assert record.capability["mode_action_policy_search"] is True
    assert record.capability["mode_action_policy_search_scope"] == "generic_mode_entry_resource_generation_and_action_priority_search"
    assert "mode_action_policy_search" not in record.unsupported_mechanics
    probe = record.provenance["mode_action_policy_probe"]
    assert probe["status"] == "selected"
    assert probe["mode_id"] == "bear"
    assert probe["selected_seconds_per_mob"] == pytest.approx(32.5)
    assert probe["seed_seconds_per_mob"] == pytest.approx(35.0)
    assert probe["improvement_vs_seed_seconds_per_mob"] == pytest.approx(2.5)
    assert probe["selected_candidate_id"] == "priority:bear_enrage>bear_primal_bite"
    assert probe["selected_action_ids"] == ["enrage:5229", "primal_bite:25"]
    assert probe["legacy_fallback"] is False

    from src.listener import DECISIONS_HTML
    assert "Generic mode action policy" in DECISIONS_HTML
    assert "function genericModeActionPolicySummary(r)" in DECISIONS_HTML


def test_g29_caster_cat_and_bear_all_enter_through_same_generic_runtime():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    for action_id, expected_mode in (("cat_form:768", "cat"), ("bear_form:5487", "bear")):
        actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
        target = TargetState.with_health(f"g29-{expected_mode}", 1000.0)
        runtime = CombatRuntime(actor=actor, target=target, auto_attacks=ir.auto_attacks)
        action = next(a for a in ir.actions if a.id == action_id)
        runtime.schedule_action(action)
        runtime.advance_to(0.0)
        assert actor.current_mode_id == expected_mode
        assert any(e.kind == "ModeChanged" for e in runtime.result().events)

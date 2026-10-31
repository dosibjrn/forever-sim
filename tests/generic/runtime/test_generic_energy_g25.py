from __future__ import annotations

from pathlib import Path
import threading

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import ActorDefinition, ModeDefinition, ModeResourceRule, ResourceDefinition, WeaponDamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility, expected_weapon_damage
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def test_g25_energy_and_claw_are_canonical_generic_ir():
    ir = build_game_ir_slice(class_key="Druid", level=23)
    assert ir.schema_version == 16
    energy = next(r for r in ir.resources if r.id == "energy")
    assert energy.capacity == pytest.approx(100.0)
    assert energy.initial_amount == pytest.approx(100.0)
    assert energy.regeneration_per_s == pytest.approx(10.0)
    assert energy.active_by_default is False

    claw = next(a for a in ir.actions if a.family_key == "claw")
    assert claw.id == "claw:20"
    assert claw.costs[0].resource_id == "energy"
    assert claw.costs[0].amount == pytest.approx(45.0)
    assert claw.gcd_s == pytest.approx(1.0)
    assert claw.requirements[-1] == {"kind": "mode_is", "value": "cat"}
    assert isinstance(claw.effects[0], WeaponDamageEffect)
    assert claw.effects[0].weapon_damage_multiplier == pytest.approx(1.10)
    assert claw.effects[0].flat_damage == pytest.approx(27.0)
    assert claw.effects[0].metadata["combo_point_award"] == 1
    assert claw.effects[0].metadata["combo_point_award_semantics"] == "generic_target_bound_resource_change"

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    state_source = Path("src/game/runtime/state.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "cat form" not in runtime_source
    assert "druid" not in state_source
    assert "claw" not in state_source


def test_g25_l23_claw_spam_is_energy_gated_by_real_generic_state():
    ir = build_game_ir_slice(class_key="Druid", level=23)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    cat_form = next(a for a in ir.actions if a.family_key == "cat_form")
    claw = next(a for a in ir.actions if a.family_key == "claw")
    target = TargetState.with_health("g25-l23-target", 10000.0)
    runtime = CombatRuntime(actor=actor, target=target)

    runtime.schedule_action(cat_form)
    runtime.advance_to(actor.gcd_ready_s)
    assert actor.current_time_s == pytest.approx(1.5)
    assert actor.resource_amount("energy") == pytest.approx(100.0)

    runtime.schedule_action(claw)
    assert actor.resource_amount("energy") == pytest.approx(55.0)
    runtime.advance_to(2.5)
    assert actor.resource_amount("energy") == pytest.approx(65.0)
    runtime.schedule_action(claw)
    assert actor.resource_amount("energy") == pytest.approx(20.0)

    runtime.advance_to(3.5)
    blocked = action_eligibility(action=claw, actor=actor)
    assert blocked.eligible is False
    assert blocked.reason == "action not ready: resource energy"
    assert blocked.next_ready_s == pytest.approx(5.0)
    assert actor.resource_amount("energy") == pytest.approx(30.0)

    runtime.advance_to(5.0)
    assert actor.resource_amount("energy") == pytest.approx(45.0)
    assert action_eligibility(action=claw, actor=actor).eligible is True
    runtime.schedule_action(claw)
    assert actor.resource_amount("energy") == pytest.approx(0.0)

    result = runtime.result()
    claw_damage = [e for e in result.events if e.kind == "Damage" and e.action_id == claw.id and e.payload.get("applied")]
    regen = [e for e in result.events if e.kind == "ResourceRegenerated" and e.payload.get("resource_id") == "energy"]
    assert len(claw_damage) == 3
    assert len(regen) >= 3
    assert claw_damage[0].payload["resolution"] == "expected_value_weapon_action_outcomes"
    assert claw_damage[0].payload["amount"] > 50.0


def test_g25_generic_resource_regen_only_runs_while_resource_active():
    actor_def = ActorDefinition(id="rogue-shaped-proof", actor_type="player")
    resource = ResourceDefinition(
        id="energy", name="Energy", owner_actor_id=actor_def.id,
        initial_amount=20.0, capacity=100.0, active_by_default=False, regeneration_per_s=10.0,
    )
    modes = (
        ModeDefinition(id="off", label="Off", initial=True, resource_rules=(ModeResourceRule("energy", False),)),
        ModeDefinition(id="on", label="On", resource_rules=(ModeResourceRule("energy", True),)),
    )
    actor = ActorState.from_ir(actor_def, (resource,), modes)
    assert actor.regenerate_for(5.0) == ()
    assert actor.resource_amount("energy") == pytest.approx(20.0)
    actor.transition_mode("on")
    rows = actor.regenerate_for(3.0)
    assert actor.resource_amount("energy") == pytest.approx(50.0)
    assert rows[0]["gained"] == pytest.approx(30.0)


def test_g25_weapon_damage_effect_is_generic_and_ap_sensitive():
    ir = build_game_ir_slice(class_key="Druid", level=23)
    claw = next(a for a in ir.actions if a.family_key == "claw")
    effect = claw.effects[0]
    actor = ActorState(id="warrior-shaped-proof", stats={"attack_power": 28.0})
    resolved = expected_weapon_damage(effect, actor=actor)
    source_dps = effect.damage_source.flat_dps + 28.0 / 14.0
    expected = source_dps * effect.weapon_damage_time_s * effect.weapon_damage_multiplier + effect.flat_damage
    assert resolved["raw_hit"] == pytest.approx(expected)
    assert resolved["expected_damage"] == pytest.approx(expected)


def test_g25_api_listener_checkpoint_publishes_energy_cadence(tmp_path):
    record = build_partial_generic_records(class_names=("Druid",), selected_level=23)[0]
    assert record.capability["energy_resource_runtime"] is True
    assert record.capability["energy_resource_scope"] == "generic_active_resource_continuous_regen_and_action_cost_gating"
    assert "energy_resource_runtime" not in record.unsupported_mechanics
    probe = record.provenance["energy_runtime_probe"]
    assert probe["regeneration_per_s"] == pytest.approx(10.0)
    assert probe["action_cost"] == pytest.approx(45.0)
    assert probe["claw_times_s"] == pytest.approx([1.5, 2.5, 5.0])
    assert probe["energy_before"] == pytest.approx([100.0, 65.0, 45.0])
    assert probe["energy_after"] == pytest.approx([55.0, 20.0, 0.0])
    assert probe["blocked_time_s"] == pytest.approx(3.5)
    assert probe["blocked_energy"] == pytest.approx(30.0)
    assert probe["blocked_reason"] == "action not ready: resource energy"
    assert probe["third_eligible_after_regen"] is True
    assert probe["claw_damage_events"] == 3
    assert probe["combo_points_target_bound_g26"] is True
    assert probe["legacy_fallback"] is False

    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=20)
        payload = client.decisions(level=23, backend_id="generic")
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    api_record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
    assert api_record["capability"]["energy_resource_runtime"] is True
    assert api_record["provenance"]["energy_runtime_probe"]["claw_times_s"] == pytest.approx([1.5, 2.5, 5.0])

    assert "Generic Energy + Cat action gating" in DECISIONS_HTML
    assert "function genericEnergySummary(r)" in DECISIONS_HTML

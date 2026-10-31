from __future__ import annotations

from pathlib import Path
import threading

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import (
    ActorDefinition,
    ModeDefinition,
    ModeResourceRule,
    ResourceDefinition,
)
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def test_g23_cat_form_is_canonical_mode_ir_not_runtime_class_dispatch():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    assert ir.schema_version == 16
    assert [m.id for m in ir.modes] == ["caster", "cat", "bear"]
    assert ir.modes[0].initial is True
    assert ir.modes[1].initial is False
    assert [m.id for m in ir.modes if m.initial] == ["caster"]
    energy = next(r for r in ir.resources if r.id == "energy")
    assert energy.active_by_default is False

    cat_action = next(a for a in ir.actions if a.family_key == "cat_form")
    cancel_action = next(a for a in ir.actions if a.id == "cancel_mode:cat")
    assert cat_action.effects[0].target_mode_id == "cat"
    assert cancel_action.effects[0].target_mode_id == "caster"
    assert cat_action.costs[0].amount == pytest.approx(354.0 * 0.55)

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    state_source = Path("src/game/runtime/state.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "cat form" not in runtime_source
    assert "druid" not in state_source
    assert "cat form" not in state_source


def test_g23_real_cat_transition_changes_mode_stats_resources_and_action_enablement():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    cat_action = next(a for a in ir.actions if a.family_key == "cat_form")
    cancel_action = next(a for a in ir.actions if a.id == "cancel_mode:cat")
    wrath = next(a for a in ir.actions if a.family_key == "wrath")

    assert actor.current_mode_id == "caster"
    assert actor.resource_is_active("energy") is False
    assert actor.stats.get("attack_power", 0.0) == pytest.approx(0.0)
    mana_before = actor.resource_amount("mana")

    context = TargetState.with_health("mode-context", 1.0)
    runtime = CombatRuntime(actor=actor, target=context)
    runtime.schedule_action(cat_action)
    runtime.run_until_idle()

    assert actor.current_mode_id == "cat"
    assert actor.resource_is_active("energy") is True
    assert actor.stats["attack_power"] == pytest.approx(12.0 + actor.stats["agility"])
    assert actor.resource_amount("mana") == pytest.approx(mana_before - cat_action.costs[0].amount)
    assert action_eligibility(action=wrath, actor=actor).eligible is False
    assert "disabled by active mode" in str(action_eligibility(action=wrath, actor=actor).reason)
    assert [e.kind for e in runtime.result().events][-2:] == ["ModeChange", "ModeChanged"]

    actor.current_time_s = max(actor.current_time_s, actor.gcd_ready_s)
    exit_runtime = CombatRuntime(actor=actor, target=context)
    exit_runtime.schedule_action(cancel_action)
    exit_runtime.run_until_idle()
    assert actor.current_mode_id == "caster"
    assert actor.resource_is_active("energy") is False
    assert actor.stats.get("attack_power", 0.0) == pytest.approx(0.0)
    assert actor.resource_amount("mana") == pytest.approx(mana_before - cat_action.costs[0].amount)


def test_g23_generic_mode_resource_rules_support_activation_preservation_and_reset():
    actor_def = ActorDefinition(id="player", actor_type="player", base_stats={"agility": 10.0})
    resources = (
        ResourceDefinition(
            id="energy", name="Energy", owner_actor_id="player",
            initial_amount=25.0, capacity=100.0, active_by_default=False,
        ),
    )
    modes = (
        ModeDefinition(
            id="idle", label="Idle", initial=True,
            resource_rules=(ModeResourceRule("energy", False, on_enter="preserve", on_exit="preserve"),),
        ),
        ModeDefinition(
            id="burst", label="Burst",
            resource_rules=(ModeResourceRule("energy", True, on_enter="reset_to_capacity", on_exit="preserve"),),
        ),
        ModeDefinition(
            id="drained", label="Drained",
            resource_rules=(ModeResourceRule("energy", True, on_enter="reset_to_zero", on_exit="preserve"),),
        ),
    )
    actor = ActorState.from_ir(actor_def, resources, modes)
    assert actor.current_mode_id == "idle"
    assert actor.resource_amount("energy") == pytest.approx(25.0)
    assert actor.resource_is_active("energy") is False

    actor.resources["energy"] = 7.0
    actor.transition_mode("burst")
    assert actor.resource_amount("energy") == pytest.approx(100.0)
    assert actor.resource_is_active("energy") is True

    actor.resources["energy"] = 41.0
    actor.transition_mode("idle")
    assert actor.resource_amount("energy") == pytest.approx(41.0)  # preserved
    assert actor.resource_is_active("energy") is False

    actor.transition_mode("drained")
    assert actor.resource_amount("energy") == pytest.approx(0.0)
    assert actor.resource_is_active("energy") is True


def test_g23_common_api_and_listener_publish_mode_runtime(tmp_path):
    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    assert record.capability["mode_ir"] is True
    assert record.capability["mode_transition_runtime"] is True
    assert "mode_transition_runtime" not in record.unsupported_mechanics
    assert [m["id"] for m in record.modes] == ["caster", "cat", "bear"]
    probe = record.provenance["mode_runtime_probe"]
    assert probe["initial_mode_id"] == "caster"
    assert probe["entered_mode_id"] == "cat"
    assert probe["final_mode_id"] == "caster"
    assert probe["entered_resource_active"]["energy"] is True
    assert probe["final_resource_active"]["energy"] is False
    assert probe["entered_stats"]["attack_power"] > probe["initial_stats"].get("attack_power", 0.0)
    assert probe["legacy_fallback"] is False

    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=20)
        payload = client.decisions(level=20, backend_id="generic")
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    api_record = next(r for r in payload["decisions"] if str(r["identity"]["class_name"]).lower() == "druid")
    assert api_record["capability"]["mode_transition_runtime"] is True
    assert [m["id"] for m in api_record["modes"]] == ["caster", "cat", "bear"]
    assert api_record["provenance"]["mode_runtime_probe"]["legacy_fallback"] is False

    assert "Generic Mode runtime" in DECISIONS_HTML
    assert "function genericModeSummary(r)" in DECISIONS_HTML

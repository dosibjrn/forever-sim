from __future__ import annotations

from pathlib import Path
import threading

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import (
    ActionDefinition,
    ActorDefinition,
    AutoAttackDamageSource,
    AutoAttackDefinition,
)
from src.game.runtime import ActorState, CombatRuntime, TargetState, expected_auto_attack_swing
from src.listener import DECISIONS_HTML
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.generic_backend import build_partial_generic_records


def test_g24_cat_melee_is_canonical_auto_attack_ir_not_runtime_class_dispatch():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    assert ir.schema_version == 16
    assert [a.id for a in ir.auto_attacks] == ["auto_attack:cat", "auto_attack:bear"]
    auto = ir.auto_attacks[0]
    assert auto.id == "auto_attack:cat"
    assert auto.attack_type == "melee"
    assert auto.required_mode_id == "cat"
    assert auto.swing_time_s == pytest.approx(1.0)
    assert auto.damage_source.kind == "equipped_weapon_dps_plus_attack_power"
    assert auto.damage_source.flat_dps == pytest.approx(20.44)
    assert auto.damage_source.attack_power_per_dps == pytest.approx(14.0)

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "cat form" not in runtime_source


def test_g24_real_cat_auto_attack_repeats_and_swings_during_form_gcd():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    cat_form = next(a for a in ir.actions if a.family_key == "cat_form")
    target = TargetState.with_health("g24-cat-target", 50.0)
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=ir.auto_attacks)

    runtime.schedule_action(cat_form)
    assert actor.current_mode_id == "cat"
    assert actor.gcd_ready_s == pytest.approx(1.5)
    runtime.run_until_idle()
    result = runtime.result()

    expected_hit = (20.44 + 36.0 / 14.0) * 1.0
    swings = [e for e in result.events if e.kind == "AutoAttackSwing"]
    outcomes = [e for e in result.events if e.kind == "AutoAttackOutcome"]
    damage = [e for e in result.events if e.kind == "Damage" and e.payload.get("auto_attack")]
    assert [e.time_s for e in swings] == pytest.approx([1.0, 2.0, 3.0])
    assert swings[0].time_s < actor.gcd_ready_s  # repeated attack timer is independent of the GCD
    assert len(outcomes) == len(damage) == 3
    assert damage[0].payload["amount"] == pytest.approx(expected_hit)
    assert outcomes[0].payload["outcome_weights"] == pytest.approx({"miss": 0.0, "hit": 1.0, "crit": 0.0})
    assert result.auto_attack_damage == pytest.approx(expected_hit * 3.0)
    assert result.target_defeated is True
    assert result.target_death_s == pytest.approx(3.0)
    assert any(e.kind == "AutoAttackStopped" for e in result.events)


def test_g24_leaving_required_mode_stops_the_repeated_swing_timer():
    ir = build_game_ir_slice(class_key="Druid", level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    cat_form = next(a for a in ir.actions if a.family_key == "cat_form")
    cancel = next(a for a in ir.actions if a.id == "cancel_mode:cat")
    target = TargetState.with_health("g24-mode-stop-target", 500.0)
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=ir.auto_attacks)

    runtime.schedule_action(cat_form)
    runtime.advance_to(1.5)
    runtime.schedule_action(cancel)
    runtime.run_until_idle()
    result = runtime.result()

    applied = [
        e for e in result.events
        if e.kind == "Damage" and e.payload.get("auto_attack") and e.payload.get("applied")
    ]
    assert len(applied) == 1
    assert actor.current_mode_id == "caster"
    assert any(e.kind == "AutoAttackStopped" for e in result.events)
    assert any(e.kind == "AutoAttackSwingSkipped" and e.time_s == pytest.approx(2.0) for e in result.events)


def test_g24_auto_attack_damage_source_and_hit_outcome_are_generic():
    actor = ActorState(
        id="warrior-shaped-proof",
        stats={"weapon_dps": 10.0, "attack_power": 28.0},
    )
    attack = AutoAttackDefinition(
        id="auto:mainhand",
        name="Main hand",
        owner_actor_id=actor.id,
        attack_type="melee",
        swing_time_s=2.0,
        school="physical",
        damage_source=AutoAttackDamageSource(
            kind="actor_weapon_dps_plus_attack_power",
            dps_stat_id="weapon_dps",
            attack_power_stat_id="attack_power",
            attack_power_per_dps=14.0,
        ),
        hit_chance=0.8,
        crit_chance_on_landed_hit=0.25,
        crit_multiplier=2.0,
    )
    resolved = expected_auto_attack_swing(attack, actor=actor)
    # raw = (10 + 28/14) * 2 = 24; expected = 24 * (.6 + .2*2) = 24
    assert resolved["raw_hit"] == pytest.approx(24.0)
    assert resolved["outcome_weights"] == pytest.approx({"miss": 0.2, "hit": 0.6, "crit": 0.2})
    assert resolved["expected_damage"] == pytest.approx(24.0)


def test_g24_common_api_and_listener_publish_auto_attack_runtime(tmp_path):
    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    assert record.capability["auto_attack_ir"] is True
    assert record.capability["auto_attack_runtime"] is True
    assert record.capability["auto_attack_scope"] == "generic_repeated_swing_timer_expected_outcome"
    assert "auto_attack_runtime" not in record.unsupported_mechanics
    published_auto = next(a for a in record.actions if a.get("kind") == "auto_attack")
    assert published_auto["id"] == "auto_attack:cat"

    probe = record.provenance["auto_attack_runtime_probe"]
    assert probe["auto_attack_ids"] == ["auto_attack:cat", "auto_attack:bear"]
    assert probe["swing_count"] == 3
    assert probe["damage_event_count"] == 3
    assert probe["first_swing_s"] == pytest.approx(1.0)
    assert probe["gcd_ready_after_enter_s"] == pytest.approx(1.5)
    assert probe["first_swing_during_gcd"] is True
    assert probe["target_defeated"] is True
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
    assert api_record["capability"]["auto_attack_runtime"] is True
    assert api_record["provenance"]["auto_attack_runtime_probe"]["first_swing_during_gcd"] is True
    assert any(a.get("kind") == "auto_attack" for a in api_record["actions"])

    assert "Generic AutoAttack runtime" in DECISIONS_HTML
    assert "function genericAutoAttackSummary(r)" in DECISIONS_HTML

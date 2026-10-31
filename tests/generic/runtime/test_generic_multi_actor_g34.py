from __future__ import annotations

from pathlib import Path

import pytest

from src.game.model import (ActorDefinition, ActionDefinition, AutoAttackDamageSource,
                            AutoAttackDefinition, DamageEffect, ResourceDefinition)
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.multi_actor_probe import execute_multi_actor_mechanics_probe
from src.listener import DECISIONS_HTML
from src.version import SOFTWARE_VERSION


def _instant(actor_id, action_id, *, spell_power_coefficient=0.0, base=2.0):
    return ActionDefinition(
        id=action_id, family_key="probe", name="Probe", owner_actor_id=actor_id,
        requirements=(), costs=(), cast_time_s=0, gcd_s=1.5, cooldown_s=0,
        effects=(DamageEffect(effect_type="damage", school="arcane", target="enemy",
                              base_min=base, base_max=base,
                              spell_power_coefficient=spell_power_coefficient),),
        provenance=(),
    )


def test_g34_real_simultaneous_actor_actions_and_autoattacks_change_kill_time():
    proof = execute_multi_actor_mechanics_probe()
    assert proof["status"] == "executed"
    assert proof["numeric_authority"] == "synthetic_not_forever_pet_tuning"
    assert proof["baseline_kill_s"] == pytest.approx(6)
    assert proof["companion_kill_s"] == pytest.approx(3)
    assert proof["improvement_s"] == pytest.approx(3)
    assert proof["actor_damage"] == {"g34:owner": 40.0, "g34:companion": 20.0}
    assert [(e["time_s"], e["actor_id"], e["payload"]["amount"])
            for e in proof["damage_events"]] == [
                (0.0, "g34:companion", 8.0),
                (2.0, "g34:companion", 12.0),
                (3.0, "g34:owner", 40.0),
            ]
    assert {e["actor_id"] for e in proof["started_events"]} == set(proof["actor_ids"])
    assert {e["time_s"] for e in proof["started_events"]} == {0.0}
    assert any(e["time_s"] == 4 for e in proof["skipped_swing_events"])
    assert proof["legacy_fallback"] is False


def test_g34_resources_regen_and_readiness_remain_actor_owned():
    proof = execute_multi_actor_mechanics_probe()
    assert proof["resources_after"] == {
        "g34:owner": {"energy": 70.0}, "g34:companion": {"energy": 35.0},
    }
    assert proof["readiness"]["g34:owner"]["gcd_ready_s"] == pytest.approx(1.5)
    assert proof["readiness"]["g34:companion"]["gcd_ready_s"] == pytest.approx(1.0)
    assert proof["readiness"]["g34:companion"]["cooldowns"]["g34:companion:bite"] == pytest.approx(2)
    assert proof["readiness"]["g34:owner"]["cooldowns"]["g34:owner:cast"] == pytest.approx(0)


def test_g34_separate_actor_spell_power_and_isolated_action_eligibility():
    primary = ActorState(id="owner", stats={"spell_power": 5})
    pet = ActorState(id="pet", stats={"spell_power": 20})
    runtime = CombatRuntime(actor=primary, companions=(pet,),
                            target=TargetState.with_health("mob", 100), spell_power=5)
    a = _instant("owner", "owner_spell", spell_power_coefficient=1)
    b = _instant("pet", "pet_spell", spell_power_coefficient=1)
    runtime.enqueue_action(a)
    runtime.enqueue_action(b)
    with pytest.raises(ValueError):
        runtime.enqueue_action(_instant("missing", "missing_spell"))
    runtime.advance_to(0)
    assert [(e.actor_id, e.payload["amount"]) for e in runtime.result().events
            if e.kind == "Damage"] == [("owner", 7.0), ("pet", 22.0)]
    assert primary.gcd_ready_s == pet.gcd_ready_s == pytest.approx(1.5)
    assert runtime.actor is primary
    assert all(x.current_time_s == 0 for x in runtime.actors.values())
    with pytest.raises(ValueError):
        runtime.enqueue_action(b)  # pet's own GCD, even if owner action is unrelated


def test_g34_fail_closed_duplicate_owners_and_target_resource_namespace():
    primary = ActorState(id="owner")
    pet = ActorState(id="pet")
    with pytest.raises(ValueError, match="duplicate combat actor id"):
        CombatRuntime(actor=primary, companions=(ActorState(id="owner"),),
                      target=TargetState.with_health("mob", 100))
    pet.current_time_s = 1
    with pytest.raises(ValueError, match="initial encounter clock"):
        CombatRuntime(actor=primary, companions=(pet,), target=TargetState.with_health("mob", 100))
    first = ActorDefinition(id="owner", actor_type="player")
    second = ActorDefinition(id="pet", actor_type="pet")
    r1 = ResourceDefinition(id="combo_points", name="CP", scope="target", owner_actor_id="owner")
    r2 = ResourceDefinition(id="combo_points", name="CP", scope="target", owner_actor_id="pet")
    a = ActorState.from_ir(first, (r1,))
    b = ActorState.from_ir(second, (r2,))
    with pytest.raises(ValueError, match="target resource id"):
        CombatRuntime(actor=a, companions=(b,), target=TargetState.with_health("mob", 100))


def test_g34_backend_listener_scopes_pet_proof_honestly():
    from src.v2.generic_backend import build_partial_generic_records
    record = build_partial_generic_records(class_names=("Druid",), selected_level=12)[0]
    assert record.capability["multi_actor_event_queue"] is True
    assert record.capability["class_pet_policy_modifiers"] is False
    assert "synthetic" in record.capability["multi_actor_scope"]
    assert "class_pet_policy_modifiers" in record.unsupported_mechanics
    probe = record.provenance["multi_actor_runtime_probe"]
    assert probe["actor_damage"]["g34:companion"] == pytest.approx(20)
    assert probe["numeric_authority"] == "synthetic_not_forever_pet_tuning"
    assert "function genericMultiActorSummary(r)" in DECISIONS_HTML
    assert "Generic multi-Actor event queue · engine proof" in DECISIONS_HTML
    assert "${eventTriggerHtml}${multiActorHtml}${timedSummonHtml}${hunterPetHtml}${modeActionPolicyHtml}" in DECISIONS_HTML
    assert SOFTWARE_VERSION == "0.11.48.157"
    assert "druid" not in Path("src/game/runtime/simulator.py").read_text().lower()


def test_g34_http_api_publishes_engine_proof_not_claimed_class_pet(tmp_path):
    import threading
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    store = QueueStore(tmp_path / "queue.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = ServiceClient(
            f"http://127.0.0.1:{server.server_address[1]}", timeout=40
        ).decisions(level=12, backend_id="generic")
        record = next(x for x in response["decisions"] if x["identity"]["class_name"].lower() == "druid")
        assert response["active_backend"] == "generic"
        assert response["generic_routes"]["publication_cache"]["status"] == "validated_release_snapshot"
        assert record["capability"]["multi_actor_event_queue"] is True
        assert record["capability"]["class_pet_policy_modifiers"] is False
        proof = record["provenance"]["multi_actor_runtime_probe"]
        assert proof["companion_kill_s"] == pytest.approx(3)
        assert proof["actor_damage"]["g34:companion"] == pytest.approx(20)
        assert "synthetic" in proof["scope"]
        assert "class_pet_policy_modifiers" in record["unsupported_mechanics"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

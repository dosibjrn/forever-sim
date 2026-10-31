import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.evaluation import Evaluation, evaluation_from_combat_timeline
from src.game.model import DamageEffect, PeriodicEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.shared.leveling.objective import representative_hp
from src.v2.class_model import Evaluation as OptimizerEvaluation
from src.v2.generic_backend import build_partial_generic_records


def _wrath_evaluation(level=20):
    ir = build_game_ir_slice(class_key="druid", level=level)
    assert ir is not None
    action = next(a for a in ir.actions if any(isinstance(e, DamageEffect) for e in a.effects) and not any(isinstance(e, PeriodicEffect) for e in a.effects))
    actor = ActorState.from_ir(ir.actor, ir.resources)
    target = TargetState.with_health("canonical", representative_hp(level), source_status="source_backed_canonical_leveling_reference")
    runtime = CombatRuntime(actor=actor, target=target)
    for _ in range(256):
        if not target.alive:
            break
        eligible = action_eligibility(action=action, actor=actor)
        assert eligible.eligible, eligible.reason
        runtime.schedule_action(action)
    runtime.run_until_idle()
    timeline = runtime.result()
    ev = evaluation_from_combat_timeline(
        timeline,
        action_name_by_id={action.id: action.name},
        provenance={"producer": "test"},
        fidelity={"rating": "test"},
    )
    return ev, timeline


def test_evaluation_contract_is_now_game_layer_authority():
    assert OptimizerEvaluation is Evaluation
    assert Evaluation.__module__ == "src.game.evaluation"


def test_g10_evaluation_is_derived_from_runtime_events():
    ev, timeline = _wrath_evaluation(20)
    assert timeline.target_defeated is True
    assert ev.evaluation_scope == "combat_kill_only"
    assert ev.optimization_ready is False
    assert ev.seconds_per_mob == pytest.approx(20.0)
    assert ev.kill_s_per_100 == pytest.approx(2000.0)
    assert ev.mobs_per_hour is None
    assert ev.resource_metrics["before"]["mana"] == pytest.approx(614.0)
    assert ev.resource_metrics["after"]["mana"] == pytest.approx(214.0)
    assert ev.resource_metrics["mana_spent"] == pytest.approx(400.0)
    assert ev.diagnostics["action_count"] == 10
    assert ev.diagnostics["damage"]["total"] == pytest.approx(517.5)
    assert ev.diagnostics["damage"]["direct"] == pytest.approx(517.5)
    assert ev.diagnostics["damage"]["periodic"] == pytest.approx(0.0)
    assert ev.diagnostics["timing_consistency"]["consistent"] is True
    assert len(ev.diagnostics["action_trace"]) == 10


def test_generic_decision_maps_real_evaluation_without_claiming_leveling_throughput():
    row = build_partial_generic_records(class_names=["druid"], selected_level=20)[0]
    assert row.objective["status"] == "combat_recovery_evaluation"
    assert row.objective["evaluation_scope"] == "combat_plus_recovery"
    assert row.objective["optimization_ready"] is False
    assert row.objective["mobs_per_hour"] is None
    # G10's historical proof is the naked pre-gear evaluation. G20 makes the
    # active decision geared, so do not conflate a later optimizer dimension
    # with this mechanics/evaluation authority.
    naked = row.provenance["naked_evaluation"]
    assert naked["score_s_per_100"] == pytest.approx(1860.8695652173915)
    assert naked["kill_seconds_per_mob"] == pytest.approx(13.5)
    assert naked["recovery_seconds_per_mob"] == pytest.approx(5.108695652173914)
    assert naked["resource_metrics"]["mana_spent"] == pytest.approx(235.0)
    assert naked["diagnostics"]["damage"]["periodic"] > 0
    assert row.timing["complete"] is False
    assert row.timing["event_consistent"] is True
    assert row.capability["combat_evaluation"] is True
    assert row.capability["optimization_ready"] is False
    assert row.provenance["legacy_fallback"] is False
    assert row.capability["multi_action_policy"] is False
    assert row.capability["recovery_evaluation"] is True
    assert "recovery_evaluation" not in row.unsupported_mechanics
    assert "travel_evaluation" in row.unsupported_mechanics
    assert "combat_attack_table_resolution" in row.unsupported_mechanics
    assert "source_backed_target_state" not in row.unsupported_mechanics


def test_non_migrated_class_still_fails_closed():
    row = build_partial_generic_records(class_names=["mage"], selected_level=20)[0]
    assert row.capability["combat_evaluation"] is False
    assert row.objective["status"] == "unsupported"
    assert row.provenance.get("evaluation") is None

def test_listener_renders_canonical_evaluation_backend_neutrally():
    from pathlib import Path
    text = Path("src/listener.py").read_text(encoding="utf-8")
    assert "Canonical Evaluation" in text
    assert "genericEvaluationSummary" in text
    assert "recovery_seconds_per_mob" in text
    assert "combat+recovery" in text
    assert "not optimization-ready" in text

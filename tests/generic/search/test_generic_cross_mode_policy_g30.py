from pathlib import Path
import pytest
from src.game.data.forever import build_game_ir_slice
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.shared.leveling.objective import representative_hp
from src.v2.generic_backend import build_partial_generic_records


def test_g30_mode_state_is_generic_policy_primitive():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    policy = next(p for p in ir.policies if p.provenance.get("g30_scope") == "cross_mode_policy_candidate")
    assert policy.provenance["mode_path"] == ["caster", "cat", "caster", "bear"]
    assert any(c.kind == "mode_state" for r in policy.rules for c in r.conditions)
    source = Path("src/game/policy.py").read_text(encoding="utf-8").lower()
    assert 'kind == "mode_state"' in source
    assert "druid" not in source and "cat form" not in source and "bear form" not in source


def test_g30_cross_mode_candidate_really_transitions_and_changes_time():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    policy = next(p for p in ir.policies if p.provenance.get("g30_scope") == "cross_mode_policy_candidate")
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health("g30", representative_hp(25)), auto_attacks=ir.auto_attacks)
    result = execute_priority_policy(policy=policy, actions=ir.actions, runtime=runtime, max_actions=256)
    assert result.timeline.target_defeated is True
    transitions = [(e.payload.get("from_mode_id"), e.payload.get("to_mode_id")) for e in result.timeline.events if e.kind == "ModeChanged"]
    assert transitions == [("caster", "cat"), ("cat", "caster"), ("caster", "bear")]
    assert result.timeline.target_death_s == pytest.approx(26.0)


def test_g30_search_compares_real_cross_mode_candidate_and_rejects_it_when_slower():
    record = build_partial_generic_records(class_names=("Druid",), selected_level=25)[0]
    assert record.capability["cross_mode_policy_search"] is True
    assert record.capability["cross_mode_policy_search_scope"] == "generic_policy_ir_mode_transition_candidate_selection"
    assert "cross_mode_policy_search" not in record.unsupported_mechanics
    p = record.provenance["cross_mode_policy_probe"]
    assert p["selected_candidate_kind"] == "cat"
    assert p["selected_seconds_per_mob"] == pytest.approx(19.0)
    assert p["cross_mode_seconds_per_mob"] == pytest.approx(26.0)
    assert p["cross_mode_delta_vs_selected_seconds_per_mob"] == pytest.approx(7.0)
    assert [x["to_mode_id"] for x in p["cross_mode_transitions"]] == ["cat", "caster", "bear"]
    assert p["legacy_fallback"] is False


def test_g30_listener_checkpoint_publishes_cross_mode_decision():
    from src.listener import DECISIONS_HTML
    assert "Cross-mode policy search" in DECISIONS_HTML
    assert "function genericCrossModePolicySummary(r)" in DECISIONS_HTML
    assert "crossModePolicyHtml" in DECISIONS_HTML

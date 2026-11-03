"""Work2: a wrong-combat-mode APL must not consume a paid refinement slot.

Uses the actual sourced Druid L20 ability/mode graph; this is a narrow
candidate-admission regression, not a P4/P5/P6 production gate PASS.
"""
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.v2.source_bounded_joint_frontier import _admit_refinement_mode_policy


def _policy(action_id, label):
    return PolicyDefinition(
        id="work2-" + label, label=label,
        rules=(PolicyRuleDefinition(id="damage:1", action_id=action_id),),
        provenance={"authority": "sourced_mode_admission_regression"},
    )


def test_wrong_mode_cannot_exhaust_one_paid_apl_slot():
    ir = build_game_ir_slice(class_key="druid", level=20)
    offensive = {"damage", "direct_damage", "weapon_damage", "periodic_damage",
                 "resource_scaled_direct_damage", "resource_scaled_periodic_damage"}
    by_mode = {}
    for action in ir.actions:
        if not any(getattr(effect, "effect_type", None) in offensive
                   for effect in action.effects):
            continue
        for requirement in action.requirements:
            if requirement.get("kind") == "mode_is":
                by_mode.setdefault(requirement["value"], action.id)
    assert len(by_mode) >= 2, "source must expose two offensive combat forms"
    active_mode, off_mode = sorted(by_mode)[:2]
    rejected = _policy(by_mode[off_mode], "off-mode")
    eligible = _policy(by_mode[active_mode], "active-mode")
    paid_admitted = set()

    assert _admit_refinement_mode_policy(ir, rejected, active_mode,
                                         paid_admitted, 1) is None
    assert paid_admitted == set()  # The observed prior defect charged this slot.
    accepted = _admit_refinement_mode_policy(ir, eligible, active_mode,
                                             paid_admitted, 1)
    assert accepted is not None
    assert paid_admitted == {accepted}
    assert _admit_refinement_mode_policy(ir, eligible, active_mode,
                                         paid_admitted, 1) is None
    assert _admit_refinement_mode_policy(ir, rejected, active_mode,
                                         paid_admitted, 1) is None


def test_unrestricted_refinement_keeps_one_slot_rule():
    ir = build_game_ir_slice(class_key="druid", level=20)
    policy = _policy(ir.actions[0].id, "unrestricted")
    admitted = set()
    assert _admit_refinement_mode_policy(ir, policy, None, admitted, 1)
    assert _admit_refinement_mode_policy(ir, policy, None, admitted, 1) is None

"""Executable RED/GREEN checks for L20 Druid toy-mob P1 ablation.

Runs source GameIR and actual gsim CombatRuntime. A passing gsim probe is
a DIAGNOSTIC ONLY, never a claim of gsim+Rust or full P1 acceptance.
"""
from pathlib import Path

from tools.wf_p1_toy_ablation import (
    _source_actions, _starting_state, compare_action, main, run_gsim,
    EXTRA_PLAYER_HP, TOY_MOB_HP,
)

ROOT = Path(__file__).resolve().parents[1]


def _find(inventory, name):
    matches = [sid for sid, row in inventory.items() if row["name"] == name]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def test_missing_rust_session_never_becomes_a_fake_pass():
    assert main(["--backend", "hybrid-rust"]) == 2


def test_source_legal_l20_feral_includes_all_druid_roles(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-17")
    ir, inventory, matched, _ = _source_actions(ROOT)
    names = {v["name"] for v in inventory.values()}
    # The spec is NOT a permission to exclude caster, healing or bear actions.
    assert {"Claw", "Maul", "Healing Touch", "Wrath", "Moonfire"} <= names
    assert _find(inventory, "Claw") in matched
    assert _find(inventory, "Healing Touch") in matched
    assert ir is not None


def test_one_real_source_wrath_vs_inert_cast(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-17")
    ir, inventory, matched, _ = _source_actions(ROOT)
    sid = _find(inventory, "Wrath")
    action = matched[sid]
    mode = next(m.id for m in ir.modes if m.enabled_action_ids is None or action.id in m.enabled_action_ids)
    actor, target = _starting_state(ir, action, mode)
    assert target.health == TOY_MOB_HP
    assert actor.resource_capacity["health"] >= EXTRA_PLAYER_HP

    result = compare_action(ir, action)
    assert result["status"] == "EFFECT_OBSERVED", result
    assert ("mob_hp" in result["difference"]
            or "damage_dealt" in result["difference"]), result
    # Costs/timing are equal in the zero-effect counterpart; damage is not.
    assert result["difference"]["mob_hp"]["real"] < result["difference"]["mob_hp"]["without_effect"]

    report = run_gsim(ability_id=sid)
    assert report["observed"] == 1 and report["checked"] == 1
    assert report["p1_certified"] is False
    assert report["hybrid_rust_executed"] is False
    assert "NOT_HYBRID_RUST" in report["proof_kind"]


def test_one_real_source_heal_vs_inert_cast(monkeypatch):
    monkeypatch.setenv("WOW_FOREVER_BUILD_AS_OF", "2026-10-17")
    ir, inventory, matched, _ = _source_actions(ROOT)
    sid = _find(inventory, "Healing Touch")
    result = compare_action(ir, matched[sid])
    assert result["status"] == "EFFECT_OBSERVED", result
    assert ("player_hp" in result["difference"]
            or "healing" in result["difference"]), result

"""Only Forever-owned native request/response transport and existing P3 field wiring."""
import json
from types import SimpleNamespace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model.ir import WeaponDamageEffect
from src.game.native_p3_player_context import (
    NativePlayerContextError, apply_native_player_context,
    query_native_player_context,
)


def _native_response():
    # Shape and source values from the draft MythicSim player-context contract.
    # This fixture is a transport test, not independent validation of Rust facts.
    return {
        "status": "ok",
        "context_kind": "source_backed_baseline_context_not_full_native_sim_actor",
        "source_context_id": "paladin-dwarf-l20-worn-mace-v1",
        "source_scope": "inherited_vanilla_classic_not_forever_verified",
        "class": "paladin", "level": 20, "race": "dwarf",
        "base_stats": {
            "strength": 47.0, "agility": 28.0, "stamina": 46.0,
            "intellect": 32.0, "spirit": 35.0,
            "attack_power": 134.0, "armor": 56.0,
        },
        "resources": {"max_health": 471.0, "max_mana": 612.0},
        "weapon": {
            "item_id": 36, "weapon_dps": 2.0 / 1.9,
            "weapon_speed_s": 1.9, "weapon_damage_min": 1.0,
            "weapon_damage_max": 3.0,
        },
        "unsupported_fields": ["melee_crit_percent", "spell_crit_percent"],
        "provenance": {"primary_stats": {"provider": "cmangos/mangos-classic"}},
    }


def test_native_player_context_forwards_exact_request_without_python_game_rules():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(_native_response()),
                               stderr="")

    result = query_native_player_context(
        "/selected/rust/forever-engine", "paladin", 20, runner=runner)
    assert result["weapon"]["item_id"] == 36
    assert calls[0][0] == [
        "/selected/rust/forever-engine", "player-context",
        "--class", "paladin", "--level", "20"]
    assert calls[0][1]["timeout"] == 60


def test_native_context_replaces_paladin_proxy_actor_weapon_and_weapon_effect():
    ir = build_game_ir_slice(class_key="paladin", level=20)
    assert ir.actor.metadata["base_stats_are_zero_proxy"] is True
    old_action_ids = tuple(action.id for action in ir.actions)
    old_auto = ir.auto_attacks[0]
    assert old_auto.damage_source.flat_dps == 14.0

    selected = apply_native_player_context(ir, _native_response())
    assert tuple(action.id for action in selected.actions) == old_action_ids
    assert selected.actor.base_stats["strength"] == 47.0
    assert selected.actor.base_stats["attack_power"] == 134.0
    assert selected.actor.metadata["race_key"] == "dwarf"
    assert selected.actor.metadata["base_stats_are_zero_proxy"] is False
    assert selected.actor.metadata["weapon_speed_s"] == 1.9
    assert selected.actor.state_status.endswith("not_full_sim_actor")
    resources = {r.id: r for r in selected.resources}
    assert resources["health"].capacity == 471.0
    assert resources["mana"].capacity == 612.0
    assert resources["mana"].regeneration_per_s == next(
        r.regeneration_per_s for r in ir.resources if r.id == "mana")
    assert selected.auto_attacks[0].swing_time_s == 1.9
    assert selected.auto_attacks[0].damage_source.flat_dps == pytest.approx(2 / 1.9)
    assert all("proxy" not in str(x.get("caveat") or "")
               for attack in selected.auto_attacks for x in attack.provenance)
    effects = [
        effect for action in selected.actions for effect in action.effects
        if isinstance(effect, WeaponDamageEffect)]
    assert effects, "Paladin sourced Holy Strike still uses the equipped weapon"
    assert all(effect.damage_source.flat_dps == pytest.approx(2 / 1.9)
               and effect.weapon_damage_time_s == 1.9 for effect in effects)
    assert any(x.get("code") == "native_player_context_not_full_native_sim_actor"
               for x in selected.unsupported_semantics)


@pytest.mark.parametrize("change", [
    {"class": "warrior"},
    {"level": 60},
    {"status": "partial"},
    {"context_kind": "proxy"},
    {"source_context_id": ""},
    {"base_stats": {}},
])
def test_native_player_context_rejects_wrong_or_unusable_response(change):
    payload = {**_native_response(), **change}

    def runner(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    with pytest.raises(NativePlayerContextError):
        query_native_player_context("engine", "paladin", 20, runner=runner)


def test_native_player_context_preserves_native_refusal():
    def runner(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "refused", "refusal": {
                "code": "unsupported_player_context"}}),
            stderr="")
    with pytest.raises(NativePlayerContextError, match="unsupported_player_context"):
        query_native_player_context("engine", "paladin", 20, runner=runner)


def test_paladin_p3_queries_selected_native_engine_without_separate_context_env(
        monkeypatch, tmp_path):
    """Omitting the redundant context env must not silently use proxy stats."""
    from tools.wf_gate_p3_live import run_live
    import src.game.native_p3_player_context as native_context

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "/selected/forever-engine")
    monkeypatch.delenv("FOREVER_P3_NATIVE_PLAYER_CONTEXT_BIN", raising=False)
    calls = []

    def native_refusal(binary, class_key, level):
        calls.append((binary, class_key, level))
        raise NativePlayerContextError("P3_NATIVE_PLAYER_CONTEXT_REFUSED:TEST")

    monkeypatch.setattr(native_context, "query_native_player_context", native_refusal)
    report = run_live(tmp_path, "paladin", 20, spec="unrestricted")
    assert calls == [("/selected/forever-engine", "paladin", 20)]
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P3_NATIVE_PLAYER_CONTEXT_REFUSED:TEST"]
    assert report["production_component"] == "src.game.native_p3_player_context"

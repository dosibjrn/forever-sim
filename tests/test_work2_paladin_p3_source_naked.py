"""Work2 #845: reproduce the Paladin L20 P3 naked-search boundary.

The stateful auto continuation is a useful diagnostic, but its current actor
and weapon values are explicitly scenario proxies. Never promote that result
to P3 evidence until a source-backed actor/weapon context replaces them.
"""
import json
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.v2.source_budgeted_prefix import AUTO_ONLY_FALLBACK
from src.v2.source_stateful_budgeted import _make_policy


def test_paladin_l20_stateful_auto_fallback_reproduces_within_44_evaluations():
    ir = build_game_ir_slice(class_key="paladin", level=20)
    result = run_source_budgeted_gear(
        class_key="paladin", level=20, ir_slice=ir,
        max_evaluations=44, initial_search=22, search_per_gear=12,
        max_gear_states=2,
        probe_stats=("agility", "strength", "stamina"),
        probe_deltas=(5.0,),
        schedule_incoming_attacks=True,
        required_level_policy="observed",
        policy_search_backend="stateful",
        stateful_search_auto_fallback=True,
        stateful_use_l1=False,
        max_event_transitions=7000,
    )
    assert result["status"] == "EVALUATED_BOUNDED", result
    assert result["attempted"] <= 44, result
    naked = next(stage for stage in result["stages"]
                 if stage["stage"] == "source_naked")
    winner = naked["winner"]
    assert winner and winner["fallback"] == AUTO_ONLY_FALLBACK, result

    # Prove that the fallback is the existing runtime auto event, not a
    # fabricated action inserted into GameIR.
    policy = _make_policy(
        ir, winner["fallback"],
        guarded_action=winner.get("guarded_action"),
        guarded_conditions=tuple(winner.get("guarded_conditions", ())),
    )
    evaluation, execution, details = _policy_combat_evaluation(
        ir, level=20, policy_override=policy,
        opening_action_ids=tuple(winner["prefix"]),
        schedule_incoming_attacks=True,
    )
    assert evaluation is not None, result
    assert execution.timeline.target_defeated
    assert details["actor_survived"]
    assert any(event.kind == "AutoAttackSwing"
               for event in execution.timeline.events)
    assert AUTO_ONLY_FALLBACK not in {action.id for action in ir.actions}

    # The existing capture explicitly labels both the naked actor and its
    # ordinary weapon DPS/speed as proxies. This is why the result is not
    # eligible to be wired into the P3 production caller.
    assert ir.actor.metadata["base_stats_are_zero_proxy"] is True
    assert ir.actor.state_status == "qualified_native_class_actor_scenario_not_final"
    assert ir.actor.provenance[0]["authority"] == "scenario_proxy_not_source_backed"
    auto = next(a for a in ir.auto_attacks if a.owner_actor_id == ir.actor.id)
    assert auto.damage_source.flat_dps == 14.0
    assert auto.provenance[0]["caveat"] == (
        "ordinary_melee_auto_and_weapon_speed_scenario_proxy"
    )

    print("PALADIN_L20_STATEFUL_44_DIAGNOSTIC", json.dumps({
        "status": result["status"],
        "attempted": result["attempted"],
        "evaluated": result["evaluated"],
        "source_naked_prefix": winner["prefix"],
        "fallback": winner["fallback"],
        "auto_attack_swing": True,
        "actor_base_stats_proxy": True,
        "weapon_dps_proxy": auto.damage_source.flat_dps,
        "weapon_source_caveat": auto.provenance[0]["caveat"],
    }, sort_keys=True), flush=True)

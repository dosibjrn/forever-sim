"""WF-COMBAT231: sourced ordinary enemy swings in the actual policy/recovery scorer.

Opt-in is deliberately explicit until base Armor and cross-class incoming facts are
source-complete. These are not isolated incoming-hit probes.
"""
from dataclasses import replace

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.gear import apply_gear_selection
from src.game.model import ActorDefinition, IncomingAttackDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.policy import execute_priority_policy
from src.v2.generic_backend import _policy_combat_evaluation


def _geared(*, armor=100, mp5=200):
    source = build_source_slice(20)
    geared, report = apply_gear_selection(source, aggregate_stats={'armor': armor, 'mp5': mp5})
    assert report.applied_stats['armor'] == armor
    return geared


def test_production_policy_same_actor_health_and_recovery_timing():
    geared = _geared()
    without, _, old = _policy_combat_evaluation(geared, level=20)
    with_hits, execution, details = _policy_combat_evaluation(
        geared, level=20, schedule_incoming_attacks=True)
    assert with_hits is not None and without is not None
    assert details['incoming_schedule_executed']
    assert details['incoming_hit_count'] > 1
    hits = [event for event in execution.timeline.events if event.kind == 'IncomingAttackResolved']
    assert [event.time_s for event in hits] == pytest.approx([2.0 * i for i in range(1, len(hits) + 1)])
    assert hits[-1].time_s <= execution.timeline.target_death_s
    assert execution.timeline.end_time_s == pytest.approx(execution.timeline.target_death_s)
    assert details['recovery']['start_time_s'] == pytest.approx(execution.timeline.target_death_s)
    assert details['recovery']['health_missing_before'] > 0
    assert old['recovery']['health_missing_before'] == 0
    assert with_hits.seconds_per_mob > without.seconds_per_mob
    assert with_hits.kill_s_per_100 == pytest.approx(without.kill_s_per_100)
    assert not with_hits.optimization_ready  # source/route fidelity still blocked


def test_named_armor_changes_policy_score_via_health_and_recovery():
    low = _geared(armor=100)
    high = _geared(armor=700)
    e_low, t_low, d_low = _policy_combat_evaluation(low, level=20, schedule_incoming_attacks=True)
    e_high, t_high, d_high = _policy_combat_evaluation(high, level=20, schedule_incoming_attacks=True)
    assert e_low and e_high
    assert t_low.timeline.target_defeated and t_high.timeline.target_defeated
    assert d_low['incoming_hit_count'] == d_high['incoming_hit_count']
    assert d_high['recovery']['health_missing_before'] < d_low['recovery']['health_missing_before']
    assert e_high.seconds_per_mob < e_low.seconds_per_mob


def test_sourced_agility_armor_allows_naked_incoming_scorer_without_fabricated_zero():
    source = build_source_slice(20)
    assert source.actor.base_stats['armor'] == pytest.approx(source.actor.base_stats['agility'] * 2)
    result, execution, details = _policy_combat_evaluation(source, level=20, schedule_incoming_attacks=True)
    assert result is not None and execution.timeline.target_defeated
    assert details['incoming_hit_count'] > 0
    # Removing the sourced stat must still fail closed, not silently assume zero.
    actor = replace(source.actor, base_stats={k:v for k,v in source.actor.base_stats.items() if k != 'armor'})
    with pytest.raises(ValueError, match="requires actor stat 'armor'"):
        _policy_combat_evaluation(replace(source, actor=actor), level=20, schedule_incoming_attacks=True)


def test_source_cadence_and_mitigation_fail_closed():
    source = _geared()
    attack = source.incoming_attacks[0]
    actor = ActorState.from_ir(source.actor, source.resources, source.modes)
    def runtime(*, incoming, mitigation=source.mitigation_rules):
        return CombatRuntime(actor=actor, target=TargetState.with_health('dummy', 1000),
                             incoming_attacks=(incoming,), mitigation_rules=mitigation)
    with pytest.raises(ValueError, match='positive sourced cadence'):
        runtime(incoming=replace(attack, metadata={}))
    with pytest.raises(ValueError, match='missing mitigation rule'):
        runtime(incoming=attack, mitigation=())
    with pytest.raises(ValueError, match='unsupported source/outcome'):
        runtime(incoming=replace(attack, hit_chance=0.0))
    with pytest.raises(ValueError, match='unsupported source/outcome'):
        runtime(incoming=replace(attack, provenance=()))


def test_player_death_blocks_score_and_no_infinite_incoming_queue():
    source = _geared()
    hit = replace(source.incoming_attacks[0], raw_damage=1000.0)
    modified = replace(source, incoming_attacks=(hit,))
    result, execution, details = _policy_combat_evaluation(
        modified, level=20, schedule_incoming_attacks=True)
    assert result is None
    assert details['stop_reason'] == 'actor_died'
    assert not details['actor_survived']
    assert details['incoming_hit_count'] >= 1
    assert any(e.kind == 'ActorDied' for e in execution.timeline.events)
    assert len(execution.timeline.events) < 150


def test_generic_non_druid_actor_can_be_scheduled_with_own_resource():
    actor_def = ActorDefinition(id='unit', actor_type='player', base_stats={'armor': 80.0}, metadata={'level': 10})
    hp = ResourceDefinition(id='vitality', name='Vitality', owner_actor_id='unit', capacity=100, initial_amount=100)
    actor = ActorState.from_ir(actor_def, (hp,))
    attack = IncomingAttackDefinition(
        id='synthetic-hit', name='Synthetic hit', source_actor_id='mob', target_actor_id='unit',
        school='shadow', raw_damage=10, hit_chance=1, health_resource_id='vitality',
        provenance=({'authority': 'synthetic_test'},), metadata={'representative_swing_s': 3.0},
    )
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('enemy', 10),
                            incoming_attacks=(attack,))
    runtime.advance_to(7)
    assert actor.resource_amount('vitality') == pytest.approx(80)
    assert [e.time_s for e in runtime.result().events if e.kind == 'IncomingAttackResolved'] == [3, 6]
    runtime.target.health = 0
    runtime.target.alive = False
    runtime.run_until_idle()
    assert actor.resource_amount('vitality') == pytest.approx(80)


def test_real_mode_policy_discovery_can_opt_into_same_incoming_scorer():
    from src.v2.source_mode_search import evaluate_discovered_mode_search
    ir, report = apply_gear_selection(build_source_slice(20), aggregate_stats={
        'armor': 700, 'strength': 30, 'mp5': 50,
    })
    assert report.applied_stats['armor'] == 700
    result = evaluate_discovered_mode_search(
        class_key='druid', level=20, ir_slice=ir,
        max_policies_per_path=24, schedule_incoming_attacks=True)
    assert result['status'] == 'EVALUATED_SOURCE_MODE_POLICY'
    assert result['evaluated_count'] > 0
    assert result['winner']['recovery_s'] > 0
    assert result['winner']['combat_kill_s'] > 0
    assert not result['optimization_ready']  # still bounded/incomplete

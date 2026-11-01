"""Real Rogue L20 source action + CombatRuntime: resource-guarded APL must wait for genuine energy regen."""
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.shared.leveling.objective import representative_hp


def _sourced_guarded_encounter(*, regen_enabled: bool, impossible_threshold: bool = False):
    ir = build_game_ir_slice(class_key='rogue', level=20)
    action = next(a for a in ir.actions if a.id == 'sinister_strike:1758')
    cost = sum(float(c.amount) for c in action.costs if c.resource_id == 'energy')
    assert cost > 5
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    assert actor.resource_regeneration_per_s['energy'] > 0
    actor.resources['energy'] = cost - 5.0
    if not regen_enabled:
        actor.resource_regeneration_per_s['energy'] = 0.0
    guard = (PolicyCondition(kind='resource_threshold', resource_id='energy',
        value=float(actor.resource_capacity['energy']) + 1.0) if impossible_threshold else
        PolicyCondition(kind='resource_threshold', resource_id='energy',
            threshold_source='action_cost'))
    policy = PolicyDefinition(id='source_rogue_energy_guard',
        label='Source Rogue builder gated by its actual energy cost',
        rules=(PolicyRuleDefinition(id='source_builder', action_id=action.id,
            conditions=(guard,)),))
    target = TargetState.with_health('canonical_leveling_target_L20',
        float(representative_hp(20)), level=20)
    runtime = CombatRuntime(actor=actor, target=target)
    result = execute_priority_policy(policy=policy, actions=ir.actions,
        runtime=runtime, max_actions=256)
    return result, runtime, cost


def test_sourced_rogue_guard_waits_for_actual_energy_regeneration():
    result, runtime, cost = _sourced_guarded_encounter(regen_enabled=True)
    assert result.stopped_reason is None
    assert result.timeline.target_defeated
    assert result.selected_actions
    first = result.selected_actions[0]
    assert first['action_id'] == 'sinister_strike:1758'
    assert first['start_time_s'] >= 5.0 / 10.0 - 1e-7
    assert any(e.kind == 'ResourceRegenerated' for e in result.timeline.events)


def test_sourced_rogue_guard_does_not_invent_energy_when_regen_absent():
    result, runtime, cost = _sourced_guarded_encounter(regen_enabled=False)
    assert result.stopped_reason == 'no legal policy action'
    assert not result.selected_actions
    assert not result.timeline.target_defeated
    assert runtime.actor.resource_amount('energy') == cost - 5.0


def test_sourced_rogue_guard_above_capacity_does_not_wait_forever():
    result, runtime, cost = _sourced_guarded_encounter(
        regen_enabled=True, impossible_threshold=True)
    assert result.stopped_reason == 'no legal policy action'
    assert not result.selected_actions
    assert not result.timeline.target_defeated


def test_sourced_rogue_cost_above_capacity_never_schedules_impossible_regen_wait():
    """The real sourced builder cannot become affordable above actor capacity."""
    from src.game.runtime import action_eligibility
    ir = build_game_ir_slice(class_key='rogue', level=20)
    action = next(a for a in ir.actions if a.id == 'sinister_strike:1758')
    cost = sum(float(c.amount) for c in action.costs if c.resource_id == 'energy')
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    assert cost > 5 and actor.resource_regeneration_per_s['energy'] > 0
    actor.resource_capacity['energy'] = cost - 1.0
    actor.resources['energy'] = cost - 5.0
    target = TargetState.with_health('canonical_leveling_target_L20',
        float(representative_hp(20)), level=20)
    eligibility = action_eligibility(action=action, actor=actor, target=target)
    assert not eligibility.eligible
    assert eligibility.reason.startswith('insufficient energy:')
    assert eligibility.next_ready_s == actor.current_time_s

    policy = PolicyDefinition(id='source_rogue_impossible_cost',
        label='Source Rogue builder with impossible resource capacity',
        rules=(PolicyRuleDefinition(id='source_builder', action_id=action.id),))
    runtime = CombatRuntime(actor=actor, target=target)
    result = execute_priority_policy(policy=policy, actions=ir.actions,
        runtime=runtime, max_actions=256)
    assert result.stopped_reason == 'no legal policy action'
    assert not result.selected_actions
    assert actor.current_time_s == 0.0


def test_sourced_rogue_affordable_cost_still_waits_for_real_regeneration():
    """Do not break normal unguarded source actions while fixing impossible waits."""
    ir = build_game_ir_slice(class_key='rogue', level=20)
    action = next(a for a in ir.actions if a.id == 'sinister_strike:1758')
    cost = sum(float(c.amount) for c in action.costs if c.resource_id == 'energy')
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    assert actor.resource_capacity['energy'] >= cost
    actor.resources['energy'] = cost - 5.0
    policy = PolicyDefinition(id='source_rogue_unguarded_regen',
        label='Source Rogue unguarded builder with paid energy regeneration',
        rules=(PolicyRuleDefinition(id='source_builder', action_id=action.id),))
    runtime = CombatRuntime(actor=actor,
        target=TargetState.with_health('canonical_leveling_target_L20',
            float(representative_hp(20)), level=20))
    result = execute_priority_policy(policy=policy, actions=ir.actions,
        runtime=runtime, max_actions=256)
    assert result.stopped_reason is None
    assert result.timeline.target_defeated
    assert result.selected_actions[0]['start_time_s'] >= 0.5 - 1e-7
    assert any(e.kind == 'ResourceRegenerated' for e in result.timeline.events)

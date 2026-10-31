"""WF379 RED: source Mage hard casts pause, not cancel, the shared 2D route."""
from dataclasses import replace

import pytest
from src.game.data.forever import build_game_ir_slice
from src.game.model import DamageEffect, PolicyDefinition, PolicyRuleDefinition
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _fixture():
    ir = build_game_ir_slice(class_key='mage', level=30)
    bolt = next(a for a in ir.actions if a.family_key == 'frostbolt')
    blast = next(a for a in ir.actions if a.family_key == 'fire_blast')
    bolt = replace(bolt, costs=(), cooldown_s=0., gcd_s=0.,
                   effects=(DamageEffect('damage', 'frost', 'enemy', 100., 100.),))
    blast = replace(blast, costs=(), cooldown_s=0., gcd_s=0.,
                    effects=(DamageEffect('damage', 'fire', 'enemy', 100., 100.),))
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    enemies = [TargetState.with_health('m0', 200.), TargetState.with_health('m1', 200.)]
    runtime = CombatRuntime(actor=actor, target=enemies[0], other_targets=(enemies[1],),
        spatial_positions_yards={'m0': (0.,0.), 'm1':(20.,0.)},
        incoming_attacks=())
    runtime.begin_player_route(((20.,0.),), speed_yards_s=5., step_yards=2.)
    return runtime, bolt, blast, enemies


def test_apl_mage_frostbolt_pauses_walk_until_cast_finishes_and_resumes_remaining_route():
    runtime, bolt, _, enemies = _fixture()
    policy = PolicyDefinition(id='mage:test:bolt', label='Hard cast priority',
        rules=(PolicyRuleDefinition('bolt', bolt.id),))
    result = execute_priority_policy(policy=policy, actions=(bolt,), runtime=runtime, max_actions=1)
    assert len(result.selected_actions) == 1
    assert not result.timeline.target_defeated  # scenario intentionally remains in combat
    assert result.selected_actions[0]['start_time_s'] == pytest.approx(0.)
    steps = [e for e in runtime.trace if e.kind == 'SpatialPlayerMoveStep']
    assert steps, 'route did not resume after cast'
    assert min(e.time_s for e in steps) >= bolt.cast_time_s
    assert runtime.player_position_yards == pytest.approx((20.,0.))


def test_apl_mage_instant_fire_blast_does_not_pause_route():
    runtime, _, blast, enemies = _fixture()
    policy = PolicyDefinition(id='mage:test:blast', label='Instant priority',
        rules=(PolicyRuleDefinition('blast', blast.id),))
    result = execute_priority_policy(policy=policy, actions=(blast,), runtime=runtime, max_actions=1)
    assert len(result.selected_actions) == 1
    assert not result.timeline.target_defeated
    steps = [e for e in runtime.trace if e.kind == 'SpatialPlayerMoveStep']
    assert steps
    assert min(e.time_s for e in steps) == pytest.approx(0.4)
    assert runtime.player_position_yards == pytest.approx((20.,0.))

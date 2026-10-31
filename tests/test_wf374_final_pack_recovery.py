"""Final pack resource debt must be charged in the canonical 100-mob objective."""

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls


@pytest.mark.parametrize('pack_size', [2, 3])
def test_threshold_recovery_charges_last_pack_even_when_its_index_is_not_mob_count(pack_size):
    ir = build_game_ir_slice(class_key='druid', level=30)
    wrath = next(a for a in ir.actions if a.family_key == 'wrath')
    policy = PolicyDefinition(id='wf374:wrath', label='Source Wrath', rules=(
        PolicyRuleDefinition(id='wf374:wrath:rule', action_id=wrath.id),))
    result = evaluate_repeated_pulls(
        ir_slice=ir, policy=policy, level=30, target_health=20,
        count=4, pack_size=pack_size, recovery_mode='threshold',
        recovery_mana_fraction=0.1, schedule_incoming_attacks=False)
    assert sum(p['mob_count'] for p in result.pulls) == 4
    assert not result.pulls[0]['recovery_performed']
    assert result.pulls[-1]['recovery_performed'], 'last pack must pay deferred mana debt'
    assert result.pulls[-1]['recovery_s'] > 0
    assert result.actor.resource_amount('mana') == pytest.approx(result.actor.resource_capacity['mana'])

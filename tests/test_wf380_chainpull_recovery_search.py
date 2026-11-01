"""TDD: source combat + real cooldowns decide when to recover, not a hardcoded Mage script."""

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.recovery_threshold_search import search_recovery_thresholds


def test_100mob_chainpull_search_beats_always_recover_for_mage_source_case():
    ir=build_game_ir_slice(class_key='mage',level=30)
    frost=next(a for a in ir.actions if a.family_key=='frostbolt')
    policy=PolicyDefinition(id='recovery:source-frost',label='Source Frostbolt',rules=(
        PolicyRuleDefinition(id='frost',action_id=frost.id),))
    result=search_recovery_thresholds(
        ir_slice=ir,policy=policy,level=30,target_health=150,count=100,
        schedule_incoming_attacks=False,health_fractions=(0.5,),
        mana_fractions=(0.1,0.3,0.6),include_always=True)
    assert result['total_candidates']==4
    assert result['evaluated']==4
    assert result['best']['seconds_per_mob']<result['baseline_always']['seconds_per_mob']
    assert result['best']['recovery_calls']<100
    assert result['best']['mobs_killed']==100
    assert result['best']['mana_threshold'] == 0.1
    assert all(row['mobs_killed']==100 for row in result['candidates'] if row['status']=='COMPLETE')


def test_recovery_search_fail_closed_invalid_thresholds_and_budgets():
    import pytest
    ir=build_game_ir_slice(class_key='mage',level=30)
    frost=next(a for a in ir.actions if a.family_key=='frostbolt')
    policy=PolicyDefinition(id='recovery:source-frost',label='Source Frostbolt',rules=(
        PolicyRuleDefinition(id='frost',action_id=frost.id),))
    with pytest.raises(ValueError,match='threshold'):
        search_recovery_thresholds(ir_slice=ir,policy=policy,level=30,
           target_health=150,count=5,health_fractions=(0.5,),mana_fractions=(-0.1,))
    with pytest.raises(ValueError,match='candidate'):
        search_recovery_thresholds(ir_slice=ir,policy=policy,level=30,
           target_health=150,count=5,health_fractions=(),mana_fractions=(),include_always=False)

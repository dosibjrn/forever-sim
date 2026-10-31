"""P00c independent negative fixtures and real L10->11 source continuation."""
from dataclasses import replace
import pytest
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.game.level_legality import require_exact_talent_ranks
from src.game.data.forever import build_game_ir_slice
from src.v2.level_evaluation_trace import evaluate_legal_level_continuation

P=LevelState('druid',10,'tauren',{'improved_wrath':1},('wrath:5177',))
C=LevelState('druid',11,'tauren',{'improved_wrath':2},('wrath:5177',))

def test_source_legality_is_scorer_independent():
    a=validate_level_state(P)
    b=validate_level_transition(P,C)
    assert a['gear_verified']=='naked_only'
    assert b['talent_changes']=={'improved_wrath':1}
    assert b['available_unspent_after']==0
    assert b['resource_carry_forward_proven'] is False
    assert not b['optimization_ready']

def test_real_evaluated_child_not_full_optimizer():
    out=evaluate_legal_level_continuation(parent=P,child=C)
    assert out['status']=='EVALUATED_LEGAL_CONTINUATION'
    assert out['child_trace']['evaluation']['seconds_per_mob']>0
    assert out['child_trace']['talent']['spent_points']==2
    assert out['child_trace']['status']=='EVALUATED'
    assert not out['optimization_ready']

@pytest.mark.parametrize('parent,child,why',[
    (P,replace(C,talents={'improved_wrath':1}),None), # legal banking
    (P,replace(C,level=13),'nonconsecutive'),
    (P,replace(C,race_key='night_elf'),'race change'),
    (P,replace(C,class_key='mage'),'class identity mismatch'),
    (P,replace(C,action_ids=('wrath:unknown_rank',)),'action/rank unavailable'),
    (P,replace(C,selected_items=('item:999',)),'named gear legality'),
    (P,replace(C,gear_scenario='invented_gear'),'named gear legality'),
    (P,replace(C,talents={'improved_wrath':3}),'budget'),
    (P,replace(C,talents={}), 'talent refund'),
    (replace(P,talents={}),replace(C,talents={'improved_wrath':2}),None), # banked L10 point
])
def test_transition_cases(parent,child,why):
    if why is None:
        assert validate_level_transition(parent,child)['status']=='LEGAL_SOURCE_TRANSITION'
    else:
        with pytest.raises(ValueError,match=why):
            validate_level_transition(parent,child)

def test_p00b_missing_respec_gate_now_enforced_before_scoring(monkeypatch):
    from src.v2 import level_evaluation_trace as trace
    def should_not_run(**kwargs):
        raise AssertionError('combat must not execute for illegal transition')
    monkeypatch.setattr(trace,'evaluate_level_trace',should_not_run)
    with pytest.raises(ValueError,match='talent refund'):
        trace.evaluate_legal_level_continuation(parent=P,child=replace(C,talents={}))

def test_fractional_and_boolean_talent_ranks_fail_closed():
    ir=build_game_ir_slice(class_key='druid',level=11)
    for rank in (1.5,True,'1'):
        with pytest.raises(ValueError,match='exact integers'):
            require_exact_talent_ranks({'improved_wrath':rank})

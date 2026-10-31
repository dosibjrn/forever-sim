import pytest
from src.v2.level_evaluation_trace import evaluate_level_trace, compare_level_candidates

A=('moonfire:8924','wrath:5177')
B=('wrath:5177',)

def trace(actions=B, talent=None):
    return evaluate_level_trace(class_key='druid',level=10,talent_selection={'improved_wrath':1} if talent is None else talent,candidate_action_ids=actions)

def test_real_two_candidate_comparison():
    result=compare_level_candidates(class_key='druid',level=10,talent_selection={'improved_wrath':1},candidates={'canonical':A,'wrath_only':B})
    assert result['difference_seconds_per_mob']>0
    assert result['winner']=='wrath_only'
    assert not result['complete_optimizer']
    for row in result['traces'].values():
        assert row['evaluation']['seconds_per_mob']>0
        assert row['combat']['resources_before']['mana']>row['combat']['resources_after']['mana']
        assert row['recovery']['total_s']>=0
        assert row['next_state']['resources']==row['recovery']['resources_after']
        assert row['gear']['named_items']==[]
        assert not row['optimization_ready']

def test_illegal_talent_points():
    with pytest.raises(ValueError,match='budget'):
        trace(talent={'improved_wrath':2})

def test_illegal_action():
    with pytest.raises(ValueError,match='unavailable action'):
        trace(actions=('unknown:999',))

def test_healing_action_not_combat_candidate():
    with pytest.raises(ValueError,match='canonical combat'):
        trace(actions=('healing_touch:rank@8',))

def test_no_fake_completeness():
    row=trace()
    assert row['status']=='EVALUATED'
    assert row['evaluation']['travel_seconds_per_mob'] is None
    assert not row['evaluation']['timing_complete']
    assert row['talent']['spent_points']==1

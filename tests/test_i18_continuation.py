from __future__ import annotations

from src.v2.constrained_routes import analyze_constraint


def _candidate(cost: float, *, name: str, mph: float, steps: list[dict]) -> dict:
    return {
        'allocation': name,
        'cumulative_objective_s': cost,
        'mobs_per_hour': mph,
        'talent_ranks': dict(steps[-1].get('talent_ranks') or {}),
        'steps': steps,
    }


def test_i18_exact_current_allocation_does_not_accept_extra_current_talents():
    wrong = _candidate(100.0, name='wrong', mph=220, steps=[
        {'level':20,'talent_ranks':{'a':5,'b':1},'allocation':'a5+b1'},
        {'level':21,'talent_ranks':{'a':5,'b':1,'x':1},'allocation':'wrong21','talent_added':'x:1'},
        {'level':22,'talent_ranks':{'a':5,'b':1,'x':2},'allocation':'wrong22','talent_added':'x:2'},
    ])
    mine = _candidate(104.0, name='mine', mph=210, steps=[
        {'level':20,'talent_ranks':{'a':5},'allocation':'a5'},
        {'level':21,'talent_ranks':{'a':5,'c':1},'allocation':'mine21','talent_added':'c:1'},
        {'level':22,'talent_ranks':{'a':5,'c':2},'allocation':'mine22','talent_added':'c:2'},
    ])
    frontier={'class':'druid','levels':[{'level':22,'candidates':[wrong,mine]}]}
    out=analyze_constraint(frontier,22,{
        'at_level':20,
        'at_level_talent_allocation_exact':{'a':5},
    })
    assert out['status']=='available'
    assert out['path']['allocation']=='mine'
    assert out['continuation_mode']=='exact_current_allocation_no_respec'
    assert out['continuation']['next_talent_pick']['level']==21
    assert out['continuation']['next_talent_pick']['talent_added']=='c:1'
    assert out['regret_percent']==4.0
    assert out['unrestricted_path']['allocation']=='wrong'


def test_i18_continuation_publishes_next_meaningful_transition():
    route = _candidate(100.0, name='route', mph=200, steps=[
        {'level':20,'talent_ranks':{'a':5},'allocation':'a5','talent_family':'feral','combat_profile':'bear'},
        {'level':21,'talent_ranks':{'a':5,'c':1},'allocation':'a5+c1','talent_family':'feral','combat_profile':'bear','talent_added':'c:1'},
        {'level':22,'talent_ranks':{'a':5,'c':2},'allocation':'a5+c2','talent_family':'feral','combat_profile':'cat','talent_added':'c:2'},
    ])
    frontier={'class':'druid','levels':[{'level':22,'candidates':[route]}]}
    out=analyze_constraint(frontier,22,{
        'at_level':20,
        'at_level_talent_allocation_exact':{'a':5},
    })
    nxt=out['continuation']['next_meaningful_decision']
    assert nxt['level']==21
    assert nxt['changes']['talent_added']=='c:1'


def test_i18_exact_allocation_fails_closed_when_corridor_not_preserved():
    route = _candidate(100.0, name='route', mph=200, steps=[
        {'level':20,'talent_ranks':{'a':5,'b':1},'allocation':'a5+b1'},
        {'level':22,'talent_ranks':{'a':5,'b':3},'allocation':'end'},
    ])
    frontier={'class':'druid','levels':[{'level':22,'candidates':[route]}]}
    out=analyze_constraint(frontier,22,{
        'at_level':20,
        'at_level_talent_allocation_exact':{'a':5},
    })
    assert out['status']=='not_preserved_requires_constrained_rerun'
    assert 'path' not in out


def test_i18_dual_spec_continuation_uses_level_boundary_switches_only():
    from src.v2.constrained_routes import dual_spec_continuation
    dual={
        'status':'available','unlock_level':40,'switch_model':'level_boundaries_only',
        'switches':[{'level':42,'to_route':'fire','to_slot':'B'},{'level':50,'to_route':'frost','to_slot':'A'}],
        'switch_recommendation':'L42: switch to fire (B); L50: switch to frost (A)',
        'pair':{'A':{'route':'frost'},'B':{'route':'fire'}},
    }
    out=dual_spec_continuation(dual,at_level=40,target_level=45)
    assert out['switch_model']=='level_boundaries_only'
    assert out['next_switch']['level']==42
    assert out['next_switch']['to_route']=='fire'


def test_i18_dual_spec_continuation_omits_nonavailable_plan():
    from src.v2.constrained_routes import dual_spec_continuation
    assert dual_spec_continuation({'status':'unlock_after_target'},at_level=20,target_level=30) is None

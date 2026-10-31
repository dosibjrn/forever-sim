import pytest
from src.v2.source_joint_feedback import trace_joint_feedback

def row(g,t,v,p):
    return {'gear_id':g,'talent_id':t,'score_s_per_mob':v,'best_policy':{'policy_id':p,'branch':'caster'}}

def test_feedback_improves_both_axes_and_reoptimizes_policy():
    rows=[row('a','x',12,'p0'),row('b','x',10,'p1'),row('a','y',11,'p2'),row('b','y',8,'p3')]
    result=trace_joint_feedback(rows,start_gear_id='a',start_talent_id='x')
    assert result['converged'] and result['winner']['score_s_per_mob']==8
    assert [r['axis'] for r in result['trace']]==['initial','gear','talents']
    assert [r['policy_id'] for r in result['trace']]==['p0','p1','p3']

def test_coordinate_stable_not_global_optimal():
    rows=[row('a','x',5,'p'),row('b','x',6,'p'),row('a','y',6,'p'),row('b','y',1,'p')]
    result=trace_joint_feedback(rows,start_gear_id='a',start_talent_id='x')
    assert result['winner']['score_s_per_mob']==5
    assert result['global_grid_winner']['score_s_per_mob']==1
    assert not result['global_optimum_proven']

def test_incomplete_grid_and_malformed_fail_closed():
    with pytest.raises(ValueError,match='Cartesian'):
        trace_joint_feedback([row('a','x',3,'p'),row('b','x',4,'p'),row('a','y',5,'p')])
    with pytest.raises(ValueError,match='duplicate'):
        trace_joint_feedback([row('a','x',2,'p'),row('a','x',2,'p')])
    with pytest.raises(ValueError,match='sweep'):
        trace_joint_feedback([row('a','x',3,'p')],max_sweeps=0)

"""Gate-level regression: 100-mob finalists should not be clones or hide deaths."""
from src.v2.source_bounded_joint_frontier import _select_screen_finalists, independently_compare_shortlist
from src.v2.source_persistent_joint_finalists import _evaluate_concurrent_source_packs


def test_finalists_diversify_talent_policy_gear_before_recovery_clones():
    rows=[]
    for name,score,rec in [('a',1.,'always'),('a',1.,'threshold'),('b',1.1,'always'),('c',1.2,'always'),('d',1.3,'always')]:
        x={'allocation':{name:1},'gear_move':'gear1','policy':'p','policy_signature':'sig',
           'recovery':rec,'screen_s_per_mob':score, 'is_control':False}
        rows.append((x,None,None))
    chosen=_select_screen_finalists(rows,4)
    assert [next(iter(x[0]['allocation'])) for x in chosen]==['a','b','c','d']


def test_actor_death_is_normal_invalid_horizon_not_opaque_exception(monkeypatch):
    import src.game.multi_pull as mp
    class Dummy:
        ir=type("IR",(),{"provenance":{}})()
        policy=None
        opening=()
    monkeypatch.setattr(mp,'evaluate_repeated_pulls',lambda **kwargs:(_ for _ in ()).throw(ValueError('pull 3 failed: actor_died')))
    result=_evaluate_concurrent_source_packs(Dummy(),level=30,mobs=100,pack_size=2,
        max_total_events=250000,max_cpu_s=10.,max_wall_s=10.,recovery_policy=None)
    assert result['status']=='BLOCKED_ACTOR_DIED'
    assert 'pull 3' in result['reason']


def test_independent_comparison_preserves_survival_failure_reason():
    rows=[{'id':'good','screen_s_per_mob':1.}, {'id':'bad','screen_s_per_mob':1.1}]
    def replay(row):
        if row['id']=='good':return {'status':'COMPLETE','count':100,'events':1000,'mean_s_per_mob':10.}
        return {'status':'BLOCKED_ACTOR_DIED','count':0,'events':0,'reason':'pull 3 failed: actor_died'}
    result=independently_compare_shortlist(rows,replay)
    assert result['status']=='INCOMPLETE_FULL_HORIZON_EVIDENCE'
    assert result['rows'][1]['reason']=='pull 3 failed: actor_died'

"""WF367: source-legal gear proposals are real, recovery-aware, paid trials."""
from __future__ import annotations
from types import SimpleNamespace

from src.v2 import source_persistent_gear_neighborhood as neighborhood


def test_role_diversity_and_recovery_paid_100mob(monkeypatch):
    seen=[]
    def roles(class_key):
        assert class_key=='druid'
        return ('balance','feral','bear')
    def select(**kw):
        assert kw['exclude_unknown_item_effects'] is True
        seen.append(kw['role'])
        iid=100+{'balance':0,'feral':10,'bear':20}[kw['role']]
        iid+=int(kw['stat_weights']['agility']*100)
        return SimpleNamespace(as_dict=lambda: {
            'role':kw['role'], 'selection_weights':kw['stat_weights'],
            'slots':{'weapon':{'item_id':iid}},'aggregate_stats':{'agility':1.}})
    def prepare(**kw):
        assert kw['strict_l2_item_effects']
        assert kw['source_ir']=='source-ir'
        return kw['stage']
    def evaluate(stage,**kw):
        assert kw['recovery_policy']=='conditional'
        assert kw['mobs'] in (2,100)
        iid=stage['gear_policy_result']['winner']['gear']['slots']['weapon']['item_id']
        return {'status':'COMPLETE','mean_s_per_mob':30-iid*.01,'events':kw['mobs']}
    monkeypatch.setattr(neighborhood,'available_gear_roles',roles)
    monkeypatch.setattr(neighborhood,'select_named_gear',select)
    monkeypatch.setattr('src.v2.source_persistent_joint_finalists.prepare_candidate',prepare)
    monkeypatch.setattr('src.v2.source_persistent_joint_finalists.evaluate_persistent_candidate',evaluate)
    stage={'allocation':{},'score_s_per_mob':20.,'gear_policy_result':{'winner':{
        'gear':{'role':'balance','selection_weights':{'agility':1.},
                'slots':{'weapon':{'item_id':1}}},'winner':{'fallback':'claw','prefix':[]}}}}
    r=neighborhood.refine_source_gear_persistent(class_key='druid',level=30,
        stage=stage,screen_mobs=2,max_proposals=6,max_finalists=2,source_ir='source-ir',
        strict_l2_item_effects=True,recovery_policy='conditional',max_total_wall_s=5.)
    assert seen[:3]==['balance','feral','bear']
    assert r['unique_legal_gear_sets']==6
    assert r['screen_completed']==6 and r['finalists_completed']==2
    assert r['attempts_paid']==8 and r['events_paid']==6*2+2*100
    assert r['winner']['persistent']['status']=='COMPLETE'


def test_hard_time_cap_does_not_promote_unmeasured(monkeypatch):
    monkeypatch.setattr(neighborhood,'available_gear_roles',lambda _:('balance',))
    stage={'gear_policy_result':{'winner':{'gear':{
        'role':'balance','selection_weights':{'agility':1.},
        'slots':{'weapon':{'item_id':1}}}}}}
    r=neighborhood.refine_source_gear_persistent(class_key='druid',level=30,
        stage=stage,max_total_wall_s=0.001)
    assert r['status']=='BLOCKED_NO_GEAR_FINALIST'
    assert r['attempts_paid']==0 and r['unique_legal_gear_sets']==0

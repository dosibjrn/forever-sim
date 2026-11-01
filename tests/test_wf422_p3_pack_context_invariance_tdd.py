"""WF422: a P3 stat derivative must never compare different 2D encounters.

The same source candidate is evaluated through the existing paid CombatRuntime.
The pure evaluator test deliberately creates a tempting cross-context false win.
"""
from dataclasses import dataclass
from types import SimpleNamespace
import pytest

from src.v2 import source_reoptimized_stat_sensitivity as sensitivity


@dataclass(frozen=True)
class Candidate:
    ir: object


def _synthetic_probe(monkeypatch, *, fail_after_pack2=False):
    original=Candidate(ir='before')
    monkeypatch.setattr(sensitivity,'_source_stat_perturbation',
                        lambda ir,**kwargs: ('after',None))
    calls=[]
    def paid_evaluate(trial,*,level,mobs,recovery_policy,pack_size,max_wall_s,max_total_events):
        calls.append((trial.ir,pack_size))
        if fail_after_pack2 and trial.ir=='after' and pack_size==2:
            return {'status':'DEAD','count':55,'events':345,'mean_s_per_mob':None}
        score={('before',1):10.,('after',1):10.,('before',2):20.,('after',2):5.}[(trial.ir,pack_size)]
        return {'status':'COMPLETE','count':100,'mean_s_per_mob':score,
                'events':200,'recovery_s':0.,'between_pull_full_recoveries':0}
    monkeypatch.setattr(sensitivity,'evaluate_persistent_candidate',paid_evaluate)
    result=sensitivity.reoptimized_stat_sensitivity(candidate=original,stat='spell_power',delta=10.,
          level=20,recovery_policies=(None,),pack_sizes=(1,2),mobs=100)
    return result,calls


def test_different_encounters_cannot_be_optimized_against_each_other(monkeypatch):
    result,calls=_synthetic_probe(monkeypatch)
    assert result['status']=='COMPLETE_CONTEXTUAL_100MOB_STAT_PROBE'
    assert result['weight_s_saved_per_mob_per_unit'] is None
    assert result['best'] is None
    assert result['by_pack_size'][1]['weight_s_saved_per_mob_per_unit']==0.
    assert result['by_pack_size'][2]['weight_s_saved_per_mob_per_unit']==pytest.approx(1.5)
    assert result['by_pack_size'][1]['best']['before']['pack_size']==1
    assert result['by_pack_size'][1]['best']['after']['pack_size']==1
    assert result['by_pack_size'][2]['best']['before']['pack_size']==2
    assert result['by_pack_size'][2]['best']['after']['pack_size']==2
    assert len(calls)==4


def test_incomplete_context_is_blocked_without_poisoning_other_context(monkeypatch):
    result,_=_synthetic_probe(monkeypatch,fail_after_pack2=True)
    assert result['status']=='BLOCKED_CONTEXTUAL_INCOMPLETE_100MOB'
    assert result['weight_s_saved_per_mob_per_unit'] is None
    assert result['by_pack_size'][1]['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['by_pack_size'][2]['status']=='BLOCKED_NO_COMPLETE_HUNDRED_MOB_FRONTIER'
    assert result['by_pack_size'][2]['weight_s_saved_per_mob_per_unit'] is None


def test_single_context_keeps_existing_p3_contract(monkeypatch):
    candidate=Candidate(ir='before')
    monkeypatch.setattr(sensitivity,'_source_stat_perturbation',lambda ir,**kw:('after',None))
    monkeypatch.setattr(sensitivity,'evaluate_persistent_candidate',lambda trial,*,level,mobs,
        recovery_policy,pack_size,max_wall_s,max_total_events:{'status':'COMPLETE','count':100,
        'mean_s_per_mob':10. if trial.ir=='before' else 9.,'events':100})
    result=sensitivity.reoptimized_stat_sensitivity(candidate=candidate,stat='spell_power',delta=10.,
        level=20,recovery_policies=(None,),pack_sizes=(2,),mobs=100)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['weight_s_saved_per_mob_per_unit']==pytest.approx(.1)
    assert result['best']['before']['pack_size']==result['best']['after']['pack_size']==2


def test_real_wf420_source_winner_has_different_one_and_two_mob_dodge_sensitivities():
    from tools.wf420_druid20_independent_full_replay import rebuild_result_winner
    _,candidate,recovery=rebuild_result_winner()
    result=sensitivity.reoptimized_stat_sensitivity(candidate=candidate,stat='dodge',delta=12.,
        level=20,recovery_policies=(recovery,),pack_sizes=(1,2),mobs=100,max_wall_s_per_eval=18.)
    assert result['status']=='COMPLETE_CONTEXTUAL_100MOB_STAT_PROBE'
    assert result['weight_s_saved_per_mob_per_unit'] is None
    assert result['by_pack_size'][1]['weight_s_saved_per_mob_per_unit']==0.
    assert result['by_pack_size'][2]['weight_s_saved_per_mob_per_unit']>0.
    assert len(result['rows'])==4
    assert all(row['status']=='COMPLETE' and row['mob_completed']==100 for row in result['rows'])

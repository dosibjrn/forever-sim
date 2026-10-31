"""WF359: fast source-legal all-item P3 ranking and paid contextual rebase."""
import json
from pathlib import Path

import pytest

from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.game.data.forever.source_checkpoint_p3_empirical_weights import (
    fit_swap_weights,rank_all_legal_items_with_proxy)
from src.game.recovery_between_pulls import BetweenPullPolicy
from tools import wf359_druid_l30_p3_rebase as wf359

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def evidence():
    return json.loads((ROOT/'evidence/wf359/WF359_L30_P3_REBASED_TOP5.json').read_text())

@pytest.fixture(scope='module')
def stage():
    return json.loads(wf359.STAGE.read_text())


def test_exact_checkpoint_legal_denominators_and_no_extra_gate(evidence):
    assert evidence['checkpoint']=='druid:L30:unrestricted'
    assert (evidence['source_legal_item_count'],evidence['source_l0_assessed'])==(1974,1974)
    assert evidence['source_legal_slot_count']==18
    assert evidence['p3']=='PASS'
    assert evidence['p4']==evidence['p5']==evidence['p6']=='NOT_RUN'
    assert evidence['accepted_checkpoints']=='1/148'


def test_paid_replay_not_silent_zero_for_unknown_effects(evidence):
    assert evidence['source_unknown_effect_items']==73
    assert evidence['direct_paid_complete']>=70
    assert evidence['direct_status_counts']['L0_ONLY_UNRESOLVED_EFFECT']>=1
    assert evidence['direct_events']>700_000
    assert evidence['baseline_100mob']['status']=='COMPLETE'
    assert abs(evidence['baseline_100mob']['mean_s_per_mob']-16.287595825231314)<1e-7
    for section in evidence['slots'].values():
        assert section['direct_complete']>=1
        assert section['l0_contextual_top5']
        for row in section['l0_contextual_top5']:
            assert 'unresolved_source_effects' in row
            assert 'unidentified_stats' in row


def test_diversified_proposals_include_non_proxy_source_extrema(stage):
    inv=checkpoint_item_l0(class_key='druid',level=30)
    prior=json.loads(wf359.PRIOR.read_text())
    active=json.loads(wf359.ACTIVE.read_text())
    rows,counts,unknown,paired=wf359.candidate_jobs(stage,inv,prior,active,max_per_slot=5)
    assert len(counts)==18 and all(counts.values())
    assert paired>0
    back=[r for r in rows if r['slot']=='back']
    assert any(r['reason']=='equipped_context_anchor' for r in back)
    assert any(r['reason'].startswith('source_stat_axis_max_') for r in back)
    assert any(r['reason'].startswith('active_paid_') for r in back)
    assert len({(r['slot'],r['item_id']) for r in rows})==len(rows)


def test_full_audit_of_all_83_contextual_top5_packages(stage,evidence):
    # The optimized O(N) legal filter is followed by full named-gear audits
    # for every candidate actually promoted to the slot Top5.
    total=0
    for slot,section in evidence['slots'].items():
        for row in section['l0_contextual_top5']:
            assert row['source_url'].startswith('https://www.wowhead.com/forever/item=')
            result=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=row['swaps'])
            assert result['gear_policy_result']['winner']['gear']['level']==30
            total+=1
    assert total==83


def test_context_fingerprint_binds_recovery_and_runtime(stage,monkeypatch):
    db=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
    first,details=wf359.scenario_context(stage=stage,db=db)
    assert 'runtime_files_sha256' in details
    monkeypatch.setattr(wf359,'POLICY',BetweenPullPolicy(.5,.2,
        exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'))
    second,_=wf359.scenario_context(stage=stage,db=db)
    assert first!=second


def test_empirical_proxy_is_contextual_and_discloses_error(evidence):
    model=evidence['empirical_context_weights']
    assert model['status']=='MEASURED_100MOB_REGULARIZED_NONLINEAR_UNCERTAINTY'
    assert model['cv_mae_s_per_mob']>0
    assert model['n']>=60
    assert any(row['unresolved_source_effects'] for section in evidence['slots'].values()
               for row in section['l0_contextual_top5'])

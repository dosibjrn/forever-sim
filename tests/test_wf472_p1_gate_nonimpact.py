"""P1 scenario scope: explicit, per-scenario waiver, not a pretend executor PASS."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as N
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from wf_gate_p1_live import (
    _load_p1_scenario_nonimpact, audit_inventory, run_live,
    P1_DEFAULT_SCENARIO, P1SetupError,
)


def _row(sid, name, effect='Stuns the enemy for 30 seconds'):
    return {'spell_id':sid, 'name':name, 'level_hint':20, 'rank_hint':1,
            'raw_listview_json':json.dumps({'envChange':{'after':{'text':effect}}})}


def _audit(rows, nonimpact):
    ir=N(actor=N(id='player'), actions=(), modes=(), resources=())
    return audit_inventory(rows, ir, parser=lambda a:set(),
            source_classifier=lambda row,raw:{'role':'ABILITY'},
            policy_builder=lambda ir,rules:None,
            scratch_builder=lambda ir,max_candidates:[],
            executor=lambda ir,action:None, effect_checker=lambda effect:'damage',
            scenario_nonimpact=nonimpact,scenario_id=P1_DEFAULT_SCENARIO)


def test_explicit_nonimpact_is_neither_an_executor_pass_nor_unreported():
    skipped={'name':'Hibernate','reason':'Not relevant to current optimized target scenario',
             'review_if':'Target enemy categories change'}
    r=_audit([_row(2637,'Hibernate'), _row(5215,'Prowl','Grants stealth')],{2637:skipped})
    assert r['status']=='FAIL'
    assert r['does_not_affect_sim_count']==1
    assert r['does_not_affect_sim'][0]['role']=='DOES_NOT_AFFECT_SIM'
    assert r['production_runtime_exercises']==0
    assert r['checked_source_abilities']==1
    assert [(p['code'],p['ability'].split(':')[0]) for p in r['problems'] if p['code']=='MISSING_GAME_IR_ACTION']==[('MISSING_GAME_IR_ACTION','5215')]


def test_no_record_means_hibernate_remains_a_cc_requirement():
    r=_audit([_row(2637,'Hibernate')],{})
    assert r['does_not_affect_sim_count']==0
    assert r['status']=='FAIL'
    assert 'MISSING_GAME_IR_ACTION' in {p['code'] for p in r['problems']}


def test_misbound_spell_id_name_never_suppresses_missing_action():
    r=_audit([_row(2637,'Completely Different Spell')],{
        2637:{'name':'Hibernate','reason':'Not relevant to this simulated objective',
              'review_if':'Different scenario'}})
    assert r['status']=='FAIL'
    assert r['does_not_affect_sim_count']==0
    assert {'P1_NONIMPACT_ID_NAME_MISMATCH','MISSING_GAME_IR_ACTION'} <= {p['code'] for p in r['problems']}


def test_loader_only_matches_class_checkpoint_and_declared_scenario():
    actual=_load_p1_scenario_nonimpact(ROOT,'druid',20,P1_DEFAULT_SCENARIO)
    assert set(actual)=={2637,18960}
    assert _load_p1_scenario_nonimpact(ROOT,'mage',20,P1_DEFAULT_SCENARIO)=={}
    assert _load_p1_scenario_nonimpact(ROOT,'druid',9,P1_DEFAULT_SCENARIO)=={}
    with pytest.raises(P1SetupError,match='P1_SCENARIO_UNDECLARED'):
        _load_p1_scenario_nonimpact(ROOT,'druid',20,'another_target_cohort')


def test_full_live_gate_reports_green_with_nonimpact_separate(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-17')
    report=run_live(ROOT,'druid',20)
    assert report['status']=='PASS'
    assert report['problem_count']==0
    assert not report['problems']
    assert report['does_not_affect_sim_count']==2
    assert {x['source_spell_id'] for x in report['does_not_affect_sim']}=={2637,18960}
    assert report['production_runtime_exercises']==18

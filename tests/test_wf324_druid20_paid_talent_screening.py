"""WF324 Druid L20: real L2 talent-scouting is paid, legal and never DONE.

Only tests an improved existing joint controller; does not certify partial
web-text source observations or historical beta build as current server truth.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.talents import validate_talent_selection
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf321_ingest_control_observations import ingest as ingest_control
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS

OBS_RANKS=Path('evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
OBS_CONTROL=Path('evidence/wf321/druid_l20_control_observations.json')


@pytest.fixture(scope='module')
def staged_druid20(tmp_path_factory):
    path=tmp_path_factory.mktemp('wf324-source')/'only-druid20.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as original, sqlite3.connect(path) as dst:
        original.backup(dst)
    assert ingest_observations(path,OBS_RANKS)['count']==9
    ingest_control(path,OBS_CONTROL)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return path


def _run(staged_druid20,monkeypatch,*,budget,events,screen):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    with ability_source_scope(staged_druid20):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=staged_druid20)
        kwargs={**JOINT_ARGS,'max_evaluations':budget,'max_event_transitions':events,
            'evaluations_per_talent':38,'talent_screening_attempts':screen}
        result=run_source_budgeted_joint_talents(**kwargs,ir_slice=ir)
        return ir,result


def test_paid_full_l2_screening_expands_independent_druid20_talent_coverage(staged_druid20,monkeypatch):
    ir,result=_run(staged_druid20,monkeypatch,budget=160,events=24000,screen=35)
    assert result['attempted']==result['evaluated']+result['blocked']<=160
    assert result['event_transitions']<=24000
    assert result['talent_screening_attempts']==35
    assert result['distinct_talent_allocations_paid_L2']>=36
    assert result['talent_states_evaluated']>=3
    assert result['talent_screening_cpu_ns']>0
    assert result['winner']['score_s_per_mob']<22.68
    assert result['complete_search'] is False
    # Every recorded scout allocation passes the SAME sourced talent legality.
    for row in result['talent_screening_evidence']:
        validate_talent_selection(ir,row['allocation'],level=20)
        assert row['status'] in ('FULL_L2_FIXED_POLICY','BLOCKED_L2')
        assert row['event_transitions']>=0
    assert all(x['scope']=='screening_only_not_joint_winner'
               for x in result['fixed_policy_challengers']
               if x.get('scope')=='screening_only_not_joint_winner')


def test_zero_screening_preserves_existing_checkpoint_path(staged_druid20,monkeypatch):
    ir,result=_run(staged_druid20,monkeypatch,budget=135,events=16000,screen=0)
    assert result['talent_screening_attempts']==0
    assert not result['talent_screening_evidence']
    assert 3 <= result['talent_states_evaluated'] <= result['attempted']
    assert result['attempted']==135
    assert result['winner']['score_s_per_mob']==pytest.approx(22.6875534645,abs=1e-6)


def test_tiny_hard_event_budget_still_limits_screen_and_full_search(staged_druid20,monkeypatch):
    ir,result=_run(staged_druid20,monkeypatch,budget=110,events=5,screen=25)
    assert result['attempted']<=110
    assert result['attempted']==result['evaluated']+result['blocked']
    assert result['event_transitions']<=5
    assert result['talent_screening_attempts']==0
    assert result['complete_search'] is False


def test_invalid_screening_budget_fail_closed():
    for value in (-1, 135, 999, 1.2, '40'):
        with pytest.raises(ValueError,match='talent_screening_attempts'):
            run_source_budgeted_joint_talents(class_key='druid',level=20,
                max_evaluations=135,talent_screening_attempts=value)

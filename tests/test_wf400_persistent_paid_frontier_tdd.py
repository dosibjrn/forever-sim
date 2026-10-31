"""TDD: expensive 30/300s four-axis evidence must survive an external abort."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier
from src.v2.source_joint_progress import load_verified_joint_progress

ROOT=Path(__file__).resolve().parents[1]


def _inputs():
    ir=build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return ir,stage


def _search(ir,stage,path,**kwargs):
    opts=dict(max_talents=2,max_gear_moves=0,max_policies=3,
        max_recovery_policies=2,max_paid_builds=5,max_cpu_s=15.,
        per_candidate_wall_s=3.,screen_then_finalists=False,pack_size=2)
    opts.update(kwargs)
    return search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,progress_path=path,**opts)


def test_external_abort_preserves_independently_verifiable_paid_100mob_result(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'journal.json'
    calls=[]
    def paid(candidate,*,level,mobs,recovery_policy=None,timeout_s=8.,pack_size=1):
        calls.append(mobs)
        if len(calls)==3:
            raise KeyboardInterrupt('simulated external abort')
        return dict(status='COMPLETE',mean_s_per_mob=20.+mobs/100.,
                    mob_completed=mobs,events=mobs*5,elapsed_cpu_s=.02,
                    outer_wall_s=.02)
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            _search(ir,stage,path)
    record=load_verified_joint_progress(path)
    assert record['status']=='IN_PROGRESS_NOT_CERTIFIED'
    assert record['complete_100mob_candidates']==1
    assert record['winner']['mobs']==100
    assert record['winner']['seconds_per_mob']==21.
    assert record['paid_candidates']==1
    assert record['eligible_for_checkpoint_acceptance'] is False
    assert record['source_legal_gear_universe_verified'] is False
    assert calls[:2]==[4,100]


def test_final_journal_is_not_checkpoint_acceptance_and_has_all_rows(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'journal.json'
    def paid(candidate,*,level,mobs,recovery_policy=None,timeout_s=8.,pack_size=1):
        return dict(status='COMPLETE',mean_s_per_mob=30.+mobs/100.,
                    mob_completed=mobs,events=mobs*7,elapsed_cpu_s=.01,
                    outer_wall_s=.01)
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        result=_search(ir,stage,path)
    record=load_verified_joint_progress(path)
    assert record['status']=='FINISHED_NOT_CERTIFIED'
    assert record['paid_candidates']==result['paid_candidates']==5
    assert record['complete_100mob_candidates']==result['complete_100mob_candidates']==5
    assert record['winner']['seconds_per_mob']==result['winner']['seconds_per_mob']
    assert record['eligible_for_checkpoint_acceptance'] is False


def test_journal_tampering_and_unintended_overwrite_are_rejected(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'journal.json'
    path.write_text('{"other":true}')
    with pytest.raises(FileExistsError, match='REFUSE_OVERWRITE'):
        _search(ir,stage,path)
    with pytest.raises(ValueError, match='SOURCE_JOINT_PROGRESS_INTEGRITY'):
        load_verified_joint_progress(path)


def test_two_stage_interrupt_during_finalists_keeps_completed_100mob(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'two_stage.json'
    calls=[]
    def paid(candidate,*,level,mobs,recovery_policy=None,timeout_s=8.,pack_size=1):
        calls.append(mobs)
        if mobs==100 and calls.count(100)==2:
            raise KeyboardInterrupt('next finalist aborted')
        return dict(status='COMPLETE',mean_s_per_mob=25.+mobs/100.,
                    mob_completed=mobs,events=mobs*5,elapsed_cpu_s=.02,
                    outer_wall_s=.02)
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            _search(ir,stage,path,screen_then_finalists=True,max_finalists=2)
    record=load_verified_joint_progress(path)
    assert record['status']=='IN_PROGRESS_NOT_CERTIFIED'
    assert record['phase']=='FULL_FINALISTS'
    assert record['paid_candidates']==5
    assert record['complete_100mob_candidates']==1
    assert record['winner']['mobs']==100
    assert record['winner']['seconds_per_mob']==26.
    assert all(row.get('status')!='COMPLETE' or row.get('mobs')==100 for row in record['rows'])


def test_source_context_fingerprint_changes_when_same_stage_has_different_gear():
    from copy import deepcopy
    from src.v2.source_joint_progress import search_context_sha256
    ir,stage=_inputs()
    changed=deepcopy(stage)
    changed['gear_policy_result']['winner']['gear']['slots']['back']=999999
    opts=dict(pack_size=2)
    key=search_context_sha256(class_key='druid',level=30,source_ir=ir,seed_stage=stage,options=opts)
    other=search_context_sha256(class_key='druid',level=30,source_ir=ir,seed_stage=changed,options=opts)
    assert key!=other


def test_three_stage_abort_keeps_qualification_but_not_a_false_full_winner(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'qualifying.json'
    calls=[]
    def paid(candidate,*,level,mobs,recovery_policy=None,timeout_s=8.,pack_size=1):
        calls.append(mobs)
        if mobs==20 and calls.count(20)==2:
            raise KeyboardInterrupt('qualifier worker forcibly aborted')
        return dict(status='COMPLETE',mean_s_per_mob=20.+mobs/100.,
                    mob_completed=mobs,events=mobs*5,elapsed_cpu_s=.01,
                    outer_wall_s=.01)
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        with pytest.raises(KeyboardInterrupt):
            _search(ir,stage,path,screen_then_finalists=True,
                qualification_mobs=20,max_qualifiers=3,max_finalists=2)
    journal=load_verified_joint_progress(path)
    assert journal['phase']=='SURVIVAL_QUALIFICATION'
    assert journal['paid_candidates']==5
    assert journal['complete_100mob_candidates']==0
    assert journal['winner'] is None
    assert sum(row.get('qualification_status')=='COMPLETE' for row in journal['rows'])==1
    assert calls.count(100)==0


def test_three_stage_finished_journal_qualifies_and_full_scores_separately(tmp_path):
    ir,stage=_inputs()
    path=tmp_path/'qualified.json'
    def paid(candidate,*,level,mobs,recovery_policy=None,timeout_s=8.,pack_size=1):
        return dict(status='COMPLETE',mean_s_per_mob=20.+mobs/100.,
                    mob_completed=mobs,events=mobs*7,elapsed_cpu_s=.01,
                    outer_wall_s=.01)
    with patch('src.v2.source_bounded_joint_frontier.isolated_joint_evaluation',side_effect=paid):
        result=_search(ir,stage,path,screen_then_finalists=True,
            qualification_mobs=20,max_qualifiers=3,max_finalists=2)
    journal=load_verified_joint_progress(path)
    assert journal['status']=='FINISHED_NOT_CERTIFIED'
    assert result['qualification_evaluated_candidates']==3
    assert result['qualification_complete_candidates']==3
    assert result['complete_100mob_candidates']==2
    assert journal['complete_100mob_candidates']==2
    assert journal['winner']['mobs']==100
    assert sum(row.get('qualification_status')=='COMPLETE' for row in journal['rows'])==3
    assert result['screen_phase_wall_s']+result['qualification_phase_wall_s']+result['finalist_phase_wall_s'] == pytest.approx(result['wall_s'], abs=.05)


def test_item_catalogue_byte_change_invalidates_progress_context(tmp_path,monkeypatch):
    from src.v2.source_joint_progress import search_context_sha256
    ir,stage=_inputs()
    db=tmp_path/'catalogue.sqlite'
    db.write_bytes(b'catalogue version A')
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(db))
    a=search_context_sha256(class_key='druid',level=30,source_ir=ir,seed_stage=stage,options={})
    db.write_bytes(b'catalogue version B')
    b=search_context_sha256(class_key='druid',level=30,source_ir=ir,seed_stage=stage,options={})
    assert a!=b

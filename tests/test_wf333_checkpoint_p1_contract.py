"""Generic P1 requires evidence + an actual context-ranked L0 candidate."""
from dataclasses import replace
import json
import sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_p1_acceptance import (
    CheckpointP1, evaluate_p1, l0_paid_action_priority)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations as ingest_web
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.v2.source_budgeted_prefix import source_prefix_envelope, run_source_budgeted_prefix

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def checkpoint_stage(tmp_path_factory):
    path=tmp_path_factory.mktemp('wf333')/'source.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(path) as dst:
        src.backup(dst)
    ingest_beta(path,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
    ingest_control(path,ROOT/'evidence/wf321/druid_l20_control_observations.json')
    ingest_maul(path,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
    ingest_web(path,ROOT/'evidence/wf331/druid20_source_web_index_observations.json')
    return path

@pytest.fixture(scope='module')
def state(checkpoint_stage):
    from os import environ
    environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    with ability_source_scope(checkpoint_stage):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=checkpoint_stage)
        frontier=action_frontier(ir,class_key='druid',level=20,db_path=checkpoint_stage)
    return ir,frontier

def test_p1_is_real_legal_universe_not_semantic_52_of_52(checkpoint_stage,state):
    ir,frontier=state
    report=evaluate_p1(frontier,checkpoint_stage,CheckpointP1('druid',20),ir=ir)
    # Prowl is now a sourced executable legal action as well as reactive CC.
    assert report['legal']==27
    assert report['scored_legal_or_conditional']==26
    assert report['unresolved'] == 30
    # The legacy numeric L0 proxy cannot price stealth detection as DPS;
    # P1 availability itself requires real IR/runtime and candidate admission,
    # not an invented numerical stealth benefit.
    assert report['legal_without_rankable_l0']==[5215]
    assert not report['PASS1']
    assert 'UNRESOLVED_SOURCE_LEGALITY' in report['blockers']
    by_id={r['spell_id']:r for r in report['records']}
    assert by_id[6807]['l0_utility']['value_domains']['queued_swing_bonus_damage']==18.0
    assert by_id[5211]['l0_utility']['value_domains']['target_control_seconds']==2.0
    assert by_id[768]['l0_utility']['value_domains']['mode_reachable_damage_filler_count']>0
    assert by_id[770]['l0_utility']['value_domains']['target_debuff_magnitude']==175.0
    assert by_id[99]['l0_utility']['value_domains']['enemy_attack_power_reduction']==56.0
    assert by_id[410021]['legality_reason']=='ENGRAVING_DISABLED'
    assert by_id[417157]['status']=='ILLEGAL'
    assert by_id[774]['status']=='UNRESOLVED'  # low level does not prove learned

def test_p1_priorities_reorder_actual_source_search_without_losing_actions(checkpoint_stage,state):
    ir,frontier=state
    report=evaluate_p1(frontier,checkpoint_stage,CheckpointP1('druid',20),ir=ir)
    priorities=l0_paid_action_priority(report)
    assert priorities
    before=source_prefix_envelope(ir,level=20)
    after=source_prefix_envelope(ir,level=20,l0_action_priority=priorities)
    assert after['l0_priored_candidate_order_applied']
    assert set(before['actions'])==set(after['actions'])
    assert {x['entry']:set(x['actions']) for x in before['mode_paths']} == {x['entry']:set(x['actions']) for x in after['mode_paths']}
    assert set(priorities).issubset(set(before['actions']) | {a for x in before['mode_paths'] for a in (*x['actions'],x['entry'])})


def test_p1_mismatched_checkpoint_and_rune_mode_rejected(checkpoint_stage,state):
    ir,frontier=state
    with pytest.raises(ValueError,match='P1_CHECKPOINT_FRONTIER_MISMATCH'):
        evaluate_p1(frontier,checkpoint_stage,CheckpointP1('druid',30),ir=ir)
    with pytest.raises(ValueError,match='P1_RUNE_CONFIGURATION_MISMATCH'):
        evaluate_p1(frontier,checkpoint_stage,CheckpointP1('druid',20,use_runes=True),ir=ir)
    with pytest.raises(ValueError,match='INVALID_CHECKPOINT'):
        CheckpointP1('druid',61)


def test_p1_fail_closed_for_unapplied_profile(checkpoint_stage,state):
    ir,frontier=state
    modified={**frontier,'checkpoint':{**frontier['checkpoint'],'profile':'feral'},'profile_constraint_applied':False}
    result=evaluate_p1(modified,checkpoint_stage,CheckpointP1('druid',20,profile='feral'),ir=ir)
    assert not result['PASS1']
    assert 'PROFILE_CONSTRAINT_UNPROVEN' in result['blockers']


def test_p1_semantic_only_is_not_numeric_score(checkpoint_stage,state):
    ir,frontier=state
    payload=json.loads(json.dumps(frontier))
    row=next(r for r in payload['records'] if r.get('spell_id')==99)
    row['source_text_context_evidence']['numeric_context_features']={}
    row['ir_proxies']=[]
    result=evaluate_p1(payload,checkpoint_stage,CheckpointP1('druid',20),ir=ir)
    assert 99 in result['legal_without_rankable_l0']
    assert not result['PASS1']


def test_p1_empty_legal_universe_not_auto_pass(checkpoint_stage,state):
    ir,frontier=state
    payload=json.loads(json.dumps(frontier))
    payload['records']=[]
    payload['excluded_above_level']=[]
    # An empty index would not be proof that no spells exist. The inventory
    # generator normally refuses an absent index, and the gate must too.
    with pytest.raises(ValueError,match='EMPTY_SOURCE_CANDIDATE_SET'):
        evaluate_p1(payload,checkpoint_stage,CheckpointP1('druid',20),ir=ir)


def test_p1_priorities_enter_paid_runtime_not_only_reporting(checkpoint_stage,state):
    ir,frontier=state
    priority=l0_paid_action_priority(evaluate_p1(frontier,checkpoint_stage,CheckpointP1('druid',20),ir=ir))
    with ability_source_scope(checkpoint_stage):
        result=run_source_budgeted_prefix(class_key='druid',level=20,max_evaluations=8,
                                           ir_slice=ir,l0_action_priority=priority)
    assert result['envelope']['l0_priored_candidate_order_applied']
    assert result['attempted']>0
    assert result['attempted']<=8
    # Deliberately do not use its single-mob diagnostic score as checkpoint evidence.

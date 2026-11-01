"""WF322: newer public beta-client values in staged SQLite, never canonical.

Two independent public web-text sources are not SHA-verified spell-detail
HTML, so no test here claims the Druid L20 checkpoint is accepted.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_observed_rank_parity import (
    ingest_observations, ExternalRankObservationError)
from src.game.data.forever.source_index_rank_parity import indexed_rank_fact
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_stateful_budgeted import _make_policy
from tools.wf319_druid_l20_current_source import _build_at
from tools.wf297_druid_l20_checkpoint import run as joint_run

OBS=Path(__file__).resolve().parents[1]/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json'


@pytest.fixture
def stage(tmp_path):
    p=tmp_path/'isolated_observed.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as src,sqlite3.connect(p) as dst:
        src.backup(dst)
    result=ingest_observations(p,OBS)
    assert result['count']==9
    return p


def _damage(ir,family):
    rows=[a for a in ir.actions if a.family_key==family]
    assert len(rows)==1
    return rows[0].effects[0].base_min


def test_newer_web_text_stage_changes_actual_core_runtime_but_not_canonical(stage):
    with _build_at(date(2026,10,13)):
        canonical=build_game_ir_slice(class_key='druid',level=20)
        observed=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage)
        assert _damage(canonical,'wrath')==32
        assert _damage(observed,'wrath')==27
        assert _damage(canonical,'moonfire')==25
        assert _damage(observed,'moonfire')==20
        assert _damage(canonical,'starfire')==79
        assert _damage(observed,'starfire')==73
        fact=indexed_rank_fact(class_key='druid',name='Healing Touch',
            required_level=20,effect_kind='direct_heal',db_path=stage)
        assert (fact['low'],fact['high'])==(325,399)
        assert fact['detail_html_independently_verified'] is False
        assert fact['checkpoint_eligibility'].startswith('BLOCKED_')
        # Same real full kill + recovery + incoming attacks, fixed caster
        # challenger: the change must affect a scored production runtime.
        scores=[]
        for ir in (canonical,observed):
            score,execution,details=_policy_combat_evaluation(ir,level=20,
                policy_override=_make_policy(ir,'wrath:5178'),
                schedule_incoming_attacks=True)
            assert score is not None and execution.timeline.target_defeated
            assert details['actor_survived'] and details['event_transitions_new']>0
            scores.append(score.seconds_per_mob)
        assert scores[1]>scores[0]+5, scores
        assert _damage(build_game_ir_slice(class_key='druid',level=20),'wrath')==32
    with sqlite3.connect(DEFAULT_DB) as canonical,sqlite3.connect(stage) as staged:
        assert canonical.execute('SELECT spell_id,raw_listview_json FROM spell_index ORDER BY class_key,spell_id').fetchall()==staged.execute('SELECT spell_id,raw_listview_json FROM spell_index ORDER BY class_key,spell_id').fetchall()


def test_historical_build_uses_canonical_index_not_future_external_stage(stage):
    with _build_at(date(2026,10,10)):
        f=indexed_rank_fact(class_key='druid',name='Wrath',required_level=14,
                            effect_kind='direct_damage',db_path=stage)
        assert f['low']==32 and f['source_authority']=='canonical_forever_source_index_after_tooltip'
    with _build_at(date(2026,10,13)):
        f=indexed_rank_fact(class_key='druid',name='Wrath',required_level=14,
                            effect_kind='direct_damage',db_path=stage)
        assert f['low']==27 and f['source_build']=='1.60.1.70338'


def test_source_identity_tamper_and_unverified_one_source_fail_closed(stage,tmp_path):
    with sqlite3.connect(stage) as con:
        con.execute('''UPDATE source_external_rank_observations SET after_json=?
                       WHERE class_key='druid' AND spell_id=5178''',
                    (json.dumps({'name':'Wrath','text':'Causes 9999 to 9999 Nature damage to the target.'}),))
    with _build_at(date(2026,10,13)),pytest.raises(ExternalRankObservationError,
                                                       match='OBSERVATION_STORED_FIELDS_DRIFT'):
        indexed_rank_fact(class_key='druid',name='Wrath',required_level=14,
                          effect_kind='direct_damage',db_path=stage)
    doc=json.loads(OBS.read_text())
    doc['observations'][0]['source_urls']=doc['observations'][0]['source_urls'][:1]
    bad=tmp_path/'single-source.json';bad.write_text(json.dumps(doc))
    with pytest.raises(ExternalRankObservationError,match='NEEDS_TWO_DISTINCT_HTTPS_SOURCE_DOMAINS'):
        ingest_observations(stage,bad)


def test_joint_search_uses_one_staged_snapshot_and_cannot_accept_web_text(stage):
    with _build_at(date(2026,10,13)):
        result=joint_run(ability_db_path=stage)
        assert result['comparison']['search_l2_attempts']==135
        assert result['comparison']['search_executor_events']>0
        assert result['comparison']['winner_independent_scratch_replay_s_per_mob']==pytest.approx(
            result['comparison']['new_score_s_per_mob'])
        assert result['source_completeness']['external_web_text_observations_not_html_verified']==9
        assert result['source_completeness']['missing_independently_verified_spell_detail_html']>0
        assert result['source_completeness']['selected_item_acquisition_routes_unverified']
        assert result['formal_validated_checkpoint'] is False
        assert result['new_checkpoint_count']==0


def test_current_l20_entrypoint_propagates_stage_to_ir_and_independent_search(stage):
    from tools.wf319_druid_l20_current_source import current_l20
    result=current_l20(as_of=date(2026,10,13),db_path=stage)
    parity=result['source_runtime_index_parity']
    assert next(x for x in parity if x['spell']=='Wrath')['source_fact']==27
    assert next(x for x in parity if x['spell']=='Moonfire' and x['field']=='base_min')['source_fact']==20
    assert result['L2_existing_joint_search']['source_completeness']['external_web_text_observations_not_html_verified']==9
    assert result['accepted_checkpoints']==0

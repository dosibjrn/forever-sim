"""WF343: Druid L20 actual equip legality and sourced passive IR execution."""
import copy
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.rulesets.forever.items.runtime_selection import available_items, item_payload, effective_level, select_gear
from src.rulesets.forever.items.source_equipment_semantics import (
    semantic_for_item, source_equipment_semantics, apply_equipped_source_effects, ledger_path)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0, verify_checkpoint_item_l0
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_persistent_slot_search import _gear_replace

ROOT=Path(__file__).resolve().parents[1]


def _rows():
    return {int(x.item_id):x for x in available_items('druid',20,required_level_policy='observed')}


def test_legal_equipment_denominator_excludes_four_rune_learning_items_but_keeps_true_relic():
    rows=_rows()
    assert len(rows)==1171
    assert not {206954,208689,210534,210195}.intersection(rows)
    assert 249396 in rows
    sem=semantic_for_item(rows[249396])
    assert sem.typed_effects==(('multiply_actor_stat','spirit',1.05),)
    assert len(source_equipment_semantics())==8
    selected=select_gear('druid',20,'druid_feral',required_level_policy='observed',exclude_unknown_item_effects=True)
    assert selected['relic'].item_id==249396
    assert selected['shirt'].slot=='shirt'


def test_complete_l0_universe_and_one_relic_candidate():
    cert=checkpoint_item_l0(class_key='druid',level=20)
    coverage=verify_checkpoint_item_l0(cert,class_key='druid',level=20,
        allow_unattested_diagnostic=True)
    assert coverage['diagnostic_only'] and not coverage['p3_pass']
    assert cert['legal_item_count']==cert['l0_assessed_count']==1171
    assert cert['unknown_effect_item_count']==29
    assert cert['slot_frontiers']['relic']['priority_item_ids']==[249396]
    record=next(x for x in cert['source_items'] if x['item_id']==249396)
    assert record['numeric_source_domains']['spirit_percent']==pytest.approx(5.)
    assert record['l2_effect_fully_supported']


def test_tampered_source_evidence_or_wrong_item_identity_fails_closed(tmp_path,monkeypatch):
    original=ledger_path()
    staged=tmp_path/'source.sqlite'
    with sqlite3.connect(original) as src,sqlite3.connect(staged) as dst:src.backup(dst)
    with sqlite3.connect(staged) as db:
        db.execute("UPDATE source_item_equipment_semantics SET evidence_excerpt='forged' WHERE item_id=249396")
    monkeypatch.setenv('FOREVER_ITEM_EQUIPMENT_SEMANTICS',str(staged))
    with pytest.raises(ValueError,match='PROVENANCE_INVALID'):
        source_equipment_semantics()
    monkeypatch.delenv('FOREVER_ITEM_EQUIPMENT_SEMANTICS')
    bad=copy.copy(_rows()[249396])
    from dataclasses import replace
    with pytest.raises(ValueError,match='IDENTITY_MISMATCH'):
        semantic_for_item(replace(bad,name='Other item'))


def test_actual_ir_spirit_multiplier_and_real_100mob_clock():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-13'
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with tempfile.TemporaryDirectory() as tmp:
        staged=Path(tmp)/'source.sqlite'
        with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db,sqlite3.connect(staged) as dst:db.backup(dst)
        ingest_observations(staged,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(staged,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(staged):
            before=prepare_candidate(class_key='druid',level=20,stage=stage)
            mushroom=_rows()[249396]
            changed=copy.deepcopy(stage)
            changed['gear_policy_result']['winner']['gear']=_gear_replace(
                stage['gear_policy_result']['winner']['gear'],'relic',mushroom)
            after=prepare_candidate(class_key='druid',level=20,stage=changed)
            assert after.ir.actor.base_stats['spirit']==pytest.approx(before.ir.actor.base_stats['spirit']*1.05)
            assert any(e['item_id']==249396 for e in after.ir.provenance['source_equipped_passives'])
            a=evaluate_persistent_candidate(before,level=20,mobs=100,max_total_events=200000)
            b=evaluate_persistent_candidate(after,level=20,mobs=100,max_total_events=200000)
            assert a['status']==b['status']=='COMPLETE'
            assert a['mean_s_per_mob']!=b['mean_s_per_mob']
            # Do not infer a source-complete optimum from a fixed legacy-stage replay.


def test_new_30_300_same_source_and_measured_saturation_not_global_optimum():
    p4=json.loads((ROOT/'evidence/wf344/WF344_P4_SOURCE_EQUIPMENT_30S.json').read_text())
    p5=json.loads((ROOT/'evidence/wf344/WF344_P5_SOURCE_EQUIPMENT_300S.json').read_text())
    for key in ('source_context_sha256','staged_source_sha256',
                'item_catalogue_sha256','equipment_semantics_sha256'):
        assert p4[key]==p5[key]
    assert p4['end_to_end_wall_s']<=30 and p5['end_to_end_wall_s']<=300
    assert p5['distinct_paid_complete_stages_lower_bound']>p4['distinct_paid_complete_stages_lower_bound']
    assert p4['winner']['actual_100mob_s_per_mob']<=1.01*p5['winner']['actual_100mob_s_per_mob']
    assert p4['winner']['gear']['relic']==p5['winner']['gear']['relic']==249396
    assert p4['winner']['gear']['shirt']==p5['winner']['gear']['shirt']
    assert p4['total_events']==p4['joint_events']+p4['persistent_events']
    assert p5['total_events']==p5['joint_events']+p5['persistent_events']


def test_previous_p3_report_is_stale_after_equipment_denominator_correction():
    from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking
    old=json.loads((ROOT/'evidence/wf342/WF342_PROVISIONAL_RATING_TOP5.json').read_text())
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    with pytest.raises(ValueError,match='STALE_EQUIPMENT_SEMANTICS'):
        verify_weighted_ranking(old,class_key='druid',level=20,stage=stage)

"""WF343: Druid L20 actual equip legality and sourced passive IR execution."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from src.rulesets.forever.items.runtime_selection import available_items, item_payload, effective_level, select_gear
from src.rulesets.forever.items.source_equipment_semantics import (
    semantic_for_item, source_equipment_semantics, apply_equipped_source_effects, ledger_path)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0, verify_checkpoint_item_l0

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

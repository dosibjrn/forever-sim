"""L30 item universe and budgeted stat ranking are fail-closed and auditable."""
import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,verify_checkpoint_item_l0
from src.rulesets.forever.items.runtime_selection import available_items
from src.game.data.forever.source_checkpoint_p3_weights import verify_weighted_ranking

ROOT=Path(__file__).resolve().parents[1]

def test_l30_item_universe_non_equipment_excluded_and_all_slotted():
    rows=available_items('druid',30,required_level_policy='observed')
    assert len(rows)==1974
    assert all(item.slot for item in rows)
    assert all(item.item_id !=5514 for item in rows) # Source Mana Agate has no equip slot.
    cert=checkpoint_item_l0(class_key='druid',level=30)
    coverage=verify_checkpoint_item_l0(cert,class_key='druid',level=30,
        allow_unattested_diagnostic=True)
    assert coverage['diagnostic_only'] and not coverage['p3_pass']
    assert cert['legal_item_count']==cert['l0_assessed_count']==1974
    assert len(cert['slot_frontiers'])==18
    assert cert['unknown_effect_item_count']>0

def test_l30_top5_contextual_weights_keep_unknown_axes_explicit():
    evidence=json.loads((ROOT/'evidence/wf351/WF351_L30_P3_TOP5.json').read_text())
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    verify_weighted_ranking(evidence,class_key='druid',level=30,stage=stage)
    assert len(evidence['slots'])==18
    assert evidence['total_legal_items']==1974
    assert evidence['stat_weights']['mobs']==100
    assert len(evidence['stat_weights']['completed_stat_probes'])==6
    assert evidence['unknown_item_count']>0
    assert evidence['stat_weights']['weights']['weapon_dps']['weight_s_saved_per_mob_per_unit'] is None
    assert all(len(slot['weighted_top'])==min(5,slot['available_legal']) for slot in evidence['slots'].values())

def test_l30_p3_is_not_false_full_acceptance():
    summary=json.loads((ROOT/'evidence/wf351/WF351_L30_P3_SUMMARY.json').read_text())
    assert summary['p3_l0'] is True
    assert summary['p3_user_contract_pass'] is False
    assert summary['accepted_checkpoints']=='1/148'

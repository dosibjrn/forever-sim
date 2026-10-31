from __future__ import annotations
import os,sqlite3
from pathlib import Path
import pytest
from src.rulesets.forever.items.runtime_selection import (available_items,clear_runtime_item_cache,
    source_class_item_membership_verified)
from tools.wf370_warrior_l30_source_bis_stage import stage,STAGE,PARENT
from src.rulesets.forever.items.catalogue import ItemCatalogue


def test_source_bis_adds_two_missing_items_and_preserves_global_fail_closed(tmp_path,monkeypatch):
    output=tmp_path/'warrior.sqlite'
    result=stage(output)
    assert result['source_item_witnesses']==11
    assert result['new_catalogue_items']==2
    assert not result['global_membership_verified']
    with sqlite3.connect(PARENT) as db:
        assert not db.execute('SELECT 1 FROM items WHERE item_id IN (6976,1488)').fetchone()
    with sqlite3.connect(output) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT verified FROM class_source_attestation WHERE class_id=1').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1 AND provenance LIKE "https://foreverdb.net/item/%"').fetchone()[0]==11
    assert not source_class_item_membership_verified('warrior',output)
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(output))
    clear_runtime_item_cache()
    items={x.item_id:x for x in available_items('warrior',30,required_level_policy='observed')}
    assert 6976 in items and 1488 in items
    assert items[6976].required_level==0
    assert items[6976].required_level_origin=='source_confirmed_no_requirement'
    assert items[1488].required_level==26
    assert items[6976].weapon_hands==2
    assert items[1488].armor_type=='mail'
    assert 6976 not in {x.item_id for x in available_items('warrior',20,required_level_policy='observed')}


def test_observed_requirement_not_inferred_floor(tmp_path,monkeypatch):
    stage(tmp_path/'warrior.sqlite')
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(tmp_path/'warrior.sqlite'))
    clear_runtime_item_cache()
    # The level-40 quest reward has no equip-level requirement.  A statistical
    # ilvl floor must not fabricate one (the quest starts at level 30).
    assert 6976 in {x.item_id for x in available_items('warrior',30,required_level_policy='observed')}


def test_source_data_does_not_claim_complete_warrior_universe():
    import json
    from tools.wf370_warrior_l30_source_bis_stage import SOURCE
    data=json.loads(SOURCE.read_text())
    assert data['source_build']=='1.60.1.70338'
    assert len({x['item_id'] for x in data['items']})==11
    assert 'not an exhaustive' in data['source_limitations']

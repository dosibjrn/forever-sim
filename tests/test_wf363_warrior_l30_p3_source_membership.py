"""WF363 Warrior gear provenance and 18-slot fail-closed regressions."""
from __future__ import annotations
import json,os,sqlite3,tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from src.rulesets.forever.items.runtime_selection import (
    _source_class_profile,_source_class_id,_armor_allowed,_weapon_allowed,
    available_items,_AVAILABLE_ITEMS_CACHE,
)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_slots
from tools.wf363_warrior_l30_gear_stage import stage,warrior_source_membership_verified
from test_wf364_warrior_capture_integrity import fixture_capture


def test_warrior_profile_is_data_sourced():
    p=_source_class_profile('warrior')
    assert p['client_build_scope']=='1.60.1.70338'
    assert p['class_id']==_source_class_id('warrior')==1
    assert all(x['url'].startswith('https://') for x in p['sources'])
    assert len(p['required_fillable_slots'])==18


def test_armor_and_polearm_proficiency_boundaries():
    assert _armor_allowed('warrior',30,SimpleNamespace(slot='chest',armor_type='mail'))
    assert not _armor_allowed('warrior',30,SimpleNamespace(slot='chest',armor_type='plate'))
    assert _armor_allowed('warrior',40,SimpleNamespace(slot='chest',armor_type='plate'))
    assert not _weapon_allowed('warrior',SimpleNamespace(weapon_type='polearm'),19)
    assert _weapon_allowed('warrior',SimpleNamespace(weapon_type='polearm'),20)
    assert not _weapon_allowed('warrior',SimpleNamespace(weapon_type='wand'),30)
    assert _weapon_allowed('warrior',SimpleNamespace(weapon_type='two_hand_sword'),30)


def test_source_slot_thrown_tabard():
    assert source_item_slots(SimpleNamespace(slot='thrown',weapon_type='thrown',item_id=5))==('ranged',)
    assert source_item_slots(SimpleNamespace(slot='tabard',weapon_type='',item_id=6))==('tabard',)


def test_canonical_warrior_class_membership_missing():
    from src.rulesets.forever.items.runtime_selection import _DEFAULT_DB
    with sqlite3.connect(_DEFAULT_DB) as db:
        assert db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1').fetchone()[0]==0
    assert not warrior_source_membership_verified(_DEFAULT_DB)


def test_provisional_stage_never_passes_p3(monkeypatch,tmp_path):
    dest=tmp_path/'warrior.sqlite'
    result=stage(output=dest,provisional=True)
    assert result['source_membership_count']>0
    assert not result['membership_verified_complete'] and not result['p3_pass']
    assert not warrior_source_membership_verified(dest)
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(dest))
    _AVAILABLE_ITEMS_CACHE.clear()
    cert=checkpoint_item_l0(class_key='warrior',level=30)
    assert cert['legal_item_count']==cert['l0_assessed_count']>0
    assert len(cert['slot_frontiers'])==18
    assert not cert['missing_required_slots']
    assert not cert['source_membership_verified'] and not cert['p3_pass']
    assert cert['unknown_effect_item_count']>0
    _AVAILABLE_ITEMS_CACHE.clear()


def test_stager_rejects_unsourced_and_wrong_class(tmp_path):
    dest=tmp_path/'stage.sqlite'
    bad=tmp_path/'wrong.json'
    bad.write_text(json.dumps({'schema':'forever_class_item_listview_v1','class_id':2,'pages':[]}))
    with pytest.raises(ValueError,match='WRONG_CLASS'):
        stage(output=dest,source_json=bad)
    bad.write_text(json.dumps({'schema':'forever_class_item_listview_v1','class_id':1,'pages':[{'source_url':'https://example.com/not-source','fetch_status':'verified_listview','item_ids':[1]}],'total_rows':1,'complete_pages':True}))
    with pytest.raises(ValueError,match='UNVERIFIED_EXPORT'):
        stage(output=dest,source_json=bad)


def test_stager_rejects_incomplete_and_missing_items(tmp_path):
    dest=tmp_path/'stage.sqlite'; source=tmp_path/'snapshot.json'
    page={'source_url':'https://www.wowhead.com/forever/items/class:1','fetch_status':'verified_listview','item_ids':[200,200]}
    source.write_text(json.dumps({'schema':'forever_class_item_listview_v1','class_id':1,'pages':[page],'total_rows':2,'complete_pages':True}))
    with pytest.raises(ValueError,match='UNVERIFIED_EXPORT'):
        stage(output=dest,source_json=source)
    page['item_ids']=[999999999]
    source.write_text(json.dumps({'schema':'forever_class_item_listview_v1','class_id':1,'pages':[page],'total_rows':1,'complete_pages':True}))
    with pytest.raises(ValueError,match='UNVERIFIED_EXPORT'):
        stage(output=dest,source_json=source)


def test_existing_adaptive_capture_import_preserves_other_class_membership(tmp_path):
    from src.rulesets.forever.items.wowhead_queries import canonical_bands
    assert all(b.class_id==1 and 'class:1' in b.url for b in canonical_bands('warrior'))
    cap=tmp_path/'capture';fixture_capture(cap)
    out=tmp_path/'stage.sqlite'
    result=stage(output=out,capture_dir=cap)
    assert result['membership_verified_complete']
    assert warrior_source_membership_verified(out)
    with sqlite3.connect(out) as db:
        assert db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=1').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM item_class_eligibility WHERE class_id=11').fetchone()[0]>0
        assert db.execute('SELECT source_url FROM items WHERE item_id=200').fetchone()[0].endswith('item=200')


def test_partial_verified_membership_still_fails_missing_slots(tmp_path,monkeypatch):
    cap=tmp_path/'capture';fixture_capture(cap)
    out=tmp_path/'stage.sqlite';stage(output=out,capture_dir=cap)
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(out))
    _AVAILABLE_ITEMS_CACHE.clear()
    cert=checkpoint_item_l0(class_key='warrior',level=30)
    assert cert['source_membership_verified']
    assert cert['missing_required_slots']
    assert not cert['p3_pass']
    _AVAILABLE_ITEMS_CACHE.clear()


def test_membership_attestation_count_tampering_fails_closed(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    dest=tmp_path/'stage.sqlite';stage(output=dest,capture_dir=cap)
    assert warrior_source_membership_verified(dest)
    with sqlite3.connect(dest) as db:
        db.execute('UPDATE class_source_attestation SET member_count=member_count+1 WHERE class_id=1')
    assert not warrior_source_membership_verified(dest)

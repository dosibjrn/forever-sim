"""WF388: true class-filtered item denominator, not inherited profile fallback."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
import pytest

from src.rulesets.forever.items.runtime_selection import (
    _DEFAULT_DB, source_class_item_membership_verified,
)
from src.rulesets.forever.items.wowhead_queries import (
    CANONICAL_CLASS_QUERIES, bands_for_class, canonical_bands,
)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0


def _fixture_export(path: Path, class_key: str, *, missing_band=False) -> None:
    bands=list(canonical_bands(class_key))
    if missing_band:
        bands=bands[1:]
    pages=[]
    for b in bands:
        ids=[200] if b.min_item_level<=20<=b.max_item_level else []
        pages.append(dict(source_url=b.url,min_item_level=b.min_item_level,
            max_item_level=b.max_item_level,http_status=200,
            fetch_status='verified_listview',item_ids=ids,unique_item_count=len(ids),
            item_ids_sha256=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()))
    path.write_text(json.dumps(dict(schema='forever_class_item_listview_v1',
        class_id=CANONICAL_CLASS_QUERIES[class_key].class_id,
        complete_pages=True,captured_at='2026-10-14T23:00:00Z',
        pages=pages,total_rows=1)))


@pytest.mark.parametrize('class_key',['mage','druid','paladin','hunter'])
def test_existing_class_rows_are_not_complete_capture_attestation(class_key):
    assert not source_class_item_membership_verified(class_key,_DEFAULT_DB)


def test_mage_checkpoint_p3_cannot_pass_from_unattested_1312_items():
    r=checkpoint_item_l0(class_key='mage',level=30)
    assert r['legal_item_count']>=1000
    assert r['l0_assessed_count']==r['legal_item_count']
    assert not r['source_membership_verified']
    assert not r['p3_pass']


@pytest.mark.parametrize('class_key',['mage','druid','paladin','hunter'])
def test_class_capture_must_cover_entire_source_item_level_envelope(class_key):
    bands=bands_for_class(class_key)
    assert bands[0][0]==1 and bands[-1][1]==255
    assert all(a[1]+1==b[0] for a,b in zip(bands,bands[1:]))


def test_generic_verified_mage_export_stages_and_attests_only_that_capture(tmp_path):
    from tools.wf388_stage_class_item_capture import stage_class_capture
    source=tmp_path/'mage.json';out=tmp_path/'mage.sqlite'
    _fixture_export(source,'mage')
    original_hash=hashlib.sha256(_DEFAULT_DB.read_bytes()).hexdigest()
    result=stage_class_capture(class_key='mage',output=out,source_json=source)
    assert result['class_key']=='mage' and result['source_membership_count']==1
    assert result['membership_verified_complete']
    assert source_class_item_membership_verified('mage',out)
    assert hashlib.sha256(_DEFAULT_DB.read_bytes()).hexdigest()==original_hash
    with sqlite3.connect(out) as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert db.execute('select count(*) from item_class_eligibility where class_id=8').fetchone()[0]==1
        assert db.execute('select count(*) from item_class_eligibility where class_id=11').fetchone()[0]>0
        db.execute('update item_class_eligibility set provenance=? where class_id=8',('UNVERIFIED',))
    assert not source_class_item_membership_verified('mage',out)


def test_incomplete_or_wrong_class_capture_cannot_be_staged(tmp_path):
    from tools.wf388_stage_class_item_capture import stage_class_capture
    source=tmp_path/'mage.json';out=tmp_path/'mage.sqlite'
    _fixture_export(source,'mage',missing_band=True)
    with pytest.raises(ValueError,match='CAPTURE_INTEGRITY_'):
        stage_class_capture(class_key='mage',output=out,source_json=source)
    assert not out.exists()
    _fixture_export(source,'druid')
    with pytest.raises(ValueError,match='CAPTURE_INTEGRITY_WRONG_CLASS'):
        stage_class_capture(class_key='mage',output=out,source_json=source)
    assert not out.exists()


def test_unattested_mage_pool_can_be_verified_as_diagnostic_without_p3_pass():
    from copy import deepcopy
    from src.game.data.forever.source_checkpoint_p3 import verify_checkpoint_item_l0
    cert=checkpoint_item_l0(class_key='mage',level=30)
    with pytest.raises(ValueError,match='P3_CERTIFICATE_CHECKPOINT_MISMATCH'):
        verify_checkpoint_item_l0(cert,class_key='mage',level=30)
    coverage=verify_checkpoint_item_l0(cert,class_key='mage',level=30,
                                       allow_unattested_diagnostic=True)
    assert coverage['diagnostic_only'] and not coverage['p3_pass']
    assert coverage['assessed_count']==1312
    bad=deepcopy(cert)
    bad['slot_frontiers']['weapon']['priority_item_ids'].pop()
    with pytest.raises(ValueError,match='FRONTIER_INCOMPLETE'):
        verify_checkpoint_item_l0(bad,class_key='mage',level=30,
                                  allow_unattested_diagnostic=True)
    bad=deepcopy(cert)
    bad['source_items'][0]['numeric_source_domains']['strength']=999999
    with pytest.raises(ValueError,match='TAMPERED_ITEM_VECTOR'):
        verify_checkpoint_item_l0(bad,class_key='mage',level=30,
                                  allow_unattested_diagnostic=True)


def test_mage_unattested_p3_proposals_require_explicit_opt_in():
    from src.game.data.forever.gear import select_named_gear
    from src.v2.source_persistent_slot_search import _source_slot_proposals
    cert=checkpoint_item_l0(class_key='mage',level=30)
    base=select_named_gear(class_key='mage',level=30,role='mage',
        stat_weights={'intellect':1.,'spell_power':1.,'stamina':.2},
        required_level_policy='observed').as_dict()
    with pytest.raises(ValueError,match='P3_CERTIFICATE_CHECKPOINT_MISMATCH'):
        _source_slot_proposals(class_key='mage',level=30,base=base,
                               p3_certificate=cert)
    proposals,counts=_source_slot_proposals(class_key='mage',level=30,base=base,
        p3_certificate=cert,allow_unattested_diagnostic=True,
        per_slot=2,max_proposals=48)
    assert len(proposals)>=18 and counts['weapon']>5
    assert all(item.item_id in {x['item_id'] for x in cert['source_items']}
               for _,item in proposals)

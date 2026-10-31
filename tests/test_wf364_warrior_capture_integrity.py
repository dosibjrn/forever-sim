"""The source membership certificate must represent the captured source bytes."""
from __future__ import annotations
import copy
from hashlib import sha256
import json
from pathlib import Path
import pytest

from src.rulesets.forever.items.wowhead_queries import canonical_bands
from src.rulesets.forever.items.source_capture_integrity import verify_class_capture
from tools.wf363_warrior_l30_gear_stage import stage


def fixture_capture(cap: Path) -> None:
    cap.mkdir(exist_ok=True)
    bands = canonical_bands('warrior')
    leaves = []
    merged = []
    for idx, band in enumerate(bands):
        rows = [{'id':200,'name':'Sourced Sword','slot':13,'classs':2,
                 'subclass':7,'level':20,'reqlevel':15}] if (band.min_item_level,band.max_item_level)==(10,29) else []
        stem = f'warrior_ilvl_{band.min_item_level}_{band.max_item_level}'
        html = f'<html><title>Forever items</title><body>{len(rows)} items found</body></html>'.encode()
        payload = (json.dumps(rows,separators=(',',':'))+'\n').encode()
        (cap/f'{stem}.html').write_bytes(html)
        (cap/f'{stem}.listview.json').write_bytes(payload)
        leaf = dict(class_key='warrior',class_id=1,min_item_level=band.min_item_level,
                    max_item_level=band.max_item_level,url=band.url,http_status=200,
                    found_count=len(rows),displayed_count=len(rows),listview_rows=len(rows),
                    listview_unique_ids=len(rows),blocked_marker=None,accepted=True,
                    needs_split=False,html_file=f'{stem}.html',listview_file=f'{stem}.listview.json',
                    html_sha256=sha256(html).hexdigest(),listview_sha256=sha256(payload).hexdigest())
        leaves.append(leaf)
        merged.extend(rows)
    manifest = dict(schema_version=1,capture_backend='playwright_persistent_chrome_adaptive',
                    captured_at='2026-10-14T05:00:00Z',classes=['warrior'],
                    seed_bands=[[b.min_item_level,b.max_item_level] for b in bands],
                    attempts=copy.deepcopy(leaves),leaves=copy.deepcopy(leaves))
    (cap/'manifest.json').write_text(json.dumps(manifest))
    (cap/'warrior_merged.listview.json').write_text(json.dumps(merged))


def mutate_manifest(cap, mutator):
    path=cap/'manifest.json'; manifest=json.loads(path.read_text())
    mutator(manifest);path.write_text(json.dumps(manifest))


def test_full_class_capture_passes_and_stages(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    cert=verify_class_capture(cap,'warrior')
    assert cert.leaf_count==len(canonical_bands('warrior'))
    assert list(cert.base_rows)==[200]
    assert cert.provenance_by_id[200].endswith('class:1?filter=161:195;1:1;0:0')
    staged=stage(output=tmp_path/'warrior.sqlite',capture_dir=cap)
    assert staged['membership_verified_complete'] and staged['source_membership_count']==1


def test_missing_seed_band_fails_closed(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    mutate_manifest(cap,lambda m:(m['leaves'].pop(),m['attempts'].pop()))
    with pytest.raises(ValueError,match='SEED_RANGE_GAP'):
        verify_class_capture(cap,'warrior')


def test_only_one_leaf_is_not_complete(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    mutate_manifest(cap,lambda m:(m.__setitem__('leaves',m['leaves'][1:2]),
                                   m.__setitem__('attempts',m['attempts'][1:2])))
    with pytest.raises(ValueError,match='SEED_RANGE_GAP'):
        stage(output=tmp_path/'stage.sqlite',capture_dir=cap)


def test_unverified_merged_file_rejected(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    (cap/'warrior_merged.listview.json').write_text('[]')
    with pytest.raises(ValueError,match='MERGED_ROWS_DIFFER'):
        verify_class_capture(cap,'warrior')


def test_modified_listview_bytes_rejected(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    name=json.loads((cap/'manifest.json').read_text())['leaves'][1]['listview_file']
    (cap/name).write_text('[]\n')
    with pytest.raises(ValueError,match='LISTVIEW_HASH_MISMATCH'):
        verify_class_capture(cap,'warrior')


def test_source_class_filter_and_http_verified(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    mutate_manifest(cap,lambda m:(m['leaves'][1].__setitem__('url',m['leaves'][1]['url'].replace('class:1','class:2')),
                                  m['attempts'][1].__setitem__('url',m['attempts'][1]['url'].replace('class:1','class:2'))))
    with pytest.raises(ValueError,match='WRONG_CLASS_FILTER'):
        verify_class_capture(cap,'warrior')


def test_outside_band_item_rejected(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    manifest=json.loads((cap/'manifest.json').read_text())
    leaf=manifest['leaves'][1]; path=cap/leaf['listview_file']
    rows=json.loads(path.read_text());rows[0]['level']=99
    payload=(json.dumps(rows,separators=(',',':'))+'\n').encode();path.write_bytes(payload)
    leaf['listview_sha256']=sha256(payload).hexdigest()
    manifest['attempts'][1]['listview_sha256']=leaf['listview_sha256']
    (cap/'manifest.json').write_text(json.dumps(manifest))
    (cap/'warrior_merged.listview.json').write_text(json.dumps(rows))
    with pytest.raises(ValueError,match='ITEM_OUTSIDE_CAPTURED_BAND'):
        verify_class_capture(cap,'warrior')


def test_positive_count_but_empty_rows_rejected(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    mutate_manifest(cap,lambda m:(m['leaves'][0].__setitem__('found_count',7),
                                  m['attempts'][0].__setitem__('found_count',7),
                                  m['leaves'][0].__setitem__('displayed_count',7),
                                  m['attempts'][0].__setitem__('displayed_count',7)))
    with pytest.raises(ValueError,match='POSITIVE_FOUND_BUT_EMPTY'):
        verify_class_capture(cap,'warrior')


def test_same_count_membership_tamper_fails_closed(tmp_path):
    import sqlite3
    from tools.wf363_warrior_l30_gear_stage import warrior_source_membership_verified
    cap=tmp_path/'capture';fixture_capture(cap)
    dest=tmp_path/'stage.sqlite';stage(output=dest,capture_dir=cap)
    assert warrior_source_membership_verified(dest)
    with sqlite3.connect(dest) as db:
        db.execute('UPDATE item_class_eligibility SET item_id=201 WHERE class_id=1 AND item_id=200')
    assert not warrior_source_membership_verified(dest)


def test_unverified_export_boolean_does_not_certify_a_denominator(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    export=tmp_path/'export.json'
    export.write_text(json.dumps({'schema':'forever_class_item_listview_v1',
        'class_id':1,'complete_pages':True,'captured_at':'2026-10-14T05:00:00Z',
        'pages':[{'source_url':canonical_bands('warrior')[1].url,
                  'fetch_status':'verified_listview','item_ids':[200]}],
        'total_rows':1}))
    with pytest.raises(ValueError,match='CAPTURE_INTEGRITY_'):
        stage(output=tmp_path/'staged.sqlite',source_json=export)


def test_complete_export_has_provenance_but_requires_real_catalogue_rows(tmp_path):
    cap=tmp_path/'capture';fixture_capture(cap)
    pages=[]
    for band in canonical_bands('warrior'):
        ids=[200] if band.min_item_level==10 else []
        pages.append(dict(source_url=band.url,min_item_level=band.min_item_level,
            max_item_level=band.max_item_level,http_status=200,
            fetch_status='verified_listview',item_ids=ids,unique_item_count=len(ids),
            item_ids_sha256=sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()))
    export=tmp_path/'export.json'
    export.write_text(json.dumps(dict(schema='forever_class_item_listview_v1',class_id=1,
        complete_pages=True,captured_at='2026-10-14T05:00:00Z',pages=pages,total_rows=1)))
    result=stage(output=tmp_path/'stage.sqlite',source_json=export)
    assert result['membership_verified_complete'] and result['source_membership_count']==1
    pages[-1]['item_ids']=[999999]
    pages[-1]['unique_item_count']=1
    pages[-1]['item_ids_sha256']=sha256(b'[999999]').hexdigest()
    export.write_text(json.dumps(dict(schema='forever_class_item_listview_v1',class_id=1,
        complete_pages=True,captured_at='2026-10-14T05:00:00Z',pages=pages,total_rows=2)))
    with pytest.raises(ValueError,match='MISSING_CANONICAL_ITEM_ROWS'):
        stage(output=tmp_path/'stage2.sqlite',source_json=export)

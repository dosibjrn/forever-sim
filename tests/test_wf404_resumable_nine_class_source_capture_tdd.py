"""WF404: real source-capture continuity, not a fabricated P3 certificate."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.rulesets.forever.items.wowhead_queries import CANONICAL_CLASS_QUERIES, canonical_bands
from src.rulesets.forever.items.wowhead_capture_import import CLASS_IDS
from src.rulesets.forever.items.source_capture_integrity import verify_class_capture
from tools.capture_wowhead_adaptive import run_adaptive_capture

EXPECTED_CLASSES = {
    'warrior': 1, 'paladin': 2, 'hunter': 3, 'rogue': 4, 'priest': 5,
    'shaman': 7, 'mage': 8, 'warlock': 9, 'druid': 11,
}


def fake_capture(calls, *, fail_after=None, split=None):
    def fetch(band, folder):
        if fail_after is not None and len(calls) == fail_after:
            raise RuntimeError('SIMULATED_BROWSER_CRASH')
        calls.append((band.class_key, band.min_item_level, band.max_item_level))
        lo, hi = band.min_item_level, band.max_item_level
        needs_split = (lo, hi) == split
        rows = [] if needs_split else [dict(id=10000+lo, name=f'Source {lo}', level=lo,
                                            slot=5, classs=4, subclass=2, reqlevel=1)]
        stem = f'{band.class_key}_ilvl_{lo}_{hi}'
        html = f'<html>{len(rows)} items found</html>'.encode()
        payload = (json.dumps(rows, separators=(',', ':'))+'\n').encode()
        (folder / f'{stem}.html').write_bytes(html)
        (folder / f'{stem}.listview.json').write_bytes(payload)
        return dict(class_key=band.class_key, class_id=band.class_id,
                    min_item_level=lo, max_item_level=hi, url=band.url,
                    http_status=200, found_count=len(rows), displayed_count=len(rows),
                    listview_rows=len(rows), listview_unique_ids=len(rows),
                    blocked_marker=None, accepted=True, needs_split=needs_split,
                    html_file=f'{stem}.html', listview_file=f'{stem}.listview.json',
                    html_sha256=sha256(html).hexdigest(), listview_sha256=sha256(payload).hexdigest())
    return fetch


def test_nine_classes_have_full_source_capture_envelope():
    assert {k: q.class_id for k,q in CANONICAL_CLASS_QUERIES.items()} == EXPECTED_CLASSES
    assert CLASS_IDS == EXPECTED_CLASSES
    for key in EXPECTED_CLASSES:
        bands = canonical_bands(key)
        assert bands[0].min_item_level == 1
        assert bands[-1].max_item_level == 255
        assert all(a.max_item_level+1 == b.min_item_level for a,b in zip(bands,bands[1:]))


def test_resume_after_browser_crash_does_not_refetch_paid_source_bytes(tmp_path):
    cap=tmp_path/'druid';calls=[]
    with pytest.raises(RuntimeError, match='SIMULATED_BROWSER_CRASH'):
        run_adaptive_capture('druid',cap,fake_capture(calls,fail_after=3))
    assert len(calls)==3
    manifest=json.loads((cap/'manifest.json').read_text())
    assert len(manifest['attempts'])==3
    result=run_adaptive_capture('druid',cap,fake_capture(calls),resume=True)
    assert result['complete'] and len(calls)==len(canonical_bands('druid'))
    assert len(result['attempts'])==len(canonical_bands('druid'))
    verified=verify_class_capture(cap,'druid')
    assert verified.leaf_count==len(canonical_bands('druid'))
    assert len(verified.base_rows)==len(canonical_bands('druid'))


def test_resume_rejects_tampered_html_before_any_refetch(tmp_path):
    cap=tmp_path/'druid';calls=[]
    with pytest.raises(RuntimeError):
        run_adaptive_capture('druid',cap,fake_capture(calls,fail_after=2))
    first=json.loads((cap/'manifest.json').read_text())['attempts'][0]
    (cap/first['html_file']).write_text('FORGED')
    new_calls=[]
    with pytest.raises(ValueError,match='CAPTURE_RESUME_.*HASH'):
        run_adaptive_capture('druid',cap,fake_capture(new_calls),resume=True)
    assert not new_calls


def test_resume_rejects_wrong_class_and_unrequested_overwrite(tmp_path):
    cap=tmp_path/'druid';calls=[]
    with pytest.raises(RuntimeError):
        run_adaptive_capture('druid',cap,fake_capture(calls,fail_after=2))
    with pytest.raises(ValueError,match='CAPTURE_RESUME_CLASS_OR_QUERY'):
        run_adaptive_capture('priest',cap,fake_capture([]),resume=True)
    with pytest.raises(FileExistsError,match='CAPTURE_EXISTS_USE_RESUME'):
        run_adaptive_capture('druid',cap,fake_capture([]))


def test_split_resume_replays_exact_source_partition(tmp_path):
    cap=tmp_path/'warrior';calls=[]
    # The 10-29 parent is truncated. A crash happens after it is recorded,
    # before its children are captured; the resume must replay the split queue.
    with pytest.raises(RuntimeError):
        run_adaptive_capture('warrior',cap,fake_capture(calls,fail_after=2,split=(10,29)))
    assert calls == [('warrior',1,9),('warrior',10,29)]
    result=run_adaptive_capture('warrior',cap,fake_capture(calls),resume=True)
    assert result['complete']
    assert calls[2:4]==[('warrior',10,19),('warrior',20,29)]
    cert=verify_class_capture(cap,'warrior')
    assert cert.leaf_count==len(canonical_bands('warrior'))+1
    assert len(cert.base_rows)==len(canonical_bands('warrior'))+1

@pytest.mark.parametrize('class_key', list(EXPECTED_CLASSES))
def test_every_class_complete_source_capture_can_stage_without_mutating_canonical(tmp_path, class_key):
    """Synthetic offline integration only; NEVER certify upstream Wowhead."""
    from tools.wf388_stage_class_item_capture import stage_class_capture
    from src.rulesets.forever.items.runtime_selection import (
        _DEFAULT_DB, source_class_item_membership_verified,
    )
    folder=tmp_path/class_key
    run_adaptive_capture(class_key,folder,fake_capture([]))
    staged=tmp_path/f'{class_key}.sqlite'
    original=sha256(_DEFAULT_DB.read_bytes()).hexdigest()
    result=stage_class_capture(class_key=class_key,output=staged,capture_dir=folder)
    assert result['membership_verified_complete']
    assert result['source_membership_count']==len(canonical_bands(class_key))
    assert source_class_item_membership_verified(class_key,staged)
    assert sha256(_DEFAULT_DB.read_bytes()).hexdigest()==original
    assert result['p3_pass'] is False

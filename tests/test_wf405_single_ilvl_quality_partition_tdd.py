"""WF405: real single-ilvl Wowhead listview cap must be provably partitioned.

All records are synthetic transport fixtures. No P3 live source claim.
"""
import json
from hashlib import sha256

import pytest

from tools.capture_wowhead_adaptive import run_adaptive_capture
from src.rulesets.forever.items.source_capture_integrity import verify_class_capture


def _source(rows, band, folder, found, needs_split):
    quality = getattr(band, 'quality', None)
    suffix = '' if quality is None else f'_quality_{quality}'
    stem = f'{band.class_key}_ilvl_{band.min_item_level}_{band.max_item_level}{suffix}'
    html = f'<html>{found} items found</html>'.encode()
    data = (json.dumps(rows, separators=(',', ':')) + '\n').encode()
    (folder / f'{stem}.html').write_bytes(html)
    (folder / f'{stem}.listview.json').write_bytes(data)
    return dict(class_key=band.class_key, class_id=band.class_id,
                min_item_level=band.min_item_level, max_item_level=band.max_item_level,
                **({'quality': quality} if quality is not None else {}),
                url=band.url, http_status=200, found_count=found,
                displayed_count=len(rows), listview_rows=len(rows),
                listview_unique_ids=len({r['id'] for r in rows}),
                blocked_marker=None, accepted=True, needs_split=needs_split,
                html_file=f'{stem}.html', listview_file=f'{stem}.listview.json',
                html_sha256=sha256(html).hexdigest(), listview_sha256=sha256(data).hexdigest())


def _item(i, level, quality=None):
    row = dict(id=i, name=f'Item {i}', level=level, reqlevel=1, slot=5,
               classs=4, subclass=2)
    if quality is not None:
        row['quality'] = quality
    return row


def _fetch(calls, *, crash_at=None, lost_item=False, duplicate=False, unknown_parent=False):
    def fetch(band, folder):
        if crash_at is not None and len(calls) == crash_at:
            raise RuntimeError('SIMULATED_BROWSER_CRASH')
        quality = getattr(band, 'quality', None)
        calls.append((band.min_item_level, band.max_item_level, quality))
        if (band.min_item_level, band.max_item_level) != (10, 10):
            return _source([], band, folder, 0, False)
        if quality is None:
            return _source([_item(i, 10) for i in range(1, 1001)], band, folder,
                           None if unknown_parent else 1002, True)
        if quality == 2:
            return _source([_item(i, 10, 2) for i in range(1, 701)], band, folder, 700, False)
        if quality == 3:
            ids = list(range(701, 1003))
            if lost_item:
                ids.pop()
            if duplicate:
                ids[0] = 1
            return _source([_item(i, 10, 3) for i in ids], band, folder,
                           len(ids), False)
        return _source([], band, folder, 0, False)
    return fetch


def test_capped_single_item_level_splits_into_eight_quality_queries_and_attests(tmp_path, monkeypatch):
    import tools.capture_wowhead_adaptive as capture
    import src.rulesets.forever.items.source_capture_integrity as integrity
    monkeypatch.setattr(capture, 'bands_for_class', lambda key: ((10, 10),))
    monkeypatch.setattr(integrity, 'bands_for_class', lambda key: ((10, 10),))
    calls = []
    result = run_adaptive_capture('druid', tmp_path, _fetch(calls))
    assert result['complete']
    assert calls == [(10, 10, None)] + [(10, 10, q) for q in range(8)]
    certificate = verify_class_capture(tmp_path, 'druid')
    assert certificate.leaf_count == 8
    assert len(certificate.base_rows) == 1002
    assert all('/quality:' in url for url in certificate.provenance_by_id.values())


def test_resume_after_quality_split_reuses_attested_parent_and_children(tmp_path, monkeypatch):
    import tools.capture_wowhead_adaptive as capture
    import src.rulesets.forever.items.source_capture_integrity as integrity
    monkeypatch.setattr(capture, 'bands_for_class', lambda key: ((10, 10),))
    monkeypatch.setattr(integrity, 'bands_for_class', lambda key: ((10, 10),))
    calls=[]
    with pytest.raises(RuntimeError, match='SIMULATED_BROWSER_CRASH'):
        run_adaptive_capture('druid', tmp_path, _fetch(calls, crash_at=4))
    assert calls == [(10, 10, None), (10, 10, 0), (10, 10, 1), (10, 10, 2)]
    result=run_adaptive_capture('druid', tmp_path, _fetch(calls), resume=True)
    assert result['complete'] and len(calls) == 9
    assert len(verify_class_capture(tmp_path, 'druid').base_rows) == 1002


@pytest.mark.parametrize('fault,expected', [
    ('lost_item','QUALITY_COUNT_MISMATCH'),
    ('duplicate','QUALITY_OVERLAP'),
    ('unknown_parent','SOURCE_FOUND_COUNT_UNATTESTED'),
])
def test_unproven_quality_partition_fails_closed(tmp_path, monkeypatch, fault, expected):
    import tools.capture_wowhead_adaptive as capture
    import src.rulesets.forever.items.source_capture_integrity as integrity
    monkeypatch.setattr(capture, 'bands_for_class', lambda key: ((10, 10),))
    monkeypatch.setattr(integrity, 'bands_for_class', lambda key: ((10, 10),))
    calls=[]
    with pytest.raises(ValueError, match=expected):
        run_adaptive_capture('druid', tmp_path, _fetch(calls, **{fault: True}))
    assert len(calls) == (1 if fault == 'unknown_parent' else 9)
    assert not json.loads((tmp_path/'manifest.json').read_text())['complete']


def test_manifest_cannot_forge_parent_found_count_to_hide_missing_item(tmp_path, monkeypatch):
    import tools.capture_wowhead_adaptive as capture
    import src.rulesets.forever.items.source_capture_integrity as integrity
    monkeypatch.setattr(capture, 'bands_for_class', lambda key: ((10, 10),))
    monkeypatch.setattr(integrity, 'bands_for_class', lambda key: ((10, 10),))
    with pytest.raises(ValueError, match='QUALITY_COUNT_MISMATCH'):
        run_adaptive_capture('druid', tmp_path, _fetch([], lost_item=True))
    manifest_path = tmp_path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['attempts'][0]['found_count'] == 1002
    manifest['attempts'][0]['found_count'] = 1001  # Source HTML still says 1002.
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='SOURCE_FOUND_COUNT_MISMATCH'):
        verify_class_capture(tmp_path, 'druid')

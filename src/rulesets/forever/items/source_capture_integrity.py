"""Fail-closed verification of a *complete* class-filtered adaptive listview capture.

A successful HTTP request, a nonempty merged JSON file, or a claim of
``complete_pages`` is not sufficient to attest a class's item universe.
The original seed bands must be covered exactly once by the terminal leaves,
and those leaves must be bound to the bytes actually captured from the page.
This verifies local capture integrity, NOT the completeness of Wowhead's own
upstream item index or any in-game loot availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import unescape
import re
import json
from pathlib import Path
from typing import Any

from .wowhead_queries import (CANONICAL_CLASS_QUERIES, WOWHEAD_QUALITY_VALUES,
                              bands_for_class, build_search_url, child_capture_coordinates)
from .wowhead_capture_import import canonical_base_rows


@dataclass(frozen=True)
class VerifiedClassCapture:
    class_key: str
    class_id: int
    captured_at: str
    base_rows: dict[int, dict[str, Any]]
    leaf_count: int
    manifest_sha256: str
    captured_rows_sha256: str
    provenance_by_id: dict[int, str]


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def html_source_found_count(html_bytes: bytes) -> int | None:
    """Read the source count from captured DOM bytes, not mutable manifest JSON.

    A missing count is not evidence of a zero-sized listview. For a capped
    single-ilvl parent we must have this independent denominator to certify
    its quality partition.
    """
    markup = html_bytes.decode('utf-8', errors='replace')
    visible = unescape(re.sub(r'<[^>]+>', ' ', markup))
    match = re.search(r'([\d,]+)\s+items?\s+found', visible, re.IGNORECASE)
    return int(match.group(1).replace(',', '')) if match else None


def verify_html_found_count(html_bytes: bytes, recorded: int | None, *,
                            required: bool = False, prefix: str = 'CAPTURE_INTEGRITY_') -> None:
    """Bind journal counts to captured DOM, with a fail-closed required mode."""
    observed = html_source_found_count(html_bytes)
    if observed is not None and observed != recorded:
        raise ValueError(prefix + 'SOURCE_FOUND_COUNT_MISMATCH')
    if required and observed is None:
        raise ValueError(prefix + 'SOURCE_FOUND_COUNT_UNATTESTED')


def _error(reason: str) -> ValueError:
    return ValueError('CAPTURE_INTEGRITY_' + reason)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool):
        raise _error('INVALID_INTEGER')
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _error('INVALID_INTEGER') from exc
    if result < 0:
        raise _error('NEGATIVE_INTEGER')
    return result


def verify_class_capture(capture_dir: Path, class_key: str) -> VerifiedClassCapture:
    """Check leaf coverage, source URLs, local evidence hashes, and row identity.

    The required seed bands are explicit and versioned in wowhead_queries.
    Split leaves are accepted only when their non-overlapping union is exactly
    those seeds. This rejects a single apparently successful page that leaves
    other legal item-level ranges entirely unqueried.
    """
    capture_dir = Path(capture_dir)
    query = CANONICAL_CLASS_QUERIES[class_key]
    manifest_bytes = (capture_dir / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('classes') != [class_key] or not manifest.get('captured_at'):
        raise _error('CLASS_OR_TIMESTAMP')
    required_bands = bands_for_class(class_key)
    seed_bands = [list(pair) for pair in required_bands]
    if manifest.get('seed_bands') != seed_bands:
        raise _error('SEED_BANDS_INCOMPLETE')
    attempts = manifest.get('attempts')
    leaves = manifest.get('leaves')
    if not isinstance(attempts, list) or not isinstance(leaves, list) or not leaves:
        raise _error('NO_TERMINAL_LEAVES')
    if any(not a.get('accepted') for a in attempts):
        raise _error('FAILED_ATTEMPT')
    terminals = [a for a in attempts if not a.get('needs_split')]
    # Compare complete objects, not only their interval endpoints: a failed or
    # silently omitted terminal attempt must never disappear from the manifest.
    norm = lambda a: json.dumps(a, sort_keys=True, separators=(',', ':'))
    if sorted(map(norm, terminals)) != sorted(map(norm, leaves)):
        raise _error('LEAF_ATTEMPT_MISMATCH')

    # Replay the actual split tree, including capped parents. A terminal leaf
    # alone is not evidence that a parent query was exhausted.
    queue = [(lo, hi, None) for lo, hi in required_bands]
    expected_leaves = []
    source_rows = {}
    for attempt in attempts:
        if not queue:
            raise _error('EXTRA_ATTEMPT')
        lo, hi, quality = queue.pop(0)
        if (attempt.get('min_item_level'), attempt.get('max_item_level'),
                attempt.get('quality')) != (lo, hi, quality):
            if (quality is None and attempt.get('quality') is None
                    and (attempt.get('min_item_level'), attempt.get('max_item_level')) in required_bands):
                raise _error('SEED_RANGE_GAP_OR_OVERLAP')
            raise _error('SPLIT_TREE_ORDER_OR_FILTER_MISMATCH')
        if (attempt.get('class_key') != class_key or attempt.get('class_id') != query.class_id
                or attempt.get('url') != build_search_url(query, lo, hi, quality=quality)):
            raise _error('WRONG_CLASS_FILTER_OR_URL')
        if attempt.get('http_status') != 200 or attempt.get('blocked_marker') or not attempt.get('accepted'):
            raise _error('BAD_HTTP_OR_BLOCKED')
        for key in ('html_file', 'listview_file'):
            filename = attempt.get(key)
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise _error('MISSING_OR_UNSAFE_EVIDENCE_FILE')
        html_bytes = (capture_dir / attempt['html_file']).read_bytes()
        rows_bytes = (capture_dir / attempt['listview_file']).read_bytes()
        if _digest(html_bytes) != attempt.get('html_sha256'):
            raise _error('HTML_HASH_MISMATCH')
        if (attempt.get('found_count') is not None and
                _positive_int(attempt['found_count']) > 0 and
                _positive_int(attempt.get('listview_rows')) == 0):
            raise _error('POSITIVE_FOUND_BUT_EMPTY_LISTVIEW')
        verify_html_found_count(html_bytes, attempt.get('found_count'),
                                required=(lo == hi and quality is None and bool(attempt.get('needs_split'))))
        if _digest(rows_bytes) != attempt.get('listview_sha256'):
            raise _error('LISTVIEW_HASH_MISMATCH')
        rows = json.loads(rows_bytes)
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise _error('INVALID_LISTVIEW_ROWS')
        try:
            ids = {int(r['id']) for r in rows}
        except (KeyError, TypeError, ValueError) as exc:
            raise _error('INVALID_ITEM_ID') from exc
        if (len(rows) != _positive_int(attempt.get('listview_rows'))
                or len(ids) != _positive_int(attempt.get('listview_unique_ids'))):
            raise _error('LISTVIEW_COUNT_MISMATCH')
        if quality is not None and any(
                r.get('quality') is not None and int(r['quality']) != quality for r in rows):
            raise _error('QUALITY_ROW_MISMATCH')
        source_rows[(lo, hi, quality)] = (attempt, rows, ids)
        if attempt.get('needs_split'):
            if lo == hi and quality is None and attempt.get('found_count') is None:
                raise _error('QUALITY_PARENT_COUNT_REQUIRED')
            try:
                queue[0:0] = child_capture_coordinates(lo, hi, quality)
            except ValueError as exc:
                raise _error('UNSPLITTABLE_QUALITY') from exc
        else:
            if len(ids) >= 1000 or attempt.get('unsplittable_capped'):
                raise _error('TRUNCATED_1000_IDS')
            found, displayed = attempt.get('found_count'), attempt.get('displayed_count')
            if found is not None and _positive_int(found) > 0 and not rows:
                raise _error('POSITIVE_FOUND_BUT_EMPTY_LISTVIEW')
            if displayed is not None and _positive_int(displayed) > 0 and not rows:
                raise _error('POSITIVE_DISPLAY_BUT_EMPTY_LISTVIEW')
            if found is not None and _positive_int(found) != len(ids):
                raise _error('TRUNCATED_OR_INCONSISTENT_FOUND_COUNT')
            if displayed is not None and _positive_int(displayed) != len(rows):
                raise _error('TRUNCATED_OR_INCONSISTENT_DISPLAY_COUNT')
            expected_leaves.append(attempt)
    if queue:
        raise _error('SEED_RANGE_GAP_OR_OVERLAP')
    if sorted(map(norm, expected_leaves)) != sorted(map(norm, leaves)):
        raise _error('LEAF_ATTEMPT_MISMATCH')

    # Every single-ilvl quality split must account for the original parent's
    # entire reported cardinality. Parent row IDs must also be present in the
    # union; quality siblings must be pairwise disjoint.
    for (lo, hi, quality), (attempt, parent_rows, parent_ids) in source_rows.items():
        if quality is not None or lo != hi or not attempt.get('needs_split'):
            continue
        child_ids = set()
        for q in WOWHEAD_QUALITY_VALUES:
            child = source_rows.get((lo, hi, q))
            if child is None or child[0].get('needs_split'):
                raise _error('QUALITY_PARTITION_INCOMPLETE')
            overlap = child_ids.intersection(child[2])
            if overlap:
                raise _error('QUALITY_OVERLAP')
            child_ids.update(child[2])
        if (len(child_ids) != _positive_int(attempt['found_count'])
                or not parent_ids.issubset(child_ids)):
            raise _error('QUALITY_COUNT_MISMATCH')

    interval_leaves: dict[tuple[int, int], list[dict[str, Any]]] = {}
    merged: list[dict[str, Any]] = []
    provenance: dict[int, str] = {}
    for leaf in leaves:
        lo, hi = _positive_int(leaf.get('min_item_level')), _positive_int(leaf.get('max_item_level'))
        if lo > hi:
            raise _error('OVERLAPPING_OR_INVALID_LEAF')
        interval_leaves.setdefault((lo, hi), []).append(leaf)
        rows = source_rows[(lo, hi, leaf.get('quality'))][1]
        base = canonical_base_rows(rows)
        for iid, row in base.items():
            if int(row.get('level') or -1) not in range(lo, hi + 1):
                raise _error('ITEM_OUTSIDE_CAPTURED_BAND')
            if iid in provenance:
                raise _error('DUPLICATE_ITEM_ACROSS_LEAVES')
            provenance[iid] = leaf['url']
        merged.extend(rows)
    for (lo, hi), group in interval_leaves.items():
        qualities = [a.get('quality') for a in group]
        if qualities != [None] and (lo != hi or sorted(qualities) != list(WOWHEAD_QUALITY_VALUES)):
            raise _error('QUALITY_PARTITION_INCOMPLETE')
    for seed_lo, seed_hi in required_bands:
        pieces = sorted((lo, hi) for lo, hi in interval_leaves if seed_lo <= lo <= hi <= seed_hi)
        cursor = seed_lo
        for lo, hi in pieces:
            if lo != cursor:
                raise _error('SEED_RANGE_GAP_OR_OVERLAP')
            cursor = hi + 1
        if cursor != seed_hi + 1:
            raise _error('SEED_RANGE_GAP_OR_OVERLAP')
    if any(not any(a <= lo <= hi <= b for a, b in required_bands) for lo, hi in interval_leaves):
        raise _error('OUTSIDE_SEED_BANDS')

    merged_bytes = (capture_dir / f'{class_key}_merged.listview.json').read_bytes()
    if json.loads(merged_bytes) != merged:
        raise _error('MERGED_ROWS_DIFFER_FROM_LEAVES')
    bases = canonical_base_rows(merged)
    if set(bases) != set(provenance):
        raise _error('MERGED_BASE_MEMBERSHIP_MISMATCH')
    return VerifiedClassCapture(class_key, query.class_id, str(manifest['captured_at']),
                                bases, len(leaves), _digest(manifest_bytes),
                                _digest(merged_bytes), provenance)


def verify_class_item_export(source_path: Path, class_key: str) -> dict[int, str]:
    """Validate an offline export's full class-filtered band partition.

    Export verification is weaker than raw browser capture because a JSON
    export cannot independently prove its upstream HTTP response. The explicit
    source and per-page digest remain provenance, not proof of loot possession.
    """
    data = json.loads(Path(source_path).read_text(encoding='utf-8'))
    query = CANONICAL_CLASS_QUERIES[class_key]
    if (data.get('schema') != 'forever_class_item_listview_v1'
            or data.get('class_id') != query.class_id):
        raise _error('WRONG_CLASS_OR_EXPORT_SCHEMA')
    if not data.get('complete_pages') or not data.get('captured_at'):
        raise _error('UNVERIFIED_EXPORT_COMPLETENESS')
    pages = data.get('pages')
    if not isinstance(pages, list) or not pages:
        raise _error('MISSING_EXPORT_PAGES')
    coverage = set()
    ids: dict[int, str] = {}
    for page in pages:
        lo, hi = _positive_int(page.get('min_item_level')), _positive_int(page.get('max_item_level'))
        if lo > hi or (lo, hi) in coverage:
            raise _error('DUPLICATE_EXPORT_BAND')
        coverage.add((lo, hi))
        if (page.get('source_url') != build_search_url(query, lo, hi)
                or page.get('fetch_status') != 'verified_listview'
                or page.get('http_status') != 200):
            raise _error('INVALID_EXPORT_SOURCE_PROVENANCE')
        item_ids = page.get('item_ids')
        if not isinstance(item_ids, list) or any(not isinstance(i, int) or isinstance(i, bool) or i <= 0 for i in item_ids):
            raise _error('INVALID_EXPORT_ITEM_IDS')
        digest = _digest(json.dumps(item_ids, separators=(',', ':')).encode())
        if digest != page.get('item_ids_sha256') or page.get('unique_item_count') != len(item_ids):
            raise _error('EXPORT_COUNT_OR_HASH_MISMATCH')
        for iid in item_ids:
            if iid in ids:
                raise _error('DUPLICATE_EXPORT_ITEM_ID')
            ids[iid] = page['source_url']
    # Unlike an untrusted boolean complete_pages, this proves every planned
    # source query has a corresponding page record. Split captures should use
    # the raw adaptive manifest verifier instead.
    if coverage != set(bands_for_class(class_key)):
        raise _error('EXPORT_BAND_GAP_OR_OVERLAP')
    if data.get('total_rows') != len(ids):
        raise _error('EXPORT_TOTAL_COUNT_MISMATCH')
    return ids

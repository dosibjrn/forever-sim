"""Source-matched VERIFIED_DETAIL acquisition requires real current detail HTML.

These are deterministic contract tests. They neither claim a player trained a
spell nor certify production P1 or source database completeness.
"""
from hashlib import sha256
import json

import pytest

from src.game.data.forever.source_checkpoint_acquisition import (
    _resolve_matching_acquisition_evidence,
)


def _row():
    return dict(batch_id="batch-current",source_url="https://source.invalid/spell",
        level_hint=30,raw_listview_json='{"id":740,"name":"Tranquility"}')


def _evidence():
    row=_row()
    return dict(index_batch_id=row['batch_id'],source_url=row['source_url'],
        required_level_hint=row['level_hint'],
        source_payload_sha256=sha256(row['raw_listview_json'].encode()).hexdigest(),
        detail_html_sha256='detailhash',snapshot_sha='detailhash',
        details_verified=1,batch_status='complete',
        evidence_status='VERIFIED_DETAIL_METHOD_OBSERVATION_NOT_WORLD_ACCESS',
        methods_observed_json=json.dumps({"taught_by_npc":1}))


def test_complete_matching_detail_snapshot_is_eligible_for_method_evidence():
    status,methods=_resolve_matching_acquisition_evidence(_evidence(),_row())
    assert status=='VERIFIED_DETAIL_METHOD_OBSERVATION_NOT_WORLD_ACCESS'
    assert methods=={'taught_by_npc':1}


@pytest.mark.parametrize('missing',('detail_html_sha256','snapshot_sha'))
def test_verified_detail_without_actual_snapshot_is_stale(missing):
    ev=_evidence();ev[missing]=None
    assert _resolve_matching_acquisition_evidence(ev,_row())==(
        'STALE_DETAIL_ACQUISITION_EVIDENCE',{})


@pytest.mark.parametrize('field,value',[
    ('snapshot_sha','other'),
    ('details_verified',0),
    ('batch_status','incomplete'),
])
def test_detail_snapshot_or_batch_mismatch_fails_closed(field,value):
    ev=_evidence();ev[field]=value
    assert _resolve_matching_acquisition_evidence(ev,_row())==(
        'STALE_DETAIL_ACQUISITION_EVIDENCE',{})


@pytest.mark.parametrize('field,value',[
    ('index_batch_id','different-batch'),
    ('source_url','https://other.invalid'),
    ('required_level_hint',25),
    ('source_payload_sha256','corrupt'),
])
def test_index_identity_mismatch_cannot_reuse_old_detail(field,value):
    ev=_evidence();ev[field]=value
    assert _resolve_matching_acquisition_evidence(ev,_row())==(
        'STALE_INDEX_ACQUISITION_EVIDENCE',{})


def test_malformed_method_evidence_fails_instead_of_legalizing_spell():
    ev=_evidence();ev['methods_observed_json']='[]'
    with pytest.raises(ValueError,match='INVALID_ACQUISITION_METHOD_EVIDENCE'):
        _resolve_matching_acquisition_evidence(ev,_row())


def test_non_detail_hints_not_converted_into_verified_detail():
    ev=_evidence()
    ev.update(evidence_status='INDEX_HINTS_ONLY_NO_ACQUISITION_PROOF',
              detail_html_sha256=None,snapshot_sha=None,
              details_verified=None,batch_status=None)
    status,methods=_resolve_matching_acquisition_evidence(ev,_row())
    assert status=='INDEX_HINTS_ONLY_NO_ACQUISITION_PROOF'
    assert methods=={'taught_by_npc':1}
    # P1 may use methods as diagnostics, but not grant LEGAL from this label.

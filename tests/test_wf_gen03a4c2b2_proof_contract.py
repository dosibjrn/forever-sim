import sqlite3
from pathlib import Path
import pytest
from src.v2.source_sqlite_semantic_proof import (
    REQUIRED_DIMENSIONS, InvalidProofEvidence, evaluate_semantic_proof, evaluate_verified_spell,
)
from src.v2.source_sqlite_semantic_audit import audit_verified_spell

DB = Path(__file__).resolve().parents[1] / 'data/forever/catalogue/forever_abilities.sqlite'
BATCH = '20261008T145657Z'


def test_all_twenty_real_snapshots_blocked():
    with sqlite3.connect(DB) as con:
        ids = [row[0] for row in con.execute('select spell_id from spell_detail_snapshots')]
    assert len(ids) == 20
    for spell_id in ids:
        result = evaluate_verified_spell(DB, batch_id=BATCH, spell_id=spell_id)
        assert len(result['dimension_status']) == len(REQUIRED_DIMENSIONS)
        assert len(result['blocking_reasons']) >= len(REQUIRED_DIMENSIONS)
        assert result['executable_effects'] == []
        assert result['ir_promotion_allowed'] is False


def test_evidence_source_mismatch_fails():
    audit = audit_verified_spell(DB, batch_id=BATCH, spell_id=116)
    for patch in ({'spell_id': 999}, {'html_sha256': 'bad'}):
        packet = {'spell_id': 116, 'html_sha256': audit['source']['html_sha256'], 'independent_verifier': 'test'}
        packet.update(patch)
        with pytest.raises(InvalidProofEvidence):
            evaluate_semantic_proof(audit, packet)


def test_all_dimension_claims_do_not_overrule_audit_or_end_to_end():
    audit = audit_verified_spell(DB, batch_id=BATCH, spell_id=116)
    packet = {'spell_id': 116, 'html_sha256': audit['source']['html_sha256'],
              'independent_verifier': 'external-test-oracle',
              'dimensions': {key: {'status': 'PASS', 'evidence_ref': f'tests/{key}.json'} for key in REQUIRED_DIMENSIONS}}
    result = evaluate_semantic_proof(audit, packet)
    assert all(x == 'EVIDENCED' for x in result['dimension_status'].values())
    assert 'UNRESOLVED_SOURCE_AUDIT_BLOCKERS' in result['blocking_reasons']
    assert not result['ir_promotion_allowed'] and not result['independent_reproduction_verified']


@pytest.mark.parametrize('bad', [True, 'PASS', {'status': 'PASS'}, {'status': 'PASS', 'evidence_ref': ''}])
def test_unsubstantiated_claim_not_evidence(bad):
    audit = audit_verified_spell(DB, batch_id=BATCH, spell_id=116)
    packet = {'spell_id': 116, 'html_sha256': audit['source']['html_sha256'],
              'independent_verifier': 'test', 'dimensions': {'targeting': bad}}
    assert evaluate_semantic_proof(audit, packet)['dimension_status']['targeting'] == 'MISSING_OR_UNPROVEN'


def test_reject_extra_dimension_and_promoted_audit():
    audit = audit_verified_spell(DB, batch_id=BATCH, spell_id=116)
    packet = {'spell_id': 116, 'html_sha256': audit['source']['html_sha256'],
              'independent_verifier': 'test', 'dimensions': {'magic': {'status':'PASS', 'evidence_ref':'x'}}}
    with pytest.raises(InvalidProofEvidence):
        evaluate_semantic_proof(audit, packet)
    audit['ir_promotion_allowed'] = True
    with pytest.raises(InvalidProofEvidence):
        evaluate_semantic_proof(audit)

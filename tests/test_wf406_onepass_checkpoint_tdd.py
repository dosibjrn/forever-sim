from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest

from src.game.checkpoint_onepass import (
    inspect_certificate, run_preflight, all_checkpoint_identities,
    verify_search_comparison, OnePassError,
)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_148_checkpoint_register_has_no_duplicates():
    cases = all_checkpoint_identities()
    assert len(cases) == len(set(cases)) == 148
    assert cases[:3] == ('druid:L20:unrestricted', 'druid:L30:unrestricted', 'mage:L30:unrestricted')


def test_forged_pass_without_actual_evidence_is_rejected(tmp_path):
    cert = {'gate':'P1','checkpoint':'druid:L20:unrestricted','status':'PASS',
            'context_sha256':_sha(b'context'), 'evidence_file':'missing.json',
            'evidence_sha256':_sha(b'FAKE')}
    assert inspect_certificate(cert, tmp_path, expected_gate='P1',
                               checkpoint=cert['checkpoint'],context_sha256=_sha(b'context'))['status'] == 'STALE'


def test_valid_evidence_is_fresh_but_never_assumed_semantically_passed(tmp_path):
    (tmp_path/'source.json').write_text('{"proof":"only-a-document"}')
    cert={'gate':'P2','checkpoint':'mage:L30:unrestricted','status':'PASS',
          'context_sha256':_sha(b'context'),'evidence_file':'source.json',
          'evidence_sha256':_sha((tmp_path/'source.json').read_bytes()),
          'gate_verifier_id':'wf362_p2'}
    res=inspect_certificate(cert,tmp_path,expected_gate='P2',
               checkpoint='mage:L30:unrestricted',context_sha256=_sha(b'context'))
    assert res['status']=='FRESH_EVIDENCE_NOT_SEMANTICALLY_VERIFIED'
    (tmp_path/'source.json').write_text('CHANGED')
    assert inspect_certificate(cert,tmp_path,expected_gate='P2',
               checkpoint='mage:L30:unrestricted',context_sha256=_sha(b'context'))['status']=='STALE'


def test_p5_finite_full_frontier_and_p6_p7_fail_closed():
    result = verify_search_comparison({'P4':{'unique':21,'wall_s':16.9,'100mob':100,'s_per_mob':18.9049},
        'P5':{'unique':216,'wall_s':76.0,'100mob':100,'s_per_mob':18.9049},
        'P6':{'T30':18.9049,'T300':18.9049,'same_context':True,'independent':True},
        'P7':{'new_s_per_mob':18.9049,'legacy_s_per_mob':19.0,'same_context':True,
              'legacy_candidate_replayed':True,'old_as_seed':False}})
    assert result == {'P4': True,'P5': True,'P6': True,'P7':True}
    with pytest.raises(OnePassError,match='P5_NOT_10X'):
        verify_search_comparison({'P4':{'unique':21,'wall_s':16.9,'100mob':100,'s_per_mob':18.9},
          'P5':{'unique':45,'wall_s':75,'100mob':100,'s_per_mob':18.8}})
    with pytest.raises(OnePassError,match='P7_LEGACY_WINS'):
        verify_search_comparison({'P4':{'unique':21,'wall_s':16,'100mob':100,'s_per_mob':18.9},
          'P5':{'unique':210,'wall_s':75,'100mob':100,'s_per_mob':18.9},
          'P6':{'T30':18.9,'T300':18.9,'same_context':True,'independent':True},
          'P7':{'new_s_per_mob':18.9,'legacy_s_per_mob':18.0,'same_context':True,
                'legacy_candidate_replayed':True,'old_as_seed':False}})


def test_actual_p3_failure_blocks_promotion_and_expensive_runs(tmp_path):
    from src.rulesets.forever.items.runtime_selection import _DEFAULT_DB
    d=run_preflight('druid:L20:unrestricted', item_db=_DEFAULT_DB,
                    certificate_dir=tmp_path, execute_expensive=False)
    assert d['gate_status']['P3']=='NEEDS_CONTEXTUAL_TOP5_ILVL_SMOKE'
    assert d['accepted'] is False
    assert d['next_action'].startswith('P3:')
    assert d['gate_status']['P4'] == 'BLOCKED_BY_P3_SMOKE_NOT_RUN'
    assert d['source_item_verified'] is False

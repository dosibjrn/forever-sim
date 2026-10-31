"""Gate-level RED -> GREEN -> REFACTOR protocol: fail closed across all 7."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest
from src.game.checkpoint_gate_cycle import (
    GateCycleError, GATES, validate_cycle, validate_gate_ledger,
)

H='1'*64
C='druid:L30:unrestricted'


def evidence(gate='P1',phase='COMPLETE'):
    criterion=f'{gate}_SOURCE_SCOPE_ACCEPTANCE'
    red={'outcome':'FAIL','criterion_id':criterion,'test_id':f'{gate}_REAL_ACCEPTANCE',
         'evidence_sha256':'2'*64}
    green={'outcome':'PASS','criterion_id':criterion,'test_id':f'{gate}_REAL_ACCEPTANCE',
           'evidence_sha256':'3'*64,'gate_certificate_ref':f'evidence/{gate}/certificate.json'}
    refactor={'genericity_reviewed':True,'class_specific_changes':[],
              'criterion_id':criterion,'post_refactor_gate_status':'PASS',
              'post_refactor_evidence_sha256':'4'*64,
              'cross_context_regressions':[{'checkpoint':'mage:L30:unrestricted',
                  'status':'PASS','evidence_sha256':'5'*64}]}
    out={'gate':gate,'phase':phase,'checkpoint':C,'source_sha256':H,
         'criterion_id':criterion}
    if phase in ('RED','GREEN','REFACTOR','COMPLETE'):out['red']=red
    if phase in ('GREEN','REFACTOR','COMPLETE'):out['green']=green
    if phase in ('REFACTOR','COMPLETE'):out['refactor']=refactor
    return out


@pytest.mark.parametrize('gate',GATES)
def test_real_seven_gates_each_have_complete_lifecycle(gate):
    assert validate_cycle(evidence(gate),checkpoint=C,source_sha256=H)=='COMPLETE'


def test_p3_red_is_a_first_class_nonpassing_state():
    result=validate_gate_ledger({'checkpoint':C,'source_sha256':H,'gates':[evidence('P3','RED')]})
    assert result['gate_phases']['P3']=='RED'
    assert not result['process_evidence_complete']
    assert not result['checkpoint_accepted']


def test_all_seven_cycle_complete_is_still_not_semantic_acceptance():
    records=[evidence(gate) for gate in GATES]
    result=validate_gate_ledger({'checkpoint':C,'source_sha256':H,'gates':records})
    assert result['cycle_structure_complete'] and not result['process_evidence_complete']
    assert not result['checkpoint_accepted']


@pytest.mark.parametrize('mutation',[
    lambda x:x.pop('red'),
    lambda x:x['red'].update(outcome='PASS'),
    lambda x:x['green'].update(criterion_id='P1_CHANGED'),
    lambda x:x['green'].update(test_id='DIFFERENT_TEST'),
    lambda x:x['green'].pop('gate_certificate_ref'),
    lambda x:x['refactor'].update(genericity_reviewed=False),
    lambda x:x['refactor'].update(post_refactor_gate_status='FAIL'),
    lambda x:x['refactor'].update(criterion_id='P1_DIFFERENT'),
    lambda x:x['refactor'].update(cross_context_regressions=[]),
    lambda x:x['refactor']['cross_context_regressions'][0].update(checkpoint=C),
    lambda x:x.update(source_sha256='6'*64),
    lambda x:x['refactor'].update(class_specific_changes=[{'file':'src/game/foo.py',
         'disposition':'LEFT_CLASS_HARDCODE','rationale':'Not yet refactored'}]),
])
def test_complete_gate_fails_closed_for_fake_or_unreviewed_evidence(mutation):
    x=evidence();mutation(x)
    with pytest.raises(GateCycleError):
        validate_cycle(x,checkpoint=C,source_sha256=H)


def test_resolved_class_specific_code_requires_traceable_disposition():
    x=evidence()
    x['refactor']['class_specific_changes']=[{'file':'src/v2/foo.py',
        'disposition':'MOVED_TO_SOURCE_DATA',
        'rationale':'Spell rank belongs to canonical source facts'}]
    assert validate_cycle(x,checkpoint=C,source_sha256=H)=='COMPLETE'


def test_green_without_review_is_not_complete():
    x=evidence(phase='GREEN')
    assert validate_cycle(x,checkpoint=C,source_sha256=H)=='GREEN'
    x['phase']='COMPLETE'
    with pytest.raises(GateCycleError,match='REFACTOR_REVIEW_MISSING'):
        validate_cycle(x,checkpoint=C,source_sha256=H)


def test_duplicate_gate_does_not_inflate_coverage():
    with pytest.raises(GateCycleError,match='DUPLICATE_GATE'):
        validate_gate_ledger({'checkpoint':C,'source_sha256':H,
                              'gates':[evidence(),deepcopy(evidence())]})


def test_source_context_change_does_not_reuse_prior_green():
    with pytest.raises(GateCycleError,match='SOURCE_CHANGED'):
        validate_cycle(evidence(),checkpoint=C,source_sha256='9'*64)


def _with_files(records, tmp_path):
    names={'red':'red.json','green':'green.json','refactor':'refactor.json','cross':'cross.json'}
    for name,file in names.items():
        data=(name+' real bytes').encode()
        (tmp_path/file).write_bytes(data)
    shas={k:sha256((tmp_path/v).read_bytes()).hexdigest() for k,v in names.items()}
    for r in records:
        for phase in ('red','green'):
            r[phase]['evidence_file']=names[phase]
            r[phase]['evidence_sha256']=shas[phase]
        post=r['refactor']
        post['post_refactor_evidence_file']=names['refactor']
        post['post_refactor_evidence_sha256']=shas['refactor']
        for item in post['cross_context_regressions']:
            item['evidence_file']=names['cross']
            item['evidence_sha256']=shas['cross']
    return shas


def test_formal_complete_ledger_requires_actual_evidence_sha256(tmp_path):
    records=[evidence(g) for g in GATES]
    _with_files(records,tmp_path)
    audit=validate_gate_ledger({'checkpoint':C,'source_sha256':H,'gates':records},
                               project_root=tmp_path)
    assert audit['cycle_structure_complete']
    assert audit['evidence_sha256_verified']
    assert audit['process_evidence_complete']
    assert not audit['checkpoint_accepted']  # Verifier is not a gameplay oracle.
    (tmp_path/'red.json').write_bytes(b'maliciously changed')
    with pytest.raises(GateCycleError,match='EVIDENCE_BYTES_SHA_MISMATCH'):
        validate_gate_ledger({'checkpoint':C,'source_sha256':H,'gates':records},
                             project_root=tmp_path)


def test_evidence_path_cannot_escape_project(tmp_path):
    records=[evidence('P1')]
    _with_files(records,tmp_path)
    records[0]['red']['evidence_file']='../outside.json'
    with pytest.raises(GateCycleError,match='EVIDENCE_PATH_ESCAPES_PROJECT'):
        validate_gate_ledger({'checkpoint':C,'source_sha256':H,'gates':records},
                             project_root=tmp_path)


def test_real_wf402_p3_red_is_verified_from_canonical_evidence():
    root=Path(__file__).resolve().parents[1]
    import json
    ledger=json.loads((root/'evidence/wf403/GATE_CYCLE_EXAMPLE.json').read_text())
    audit=validate_gate_ledger(ledger,project_root=root)
    assert audit['gate_phases']['P3']=='RED'
    assert audit['evidence_sha256_verified']
    assert not audit['process_evidence_complete']

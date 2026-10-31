"""Strict 30s blind optimizer contract: never label known best as global optimum."""
import json
from pathlib import Path
import tempfile
import pytest
from tools.wf299_30s_acceptance import run
from tools.wf299_30s_worker import fresh_replay


def test_deadline_must_be_at_most_30_seconds():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError, match='within 30'):
            run(class_key='druid', level=20,output=Path(d)/'out.json',deadline_s=31)


def test_worker_is_killed_and_evidence_deleted_if_it_exceeds_budget():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'evidence.json'
        p.write_text('fake cached success')
        result=run(class_key='druid',level=20,output=p,deadline_s=1.0)
        assert result['status']=='FAIL_30_SECOND_DEADLINE'
        assert result['accepted_checkpoint'] is False
        assert not p.exists()


def test_source_worker_does_not_import_a_legacy_oracle_module():
    p=Path(__file__).resolve().parents[1]/'tools/wf299_30s_worker.py'
    text=p.read_text()
    for forbidden in ('frozen_heldout', 'wf282_source_role_heldout_benchmark',
                      'wf298_druid_l20_verified_delta', 'fixtures/wf243',
                      'tools.wf297_druid_l20_checkpoint'):
        assert forbidden not in text


def test_evidence_structure_keeps_known_best_separate_from_certified_optimum():
    p=Path(__file__).resolve().parents[1]/'WF299_30S_ACCEPTANCE.json'
    if not p.exists():pytest.skip('acceptance evidence not included in working extract')
    result=json.loads(p.read_text())
    assert result['status']=='PASS_BLIND_30S_REPRODUCIBLE_MODEL_BENCHMARK'
    assert result['actual_wall_s']<30
    assert result['search_oracle_seeded'] is False
    assert result['global_optimum_proven'] is False
    assert result['accepted_checkpoint'] is False
    assert result['score_s_per_mob']==result['scratch_replay']['score_s_per_mob']

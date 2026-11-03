"""The user's six empirical ports, not a held-out global optimum gate."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import pytest
from src.game.checkpoint_acceptance_status import accepted_checkpoint_status
from tools.m1_progress import FIELDS, GATES

ROOT=Path(__file__).resolve().parents[2]


def test_fresh_same_source_empirical_acceptance_supersedes_extra_gate():
    r=accepted_checkpoint_status(ROOT)
    # This is historical P1-P6 evidence, never a current P1-P7.5 PASS.
    assert r['accepted_checkpoints']=='0/148'
    assert not r['full_checkpoint_certified']
    assert r['full_checkpoint_authority']=='CANONICAL_M1_LEDGER_COMPATIBLE_P1_P7_5'
    assert r['legacy_six_gate_accepted_checkpoints']=='2/148'
    assert r['legacy_six_gate_druid_l30']=='PASS'
    assert not r['heldout_global_optimality_proven']
    p=json.loads((ROOT/'evidence/wf367/WF367_ACCEPTANCE.json').read_text())
    assert p['heldout_challenger']['actual_s_per_mob']<p['ports']['P4']['actual_s_per_mob']
    assert p['ports']['P6']['T30']<=1.01*p['ports']['P6']['T300']


def test_invalid_p6_cannot_promote(tmp_path):
    (tmp_path/'evidence/wf360').mkdir(parents=True)
    (tmp_path/'evidence/wf367').mkdir(parents=True)
    for name in ('WF360_ACCEPTANCE.json',):
        (tmp_path/'evidence/wf360'/name).write_bytes((ROOT/'evidence/wf360'/name).read_bytes())
    p=json.loads((ROOT/'evidence/wf367/WF367_ACCEPTANCE.json').read_text())
    p['ports']['P6']['T30']=1.02*p['ports']['P6']['T300']
    (tmp_path/'evidence/wf367/WF367_ACCEPTANCE.json').write_text(json.dumps(p))
    with pytest.raises(ValueError,match='INVALID_WF367'):
        accepted_checkpoint_status(tmp_path)


def test_wf360_historical_pass_never_certifies_full_p7(tmp_path):
    target=tmp_path/'evidence/wf360'
    target.mkdir(parents=True)
    target.joinpath('WF360_ACCEPTANCE.json').write_bytes(
        (ROOT/'evidence/wf360/WF360_ACCEPTANCE.json').read_bytes())
    r=accepted_checkpoint_status(tmp_path)
    assert r['legacy_six_gate_accepted_checkpoints']=='2/148'
    assert r['accepted_checkpoints']=='0/148'
    assert not r['full_checkpoint_certified']


def test_wf365_revocation_keeps_six_gate_and_full_counts_separate(tmp_path):
    for wf,name in (('wf360','WF360_ACCEPTANCE.json'),
                    ('wf365','WF365_DRUID_L30_REVOCATION.json')):
        target=tmp_path/'evidence'/wf
        target.mkdir(parents=True)
        target.joinpath(name).write_bytes((ROOT/'evidence'/wf/name).read_bytes())
    r=accepted_checkpoint_status(tmp_path)
    assert r['legacy_six_gate_accepted_checkpoints']=='1/148'
    assert r['legacy_six_gate_druid_l30']=='REVOKED'
    assert r['accepted_checkpoints']=='0/148'
    assert not r['full_checkpoint_certified']


def test_canonical_m1_ledger_is_only_full_checkpoint_authority(tmp_path):
    """Eleven compatible live PASS stamps count; incompatible stamps do not."""
    source = ROOT / 'evidence/wf360/WF360_ACCEPTANCE.json'
    evidence = tmp_path / 'evidence/wf360'
    evidence.mkdir(parents=True)
    (evidence / source.name).write_bytes(source.read_bytes())

    ledger = tmp_path / 'docs/planning/M1_PASSES.tsv'
    ledger.parent.mkdir(parents=True)
    stamp = '2026-11-03T00:00:00+00:00'
    rows = [
        {'class': 'druid', 'level': '20', 'spec': 'unrestricted',
         'gate': gate, 'passed_at_utc': stamp, 'commit': 'a' * 40,
         'run_url': '', 'compatibility_id': 'same-native-scenario-source',
         'status': 'PASS', 'verified': '', 'applicable': '',
         'scope_provisional': '', 'measured_at_utc': stamp}
        for gate in GATES
    ]

    def save():
        with ledger.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter='\\t')
            writer.writeheader()
            writer.writerows(rows)

    save()
    accepted = accepted_checkpoint_status(tmp_path)
    assert accepted['accepted_checkpoints'] == '1/148'
    assert accepted['full_checkpoint_certified'] is True
    assert accepted['legacy_six_gate_accepted_checkpoints'] == '2/148'

    rows[-1]['compatibility_id'] = 'different-source-or-engine'
    save()
    incompatible = accepted_checkpoint_status(tmp_path)
    assert incompatible['accepted_checkpoints'] == '0/148'
    assert incompatible['full_checkpoint_certified'] is False
    assert incompatible['legacy_six_gate_accepted_checkpoints'] == '2/148'

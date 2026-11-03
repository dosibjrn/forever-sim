"""Report current M1 checkpoint status alongside separate historical pre-v2.20 facts.

WF360/WF365/WF367 are legacy six-gate evidence, not current certification.
Only the canonical Merge-owned M1 register can supply full checkpoint counts.
This reader never awards a gate PASS or changes the register.
"""
from __future__ import annotations
import json
from pathlib import Path


def _legacy_six_gate_status(root: Path) -> dict:
    original=json.loads((root/'evidence/wf360/WF360_ACCEPTANCE.json').read_text())
    # A later *six-gate* rerun supersedes historical acceptance/revocation.
    # A faster held-out build is useful evidence of search weakness, but is
    # NOT a seventh gate: P6 tests T30 <= 1.01*T300, not global optimality.
    current=root/'evidence/wf367/WF367_ACCEPTANCE.json'
    if current.is_file():
        audit=json.loads(current.read_text())
        p=audit.get('ports',{})
        if (audit.get('checkpoint')!='druid:L30:unrestricted'
                or any(p.get('P'+str(i),{}).get('status')!='PASS' for i in range(1,7))
                or p['P4']['wall_s']>30. or p['P5']['wall_s']>300.
                or p['P5']['unique']<=p['P4']['unique']
                or any(p[k]['covered']!=p[k]['legal'] or p[k]['legal']<=0
                       for k in ('P1','P2','P3'))
                or p['P3']['slots']<1
                or not audit.get('source_db_sha256')
                or p['P4']['actual_s_per_mob']<=0 or p['P5']['actual_s_per_mob']<=0
                or abs(p['P6']['T30']-p['P4']['actual_s_per_mob'])>1e-8
                or abs(p['P6']['T300']-p['P5']['actual_s_per_mob'])>1e-8
                or p['P6']['T30']>1.01*p['P6']['T300']):
            raise ValueError('INVALID_WF367_SIX_GATE_ACCEPTANCE')
        return {'accepted_checkpoints':'2/148','druid_l30':'PASS',
                'authority':'WF367 current-source six-gate rerun',
                'source_db_sha256':audit['source_db_sha256'],
                'heldout_global_optimality_proven':False}
    revocation_path=root/'evidence/wf365/WF365_DRUID_L30_REVOCATION.json'
    if not revocation_path.exists():
        return {'accepted_checkpoints':original['accepted_checkpoints'],
                'druid_l30':original['ports']['P6']['status'],
                'authority':'WF360 historical, no later revocation present'}
    audit=json.loads(revocation_path.read_text())
    compare=audit.get('comparison') or {}
    if (audit.get('checkpoint')!='druid:L30:unrestricted'
            or audit.get('L30_status')!='REVOKED'
            or compare.get('falsified') is not True
            or compare.get('same_source') is not True
            or compare.get('same_recovery') is not True
            or compare.get('same_100_mob_objective') is not True):
        raise ValueError('INVALID_DRUID_L30_REVOCATION_EVIDENCE')
    return {'accepted_checkpoints':'1/148','druid_l30':'REVOKED',
            'authority':'WF365 100-mob same-source heldout replay',
            'source_db_sha256':audit['source_db_sha256']}


def accepted_checkpoint_status(root: Path) -> dict:
    """Read the canonical live M1 count, retaining separately labeled legacy facts.

    An empty or absent ledger means zero certified checkpoints. Even 11 PASS
    rows do not certify a checkpoint unless their compatibility IDs agree;
    tools.m1_progress.scoreboard owns that predicate. No gate is run here.
    """
    from tools.m1_progress import scoreboard

    root = Path(root)
    legacy = _legacy_six_gate_status(root)
    current = scoreboard(root / "docs/planning/M1_PASSES.tsv")
    certified = current["certified_checkpoints"]
    return {
        "accepted_checkpoints": f"{certified}/{current['total_checkpoints']}",
        "full_checkpoint_certified": certified > 0,
        "full_checkpoint_authority": "CANONICAL_M1_LEDGER_COMPATIBLE_P3_P7_5",
        "legacy_six_gate_accepted_checkpoints": legacy["accepted_checkpoints"],
        "legacy_six_gate_druid_l30": legacy["druid_l30"],
        "legacy_six_gate_authority": legacy["authority"],
        **{key: value for key, value in legacy.items()
           if key not in ("accepted_checkpoints", "druid_l30", "authority")},
    }

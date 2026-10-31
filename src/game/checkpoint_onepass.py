"""Strict checkpoint preflight and evidence reuse across the 148 validation cases.

The currently available legal item universe is used for the approved fast
P3 ilvl-Top5 score smoke; full external catalogue attestation is advisory.  A file/hash-matching
historical certificate is only fresh evidence, NOT a semantic PASS.  Only the
native semantic verifiers may promote a checkpoint; this preflight deliberately
cannot do that.  The preflight exists to avoid wasting hours on guaranteed
failures and to make a single-turn workflow feasible once source/data exist.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Mapping
import math
import time

from src.game.checkpoint_gate_cycle import GATES
from src.rulesets.forever.items.wowhead_queries import CANONICAL_CLASS_QUERIES
from src.rulesets.forever.items.runtime_selection import source_class_item_membership_verified


class OnePassError(ValueError):
    """A measured or evidence-backed acceptance condition failed."""


# The order and expected labels are data-only reporting configuration, not
# optimizer conditions. Forever mechanics, talents and legality stay in SQLite.
CHECKPOINT_REGISTRY_FILE = Path(__file__).resolve().parents[2] / 'config' / 'validation' / 'checkpoint_148.json'


def _reporting_registry() -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    import json
    doc = json.loads(CHECKPOINT_REGISTRY_FILE.read_text(encoding='utf-8'))
    names = tuple(doc['class_order'])
    specs = {key: tuple(value) for key, value in doc['spec_profiles'].items()}
    if set(specs) != set(names) or len(names) != 9 or len(set(names)) != 9:
        raise OnePassError('INVALID_REPORTING_CLASS_REGISTRY')
    if set(names) != set(CANONICAL_CLASS_QUERIES):
        raise OnePassError('CHECKPOINT_CLASS_SET_MISMATCH')
    if sum(len(value) for value in specs.values()) != 28:
        raise OnePassError('SPEC_REPORTING_PROFILE_COUNT_MISMATCH')
    return names, specs


def all_checkpoint_identities() -> tuple[str, ...]:
    """Full 36 unrestricted + 112 spec-constrained, in the requested priority."""
    classes, specs = _reporting_registry()
    rest_l30 = tuple(c for c in classes if c not in ('druid', 'mage', 'hunter', 'shaman'))
    order = [('druid',20),('druid',30),('mage',30),('hunter',30),('shaman',30)]
    order += [(c,30) for c in rest_l30]
    order += [(c,20) for c in classes if c != 'druid']
    order += [(c,40) for c in classes]
    order += [(c,60) for c in classes]
    unrestricted = [f'{c}:L{level}:unrestricted' for c,level in order]
    constrained = [f'{c}:L{level}:{spec}' for level in (20,30,40,60)
                   for c in classes for spec in specs[c]]
    all_cases = tuple(unrestricted + constrained)
    if len(all_cases) != len(set(all_cases)) or len(all_cases) != 148:
        raise OnePassError('CHECKPOINT_REGISTER_NOT_148_UNIQUE')
    return all_cases


def _hash_path(path: Path) -> str:
    h=sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect_certificate(cert: Mapping, root: Path, *, expected_gate: str,
                        checkpoint: str, context_sha256: str) -> dict:
    """Validate a cached evidence *reference*, not its gameplay truth.

    A caller cannot claim PASS by providing a syntactically green JSON file.
    The actual P1..P7 semantic verifier must be run independently.
    """
    try:
        if cert.get('gate') != expected_gate or cert.get('checkpoint') != checkpoint:
            raise OnePassError('IDENTITY_MISMATCH')
        if cert.get('context_sha256') != context_sha256 or cert.get('status') != 'PASS':
            raise OnePassError('CONTEXT_CHANGED_OR_NOT_PASS')
        if not isinstance(cert.get('gate_verifier_id'), str) or not cert['gate_verifier_id']:
            raise OnePassError('NO_GATE_VERIFIER')
        name=cert.get('evidence_file')
        if not isinstance(name,str) or not name.strip():
            raise OnePassError('MISSING_EVIDENCE_FILE')
        root=Path(root).resolve()
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise OnePassError('EVIDENCE_MISSING_OR_ESCAPES_ROOT')
        if _hash_path(path) != cert.get('evidence_sha256'):
            raise OnePassError('EVIDENCE_CHANGED')
    except (OnePassError, OSError, AttributeError):
        return {'status':'STALE', 'semantic_pass':False}
    return {'status':'FRESH_EVIDENCE_NOT_SEMANTICALLY_VERIFIED',
            'semantic_pass':False,'gate_verifier_id':cert['gate_verifier_id']}


def _positive(row: Mapping, key: str) -> float:
    v=row.get(key)
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
        raise OnePassError(f'INVALID_{key.upper()}')
    return float(v)


def verify_search_comparison(measured: Mapping) -> dict[str, bool]:
    """Independently check P4..P7 *numerical* predicates on measured metadata.

    This only validates arithmetic and declared replay provenance: it DOES NOT
    certify that recorded runs occurred or used complete Forever game facts.
    Runtime/raw-evidence authenticity is a separate prerequisite for PASS.
    """
    p4=measured['P4']; p5=measured['P5']
    if _positive(p4,'wall_s')>30 or _positive(p4,'100mob')!=100 or _positive(p4,'unique')<1:
        raise OnePassError('P4_BUDGET_OR_100MOB_FAIL')
    _positive(p4,'s_per_mob')
    if _positive(p5,'wall_s')>300 or _positive(p5,'100mob')!=100 or _positive(p5,'unique')<1:
        raise OnePassError('P5_BUDGET_OR_100MOB_FAIL')
    _positive(p5,'s_per_mob')
    if p5['unique'] < 10*p4['unique']:
        raise OnePassError('P5_NOT_10X')
    status={'P4':True,'P5':True}
    if 'P6' in measured:
        p6=measured['P6']
        if p6.get('same_context') is not True or p6.get('independent') is not True:
            raise OnePassError('P6_CONTEXT_OR_REPLAY_INVALID')
        t30=_positive(p6,'T30');t300=_positive(p6,'T300')
        if abs(t30-p4['s_per_mob'])>1e-8 or abs(t300-p5['s_per_mob'])>1e-8:
            raise OnePassError('P6_REPLAY_DIFFERS_FROM_SEARCH')
        if t30>1.01*t300:
            raise OnePassError('P6_SATURATION_FAIL')
        status['P6']=True
    if 'P7' in measured:
        p7=measured['P7']
        if 'P6' not in status or p7.get('same_context') is not True or p7.get('legacy_candidate_replayed') is not True or p7.get('old_as_seed') is not False:
            raise OnePassError('P7_LEGACY_PARITY_OR_SEED_INVALID')
        new=_positive(p7,'new_s_per_mob'); old=_positive(p7,'legacy_s_per_mob')
        if abs(new-measured['P6']['T30'])>1e-8:
            raise OnePassError('P7_NEW_WINNER_NOT_REPLAYED')
        if new>old+1e-9:
            raise OnePassError('P7_LEGACY_WINS')
        status['P7']=True
    return status


def run_preflight(checkpoint: str, *, item_db: Path, certificate_dir: Path,
                  execute_expensive: bool = False) -> dict:
    """Run cheap trustworthy preconditions; never promote an unverified gate.

    `execute_expensive` is reserved for the real semantic P4/P5 executor.  It
    cannot override a failed P3; this routine must not fake long-run searches.
    """
    start=time.monotonic()
    if checkpoint not in all_checkpoint_identities():
        raise OnePassError('UNKNOWN_CHECKPOINT')
    class_key=checkpoint.split(':',1)[0]
    item_db=Path(item_db)
    if not item_db.is_file():
        raise OnePassError('SOURCE_ITEM_DB_NOT_FOUND')
    item_hash=_hash_path(item_db)
    source_ok=source_class_item_membership_verified(class_key,item_db)
    statuses={gate:'NEEDS_SEMANTIC_VALIDATOR' for gate in GATES}
    statuses['P3']='NEEDS_CONTEXTUAL_TOP5_ILVL_SMOKE'
    cert_dir=Path(certificate_dir)
    existing={}
    for gate in GATES:
        p=cert_dir/f'{gate}.json'
        if p.is_file():
            import json
            try:
                existing[gate]=inspect_certificate(json.loads(p.read_text()),cert_dir,
                          expected_gate=gate,checkpoint=checkpoint,context_sha256=item_hash)
            except (ValueError,OSError):
                existing[gate]={'status':'STALE','semantic_pass':False}
    # This cheap preflight has no source-bound build weights or APL, so it
    # cannot execute the semantic P3 smoke or certify downstream searches.
    for gate in ('P4','P5','P6','P7'):
        statuses[gate]='BLOCKED_BY_P3_SMOKE_NOT_RUN'
    # No P1/P2/other automatic acceptance just because a historical JSON exists.
    result={'checkpoint':checkpoint,'accepted':False,'source_item_verified':source_ok,
            'source_item_db_sha256':item_hash,'gate_status':statuses,
            'certificate_evidence':existing,'expensive_search_launched':False,
            'wall_s':round(time.monotonic()-start,6),
            'next_action':('P3: evaluate up to five highest-ilvl legal items per slot with source-context '
                           'nonnegative meaningful stat weights; full capture is not required')}
    if execute_expensive:
        result['refused_expensive_search']='P3_SMOKE_NOT_EXECUTED'
    return result

"""Crash-survivable paid joint-search evidence, NOT a checkpoint certificate.

The journal is intentionally append-in-the-logical-sense but atomically
replaced on disk. An external SIGKILL or OS timeout cannot turn a completed
100mob trial into a missing output file. The digest detects torn or accidentally
edited evidence, not a trusted upstream source signature.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Mapping

from src.rulesets.forever.items.runtime_selection import catalogue_path


def _canonical_bytes(data: Mapping) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False, default=str).encode('utf-8')


def search_context_sha256(*, class_key, level, source_ir, seed_stage, options) -> str:
    """Bind the journal to input GameIR, seed, and the *complete* search contract."""
    item_catalogue=Path(catalogue_path())
    # The shared gear proposal generator reads this DB outside GameIR. If
    # its bytes change, old paid evidence must not be treated as same-context.
    item_catalogue_sha256=sha256(item_catalogue.read_bytes()).hexdigest()
    return sha256(_canonical_bytes({'class_key':class_key, 'level':level,
        'source_ir':str(source_ir),'source_seed':seed_stage,
        'item_catalogue_sha256':item_catalogue_sha256,
        'search_options':options})).hexdigest()


class PaidJointProgressJournal:
    def __init__(self, path: Path, *, context_sha256: str, resume: bool = False):
        self.path=Path(path)
        temporary=self.path.with_suffix(self.path.suffix+'.tmp')
        if temporary.exists():
            raise FileExistsError('REFUSE_UNRESOLVED_PAID_JOINT_TEMPORARY_FILE')
        self.recovered=None
        if resume:
            self.recovered=load_verified_joint_progress(self.path,
                expected_context_sha256=context_sha256)
            if self.recovered['status']!='IN_PROGRESS_NOT_CERTIFIED':
                raise ValueError('SOURCE_JOINT_PROGRESS_NOT_RESUMABLE')
            if self.recovered['phase'] not in ('PREPARED','SCREENING',
                                              'SURVIVAL_QUALIFICATION','FULL_FINALISTS'):
                raise ValueError('SOURCE_JOINT_PROGRESS_UNKNOWN_RESUME_PHASE')
        elif self.path.exists():
            raise FileExistsError('REFUSE_OVERWRITE_EXISTING_PAID_JOINT_PROGRESS')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.context_sha256=context_sha256
        self.sequence=int(self.recovered['sequence']) if self.recovered else 0

    def write(self, *, status, phase, attempted, completed, events,
              full_evaluated_candidates, elapsed_wall_s, phase_wall_s=None):
        self.sequence+=1
        ranked=sorted(completed,key=lambda row:(float(row['seconds_per_mob']),
            str(row.get('allocation')),str(row.get('gear_move')),
            str(row.get('policy')),str(row.get('recovery'))))
        record={
            'journal_version':1,
            'status':status,
            'phase':phase,
            'context_sha256':self.context_sha256,
            'sequence':self.sequence,
            'wall_s_at_snapshot':elapsed_wall_s,
            'phase_wall_s':phase_wall_s or {},
            'paid_candidates':len(attempted),
            'full_evaluated_candidates':full_evaluated_candidates,
            'complete_100mob_candidates':len(completed),
            'winner':ranked[0] if ranked else None,
            'rows':attempted,
            'events':events,
            # A source-proxy candidate completion never establishes a class-item
            # source attestation, a global optimum, or a checkpoint acceptance.
            'source_legal_gear_universe_verified':False,
            'global_optimum_proven':False,
            'eligible_for_checkpoint_acceptance':False,
        }
        envelope={'payload':record,'payload_sha256':sha256(_canonical_bytes(record)).hexdigest()}
        contents=_canonical_bytes(envelope)
        temp=self.path.with_suffix(self.path.suffix+'.tmp')
        try:
            with temp.open('xb') as stream:
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp,self.path)
        finally:
            temp.unlink(missing_ok=True)


def load_verified_joint_progress(path: Path, *, expected_context_sha256: str | None = None) -> dict:
    try:
        envelope=json.loads(Path(path).read_bytes())
        payload=envelope['payload']
        actual=sha256(_canonical_bytes(payload)).hexdigest()
        if envelope['payload_sha256']!=actual or payload['journal_version']!=1:
            raise ValueError('invalid journal content')
        if expected_context_sha256 is not None and payload['context_sha256'] != expected_context_sha256:
            raise ValueError('mismatched input context')
        if payload['eligible_for_checkpoint_acceptance'] is not False:
            raise ValueError('unsafe checkpoint evidence')
        if payload['source_legal_gear_universe_verified'] is not False:
            raise ValueError('unsafe source evidence')
        if payload['complete_100mob_candidates']!=sum(
                row.get('status')=='COMPLETE' and row.get('mobs')==100
                for row in payload['rows']):
            raise ValueError('inconsistent 100mob accounting')
        if payload['winner'] is not None and payload['winner'].get('status')!='COMPLETE':
            raise ValueError('invalid winner')
        return payload
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ValueError('SOURCE_JOINT_PROGRESS_INTEGRITY: '+str(exc)) from exc

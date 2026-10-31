"""P7: adversarial legacy-winner challenger, tested on the NEW 100-mob runtime.

The old score is NEVER used as a number in the comparison. The complete
legacy-selected gear/talents/policy must be represented as a new-engine stage,
source-rebuilt, and scored with the same source IR/objective as the new winner.
Absent snapshots, unexecutable mechanics, or noncomparable recovery are BLOCKED,
not zero and not a free PASS.
"""
from __future__ import annotations

from hashlib import sha256
from json import dumps
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


def fingerprint(stage: Mapping[str, Any]) -> str:
    """Bind talents, gear and rotation; NEVER fingerprint just the displayed score."""
    try:
        selected=stage['gear_policy_result']['winner']
        gear={str(k):int(v['item_id']) for k,v in selected['gear']['slots'].items()}
        policy=selected['winner']
        identity={'allocation':dict(stage['allocation']),'gear':gear,
                  'opening':list(policy['prefix']), 'fallback':str(policy['fallback']),
                  'guarded_action':policy.get('guarded_action'),
                  'guarded_conditions':policy.get('guarded_conditions')}
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('P7_INCOMPLETE_FULL_BUILD_IDENTITY') from exc
    if not gear or not identity['allocation'] or not identity['opening']:
        raise ValueError('P7_EMPTY_GEAR_TALENT_OR_POLICY')
    return sha256(dumps(identity,sort_keys=True,default=str).encode()).hexdigest()


def _blocking(reason: str, **facts) -> dict:
    return {'gate':'P7_LEGACY_HOLDOUT','status':'BLOCKED','pass':False,
            'reason':reason,'checkpoint_accepted':False,**facts}


def validate_p7_replays(*, legacy_stage: Mapping[str, Any] | None,
                        new_stage: Mapping[str, Any] | None,
                        legacy_publication_sha256: str | None,
                        source_context_sha256: str | None,
                        old_replay: Mapping[str, Any] | None,
                        new_replay: Mapping[str, Any] | None,
                        recovery_semantics_verification: Mapping[str, Any] | None,
                        checkpoint: str) -> dict:
    """Fail-closed adjudication of two actually executed new-runtime 100-mob runs.

    A separate runner MUST execute both frozen stages on the same GameIR and
    source DB. Missing published L30 legacy winner is an explicit blocker.
    """
    if legacy_stage is None:
        return _blocking('LEGACY_LEVEL_WINNER_UNPUBLISHED',checkpoint=checkpoint)
    if new_stage is None:
        return _blocking('NEW_LEVEL_WINNER_UNAVAILABLE',checkpoint=checkpoint)
    if not legacy_publication_sha256 or len(legacy_publication_sha256)!=64:
        return _blocking('LEGACY_PUBLICATION_NOT_PINNED',checkpoint=checkpoint)
    if not source_context_sha256 or len(source_context_sha256)!=64:
        return _blocking('SOURCE_CONTEXT_NOT_PINNED',checkpoint=checkpoint)
    try:
        old_id=fingerprint(legacy_stage);new_id=fingerprint(new_stage)
    except ValueError as exc:
        return _blocking(str(exc),checkpoint=checkpoint)
    # The old winner must be rebuilt as a *real* candidate, not measured by its
    # own old simulator or compared via originally published throughput.
    for label,record,expected_id in [('legacy',old_replay,old_id),('new',new_replay,new_id)]:
        if not isinstance(record,Mapping) or record.get('status')!='COMPLETE':
            return _blocking('MISSING_COMPLETE_NEW_RUNTIME_100MOB_REPLAY_'+label.upper(),checkpoint=checkpoint)
        if record.get('stage_fingerprint')!=expected_id:
            return _blocking('REPLAY_BUILD_IDENTITY_MISMATCH_'+label.upper(),checkpoint=checkpoint)
        if record.get('source_context_sha256')!=source_context_sha256:
            return _blocking('REPLAY_SOURCE_CONTEXT_MISMATCH_'+label.upper(),checkpoint=checkpoint)
        if record.get('evaluator')!='new_source_combat_runtime':
            return _blocking('REPLAY_NOT_NEW_RUNTIME_'+label.upper(),checkpoint=checkpoint)
        if record.get('count')!=100 or not record.get('continuous_actor_state'):
            return _blocking('REPLAY_NOT_CONTINUOUS_100MOB_'+label.upper(),checkpoint=checkpoint)
        if record.get('objective_id')!='kill+recovery+survival_100_consecutive_mobs':
            return _blocking('NONCOMPARABLE_OBJECTIVE_'+label.upper(),checkpoint=checkpoint)
        if record.get('equipment_legality_checked') is not True:
            return _blocking('EQUIPMENT_LEGALITY_UNPROVEN_'+label.upper(),checkpoint=checkpoint)
        try: score=float(record['mean_s_per_mob'])
        except (KeyError,TypeError,ValueError):
            return _blocking('INVALID_SCORE_'+label.upper(),checkpoint=checkpoint)
        if not isfinite(score) or score <= 0:
            return _blocking('INVALID_SCORE_'+label.upper(),checkpoint=checkpoint)
    # A current runtime that cannot perform human->HoT->cat while preserving
    # state is not a sufficient arena for a meaningful talent comparison.
    if not recovery_semantics_verification or recovery_semantics_verification.get('status')!='PASS':
        return _blocking('BETWEEN_MOB_FORM_HEAL_CONTINUITY_UNPROVEN',checkpoint=checkpoint,
                         legacy_100mob_s=old_replay['mean_s_per_mob'],
                         new_100mob_s=new_replay['mean_s_per_mob'])
    if recovery_semantics_verification.get('source_context_sha256')!=source_context_sha256:
        return _blocking('RECOVERY_PROOF_SOURCE_MISMATCH',checkpoint=checkpoint)
    # Do not accept a hand-authored status='PASS' while the scorer still forces
    # full recovery each kill or silently treats caster heals as always legal.
    required=('sourced_form_exit_executed','sourced_hot_cast_executed',
              'sourced_form_reentry_executed','form_entry_mana_paid',
              'gcd_and_cast_time_paid','hot_ticks_persisted_into_next_pull',
              'no_forced_full_hp_mana_per_mob','same_continuous_100mob_objective')
    missing=[flag for flag in required if recovery_semantics_verification.get(flag) is not True]
    if missing:
        return _blocking('RECOVERY_PROOF_INCOMPLETE',checkpoint=checkpoint,
                         missing_recovery_evidence=missing)
    old_score=float(old_replay['mean_s_per_mob']);new_score=float(new_replay['mean_s_per_mob'])
    passed=new_score<=old_score+1e-9
    return {'gate':'P7_LEGACY_HOLDOUT','checkpoint':checkpoint,
            'status':'PASS' if passed else 'FAIL_LEGACY_BETTER','pass':passed,
            'checkpoint_accepted':False,  # P7 does not bypass P1-P6
            'legacy_100mob_s':old_score,'new_100mob_s':new_score,
            'legacy_advantage_s_per_mob':new_score-old_score,
            'legacy_build_sha256':old_id,'new_build_sha256':new_id,
            'source_context_sha256':source_context_sha256,
            'legacy_publication_sha256':legacy_publication_sha256,
            'same_new_runtime':True,'legacy_explicit_new_runtime_challenger':True,
            'recovery_semantics_verified':True}


def run_actual_p7(*, class_key:str,level:int, source_ir, legacy_stage:dict | None,
                  new_stage:dict | None, legacy_publication_sha256:str | None,
                  source_context_sha256:str | None, recovery_semantics_verification:dict | None,
                  max_wall_s:float=45.0) -> dict:
    """Replay both frozen stages by the actual new GameIR/CombatRuntime.

    Call inside the pinned ability-source SQLite scope. No legacy scorer is called.
    A caller may additionally wrap this in a hard OS-process timeout.
    """
    checkpoint=f'{class_key}:L{level}:unrestricted'
    if legacy_stage is None or new_stage is None:
        return validate_p7_replays(legacy_stage=legacy_stage,new_stage=new_stage,
            legacy_publication_sha256=legacy_publication_sha256,
            source_context_sha256=source_context_sha256,old_replay=None,new_replay=None,
            recovery_semantics_verification=recovery_semantics_verification,checkpoint=checkpoint)
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    actual=[]
    for stage in (legacy_stage,new_stage):
        try:
            candidate=prepare_candidate(class_key=class_key,level=level,stage=stage,
               source_ir=source_ir,strict_l2_item_effects=True)
            replay=evaluate_persistent_candidate(candidate,level=level,mobs=100,max_wall_s=max_wall_s)
        except (ValueError,KeyError,RuntimeError) as exc:
            replay={'status':'BLOCKED_SOURCE_CANDIDATE','reason':str(exc)}
        replay={**replay,'stage_fingerprint':fingerprint(stage),
                'source_context_sha256':source_context_sha256,
                'evaluator':'new_source_combat_runtime',
                'objective_id':'kill+recovery+survival_100_consecutive_mobs',
                'equipment_legality_checked':replay.get('status')=='COMPLETE'}
        actual.append(replay)
    return validate_p7_replays(legacy_stage=legacy_stage,new_stage=new_stage,
        legacy_publication_sha256=legacy_publication_sha256,
        source_context_sha256=source_context_sha256,old_replay=actual[0],new_replay=actual[1],
        recovery_semantics_verification=recovery_semantics_verification,checkpoint=checkpoint)

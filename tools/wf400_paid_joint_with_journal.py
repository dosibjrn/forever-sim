"""Repeatable real 100mob four-axis search with durable interim evidence.

Works with any sourced class/level/GameIR and valid seed stage. The atomic
progress JSON is safe to inspect after a caller's process is forcibly stopped.
It is NOT an acceptance certificate and does NOT constitute a source item
membership attestation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from hashlib import sha256

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (search_bounded_joint_frontier,
    source_cold_start_stage, joint_screen_budget_fraction)
from src.v2.source_joint_progress import load_verified_joint_progress


def _source_seed_and_hash(*, class_key, level, source_ir, seed_stage, cold_start_gear_role):
    """One deterministic stage identity for new and resumed paid searches."""
    if (seed_stage is None)==(cold_start_gear_role is None):
        raise ValueError('REQUIRE_EXACTLY_ONE_SOURCE_SEED_OR_COLD_START')
    if cold_start_gear_role is not None:
        stage=source_cold_start_stage(class_key=class_key,level=level,
            source_ir=source_ir,gear_role=cold_start_gear_role)
        return stage,sha256(json.dumps(stage,sort_keys=True).encode()).hexdigest()
    path=Path(seed_stage)
    return json.loads(path.read_text()),sha256(path.read_bytes()).hexdigest()

def run(*,class_key,level,ability_db,seed_stage,output,progress,
        budget_s,pack_size,max_talents,max_gear_moves,max_policies,
        max_recovery_policies,max_paid_builds,max_finalists,per_candidate_s,
        qualification_mobs=None,max_qualifiers=12,proposal_strategy="diagonal",resume=False,talented=True,
        cold_start_gear_role=None,screen_budget_fraction=None):
    if Path(output).exists():
        raise FileExistsError('REFUSE_OVERWRITE_PAID_JOINT_RESULT')
    ir=build_game_ir_slice(class_key=class_key,level=level,
        ability_db_path=Path(ability_db))
    stage,stage_hash=_source_seed_and_hash(class_key=class_key,level=level,
        source_ir=ir,seed_stage=seed_stage,cold_start_gear_role=cold_start_gear_role)
    result=search_bounded_joint_frontier(class_key=class_key,level=level,
        source_ir=ir,seed_stage=stage, max_cpu_s=budget_s,
        bonus_talent_points=None if talented else 0,
        max_talents=max_talents,max_gear_moves=max_gear_moves,
        max_policies=max_policies,max_recovery_policies=max_recovery_policies,
        max_paid_builds=max_paid_builds,per_candidate_wall_s=per_candidate_s,
        screen_then_finalists=True,max_finalists=max_finalists,
        pack_size=pack_size,progress_path=Path(progress),resume_progress=resume,
        qualification_mobs=qualification_mobs,max_qualifiers=max_qualifiers,
        proposal_strategy=proposal_strategy,screen_budget_fraction=screen_budget_fraction)
    durable=load_verified_joint_progress(progress)
    if durable['paid_candidates']!=result['paid_candidates'] or durable['status']!='FINISHED_NOT_CERTIFIED':
        raise AssertionError('PAID_SEARCH_RESULT_JOURNAL_DIVERGENCE')
    result.update(screen_budget_fraction=joint_screen_budget_fraction(
        qualification_mobs=qualification_mobs,override=screen_budget_fraction),
        journal_path=str(progress),journal_context_sha256=durable['context_sha256'],
        source_input_sha256=sha256(Path(ability_db).read_bytes()).hexdigest(),
        seed_stage_sha256=stage_hash,
        seed_origin=stage.get('paid_candidate_origin','EXPLICIT_SOURCE_STAGE'))
    p=Path(output)
    if p.exists():raise FileExistsError('REFUSE_OVERWRITE_PAID_JOINT_RESULT')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,sort_keys=True,default=str))
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--class-key',required=True)
    ap.add_argument('--level',type=int,required=True)
    ap.add_argument('--ability-db',type=Path,required=True)
    source=ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--seed-stage',type=Path)
    source.add_argument('--cold-start-gear-role',type=str)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--progress',type=Path,required=True)
    ap.add_argument('--resume',action='store_true',help='Resume exact matching unfinished paid journal')
    ap.add_argument('--talented',action=argparse.BooleanOptionalAction,default=True,
        help='Legacy Talented 5/5 points enabled (default), --no-talented for standard L10-start budget')
    ap.add_argument('--budget-s',type=float,default=30.)
    ap.add_argument('--pack-size',type=int,default=2)
    ap.add_argument('--max-talents',type=int,default=16)
    ap.add_argument('--max-gear-moves',type=int,default=4)
    ap.add_argument('--max-policies',type=int,default=12)
    ap.add_argument('--max-recovery-policies',type=int,default=3)
    ap.add_argument('--max-paid-builds',type=int,default=120)
    ap.add_argument('--max-finalists',type=int,default=4)
    ap.add_argument('--per-candidate-s',type=float,default=7.)
    ap.add_argument('--qualification-mobs',type=int,default=None)
    ap.add_argument('--max-qualifiers',type=int,default=12)
    ap.add_argument('--proposal-strategy',choices=('diagonal','marginal_screen'),default='diagonal')
    ap.add_argument('--screen-budget-fraction',type=float,default=None)
    args=ap.parse_args()
    result=run(**vars(args))
    print(json.dumps({k:result[k] for k in ('status','paid_candidates',
        'complete_100mob_candidates','wall_s','winner','eligible_for_checkpoint_acceptance')},
        indent=2,default=str))

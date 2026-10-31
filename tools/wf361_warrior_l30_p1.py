"""Warrior L30 P1 sourced frontier, using the existing generic P1 and GameIR.

No combat engine or class ability table is introduced here. External spellbook
is an explicit, versioned data snapshot; L0 proxy gaps fail closed.
"""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_checkpoint_p1_acceptance import CheckpointP1,evaluate_p1,l0_ranked_source_candidates,l0_paid_action_priority
from src.v2.source_budgeted_prefix import source_prefix_envelope

ROOT=Path(__file__).resolve().parents[1]
SPELLBOOK=ROOT/'evidence/wf361/warrior_spellbook_70338_level1_30.json'

def run():
    os.environ['WOW_FOREVER_BUILD_AS_OF']='2026-10-14'
    cp=CheckpointP1('warrior',30,use_runes=False)
    ir=build_game_ir_slice(class_key=cp.class_key,level=cp.level,ability_db_path=DEFAULT_DB,use_runes=cp.use_runes)
    if ir is None:
        raise ValueError('WARRIOR_L30_NO_SOURCE_GAME_IR')
    frontier=action_frontier(ir,class_key=cp.class_key,level=cp.level,db_path=DEFAULT_DB,use_runes=cp.use_runes)
    p1=evaluate_p1(frontier,DEFAULT_DB,cp,ir=ir,spellbook_path=SPELLBOOK)
    ranked=l0_ranked_source_candidates(p1)
    order=l0_paid_action_priority(p1)
    before=source_prefix_envelope(ir,level=cp.level)
    after=source_prefix_envelope(ir,level=cp.level,l0_action_priority=order)
    if set(before['actions'])!=set(after['actions']):
        raise AssertionError('L0_PRIORITIZATION_MUTATED_LEGAL_ACTIONS')
    if sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True).execute('PRAGMA integrity_check').fetchone()[0]!='ok':
        raise AssertionError('CANONICAL_SQLITE_INTEGRITY')
    p1['l0_source_candidate_ranking']=ranked
    p1['l0_paid_action_priority']=order
    p1['ir_action_count']=len(ir.actions)
    p1['ir_mode_count']=len(ir.modes)
    p1['source_index_provisional_rank_count']=frontier['potentially_legal_positive_ranks']
    p1['source_context_role_assessed']=frontier['potential_ranks_assessed_by_numeric_ir_or_text_role']
    p1['l2_actions_before_after_identical']=True
    p1['uncertainty']='L0-only web text snapshot; no verified executable claim for missing Warrior actions'
    return p1

if __name__=='__main__':
    p1=run()
    dest=ROOT/'evidence/wf361/WF361_WARRIOR_L30_P1_CERTIFICATE.json'
    dest.write_text(json.dumps(p1,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in p1.items() if k not in ('records','l0_paid_action_priority','l0_source_candidate_ranking')},indent=2))

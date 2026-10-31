"""Reproduce Mage L30 source P1 certificate; P2 and 100mob are diagnostics only.

No game facts, optimizer or runtime implementation lives in this script.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json, sqlite3, time

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_checkpoint_p1_acceptance import (
    CheckpointP1, evaluate_p1, l0_ranked_source_candidates)
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint, evaluate_p2
from src.game.multi_pull import evaluate_repeated_pulls

ROOT=Path(__file__).resolve().parents[1]
SPELLBOOK=ROOT/'evidence/wf377/mage_spellbook_70338_level1_30.json'
OUT=ROOT/'evidence/wf377/WF377_MAGE_L30_P1_CERTIFICATE.json'


def run():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    frontier=action_frontier(ir,class_key='mage',level=30,db_path=DEFAULT_DB,use_runes=False)
    p1=evaluate_p1(frontier,DEFAULT_DB,CheckpointP1('mage',30),ir=ir,spellbook_path=SPELLBOOK)
    p1['l0_source_candidate_ranking']=l0_ranked_source_candidates(p1)
    p2=evaluate_p2(ir,P2Checkpoint('mage',30),spellbook_path=SPELLBOOK)
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    assert integrity=='ok'
    # Existing policy and canonical 100mob evaluator: quick regression only,
    # NOT a gear×talent×APL search or P4/P5/P6 acceptance.
    paid={}
    for pack in (1,2,3):
        wall=time.perf_counter();cpu=time.process_time()
        result=evaluate_repeated_pulls(ir_slice=ir,policy=ir.policies[0],level=30,
            target_health=200,count=100,pack_size=pack,
            recovery_mode='always',schedule_incoming_attacks=True)
        paid[str(pack)]={'seconds_per_mob':result.seconds_per_mob,
            'kills':sum(int(p.get('mob_count',0)) for p in result.pulls if p['pack_all_defeated']),
            'events':sum(int(p.get('event_transitions',0)) for p in result.pulls),
            'wall_s':time.perf_counter()-wall,'cpu_s':time.process_time()-cpu,
            'pulls':len(result.pulls)}
    evidence={'schema':'wf377_mage_l30_p1_evidence_v1',
        'checkpoint':{'class_key':'mage','level':30,'profile':'unrestricted','use_runes':False},
        'source_build':'1.60.1.70338','accepted_checkpoint_total':2,'target_total':148,
        'canonical_sqlite_sha256':sha256(DEFAULT_DB.read_bytes()).hexdigest(),
        'source_spellbook_sha256':sha256(SPELLBOOK.read_bytes()).hexdigest(),
        'sqlite_integrity':integrity,'p1':p1,
        'p2_diagnostic':{'p2_pass':p2['p2_pass'],
            'known_reachable_rank_count':p2['known_reachable_rank_count'],
            'l0_scored_reachable_rank_count':p2['l0_scored_reachable_rank_count'],
            'unknown_position_families':p2['unknown_position_families'],
            'blocked':p2['blocked'],
            'source_rank_mismatches':p2['source_rank_mismatches']},
        'p3':'NOT_RUN','p4':'NOT_RUN','p5':'NOT_RUN','p6':'NOT_RUN',
        'paid_100mob_diagnostic_not_acceptance':paid,
        'legacy_held_out_druid_l30':{'original_objective_legacy_s_per_mob':16.2876,
            'wf367_s_per_mob':16.6457,'different_from_mage_200hp_diagnostic':True},
        'next':'Mage L30 P2: source-stage beta 70338 talent tree identity, rows, prerequisites and all legal rank L0.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    return evidence


if __name__=='__main__':
    x=run();print(json.dumps({'p1_pass':x['p1']['PASS1'],
        'legal':x['p1']['legal'],'conditional':x['p1']['conditional'],
        'scored':x['p1']['scored_legal_or_conditional'],
        'unresolved':x['p1']['unresolved'],
        'p2_diagnostic':{'pass':x['p2_diagnostic']['p2_pass'],
            'scored':x['p2_diagnostic']['l0_scored_reachable_rank_count'],
            'unknown_talent_families':len(x['p2_diagnostic']['unknown_position_families'])},
        'paid_100mob':x['paid_100mob_diagnostic_not_acceptance']},indent=2))

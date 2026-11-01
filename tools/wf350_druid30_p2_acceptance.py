"""Measure L30 P2 from the staged canonical SQLite -> GameIR pipeline."""
from __future__ import annotations
from pathlib import Path
import json,hashlib,sqlite3
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2,evaluate_p2_allocation_l0
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf350/druid_l30_source_talent_catalogue_70338.json'
SPELL=ROOT/'evidence/wf348/druid_spellbook_70338_level1_30.json'
OUT=ROOT/'evidence/wf350/WF350_P2_ACCEPTANCE.json'

def run():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    assert len(ir.talents)==52 and 'natural_instinct' in {t.id for t in ir.talents}
    assert 'predatory_instincts' not in {t.id for t in ir.talents}
    result=evaluate_p2(ir,P2Checkpoint('druid',30),source_observations_path=OBS,spellbook_path=SPELL)
    for r in result['rank_rows']:
        evaluated=evaluate_p2_allocation_l0(result,ir,r['witness'],P2Checkpoint('druid',30))
        assert evaluated['rankable']
    with sqlite3.connect(DB) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    assert integrity=='ok'
    from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
    p3=checkpoint_item_l0(class_key='druid',level=30)
    evidence={'checkpoint':'druid:L30:unrestricted','source_build':'1.60.1.70338',
        'accepted_total':1,'target_total':148,'p1':{'pass':True,'coverage':'86/86'},
        'p2':{'pass':result['p2_pass'],'source_catalogue_identities':len(ir.talents),
            'legal_rank_witnesses':result['known_reachable_rank_count'],
            'l0_scored_legal_ranks':result['l0_scored_reachable_rank_count'],
            'source_only_l0_rank_count':result['source_only_l0_rank_count'],
            'l2_unsupported_scored_rank_count':result['l2_unsupported_scored_rank_count'],
            'blocked':result['blocked'],'unknown_positions':result['unknown_position_families'],
            'source_rank_mismatches':result['source_rank_mismatches'],
            'witnesses_replayed':len(result['rank_rows']),
            'source_rank_uncertainty':'Fan-site beta client-derived; L0 effect vectors, not full L2 runtime support'},
        'p3':{'status':'PARTIAL_NOT_ACCEPTED','legal_items':p3['legal_item_count'],
            'l0_assessed':p3['l0_assessed_count'],'uncertain_effect_items':p3['unknown_effect_item_count'],
            'nonempty_slots':len(p3['slot_frontiers']),
            'missing':'build-context finite-difference stat weights and defensible Top 5 per slot'},
        'p4':'NOT_RUN','p5':'NOT_RUN','p6':'NOT_RUN',
        'staged_sqlite_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'source_evidence_sha256':hashlib.sha256(OBS.read_bytes()).hexdigest(),
        'sqlite_integrity':integrity,
        'next':'Druid L30 unrestricted P3: legal item universe, context-specific stat weights, Top 5 per slot.'}
    OUT.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    return evidence
if __name__=='__main__':print(json.dumps(run(),indent=2))

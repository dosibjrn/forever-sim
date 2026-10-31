"""Warrior L30 unrestricted: exact source-legal P2 L0 rank and allocation audit."""
from __future__ import annotations
import hashlib,json,random,sqlite3,time
from collections import Counter
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import (P2Checkpoint,evaluate_p2,
    evaluate_p2_allocation_l0,check_structural_allocation)
from tools.wf362_stage_warrior30_talents import SOURCE,TARGET,stage
ROOT=Path(__file__).resolve().parents[1]
SPELL=ROOT/'evidence/wf361/warrior_spellbook_70338_level1_30.json'
OUT=ROOT/'evidence/wf362/WF362_WARRIOR_L30_P2_CERTIFICATE.json'

def random_legal_allocations(ir,cp,count=600,seed=362):
    rng=random.Random(seed)
    defs=list(ir.talents)
    checked=0;unique=set();hybrid=0
    for _ in range(count):
        selection={}
        for _ in range(21):
            choices=[]
            for t in defs:
                current=selection.get(t.id,0)
                if current>=t.max_rank:continue
                trial={**selection,t.id:current+1}
                try:check_structural_allocation(ir,trial,cp)
                except ValueError:continue
                choices.append(trial)
            if not choices:break
            selection=rng.choice(choices)
        check_structural_allocation(ir,selection,cp)
        key=tuple(sorted(selection.items()))
        if key in unique:continue
        unique.add(key)
        if len({next(t.tree_key for t in defs if t.id==tid) for tid in selection})>1:
            hybrid+=1
        checked+=1
        yield selection

def run():
    started=time.perf_counter();cpu=time.process_time()
    stage_result=stage()
    cp=P2Checkpoint('warrior',30)
    ir=build_game_ir_slice(class_key='warrior',level=30,ability_db_path=TARGET)
    source=json.loads(SOURCE.read_text())
    assert len(ir.talents)==52
    assert {t.id for t in ir.talents}=={r['talent_id'] for r in source['catalogue']}
    assert not {t.id for t in ir.talents}&set(source['retired_indexed_talent_ids'])
    result=evaluate_p2(ir,cp,source_observations_path=SOURCE,spellbook_path=SPELL)
    for r in result['rank_rows']:
        evaluated=evaluate_p2_allocation_l0(result,ir,r['witness'],cp)
        assert evaluated['rankable']
    randoms=list(random_legal_allocations(ir,cp))
    for selection in randoms:
        evaluation=evaluate_p2_allocation_l0(result,ir,selection,cp)
        assert evaluation['rankable']
    assert result['p2_pass'] and result['known_reachable_rank_count']==117
    assert result['l0_scored_reachable_rank_count']==117
    assert not result['blocked'] and not result['unknown_position_families']
    assert not result['source_rank_mismatches']
    assert sum(t.metadata['row']>=5 for t in ir.talents)==8
    assert {t.id for t in ir.talents if t.metadata['row']>=5}.isdisjoint(
        {r['talent_id'] for r in result['rank_rows']})
    with sqlite3.connect(TARGET) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    assert integrity=='ok'
    evidence={
        'schema':'wf362_warrior_l30_p2_acceptance_v1','parent':'WF361',
        'checkpoint':{'class_key':'warrior','level':30,'profile':'unrestricted','use_runes':False},
        'scoreboard':'2/148',
        'gates':{'P1':{'status':'PASS','scored':54,'legal':54},
                 'P2':{'status':'PASS','scored':117,'legal':117},
                 'P3':{'status':'NOT_RUN'},'P4':{'status':'NOT_RUN'},
                 'P5':{'status':'NOT_RUN'},'P6':{'status':'NOT_RUN'}},
        'source':{'url':source['source_url'],'details_url':source['source_detail_url'],
            'license':'CC BY 4.0','talent_client_build':source['talent_source_client_build'],
            'checked_against':source['talent_checked_against_build'],
            'source_sha256':stage_result['source_sha256'],
            'staged_sqlite_sha256':stage_result['staged_sqlite_sha256']},
        'p2':{'talent_families':52,'observed_reachable_families':44,
            'unreachable_families':8,'retired_stale_indexed_families':4,
            'legal_reachable_ranks':117,'l0_scored_reachable_ranks':117,
            'source_only_l0_rank_count':result['source_only_l0_rank_count'],
            'l2_unsupported_scored_rank_count':result['l2_unsupported_scored_rank_count'],
            'legal_witnesses_replayed':len(result['rank_rows']),
            'random_legal_full_allocations_replayed':len(randoms),
            'hybrid_full_allocations_replayed':sum(len({next(t.tree_key for t in ir.talents if t.id==tid)
                for tid in selection})>1 for selection in randoms),
            'tree_rank_counts':dict(Counter(r['tree_key'] for r in result['rank_rows'])),
            'context_zero_effects':sum(e.get('context_status','').startswith('ZERO_')
                for r in result['rank_rows'] for e in r['l0_effects']),
            'unknown_positions':result['unknown_position_families'],
            'blocked':result['blocked'],
            'source_rank_mismatches':result['source_rank_mismatches'],
            'uncertainty':'L0 source tooltip vectors are not calibrated s/mob and do not confer L2 runtime support; gear/stance/target/proc context remains conditional.',
            'rank_rows':result['rank_rows']},
        'timing':{'wall_s':time.perf_counter()-started,'cpu_s':time.process_time()-cpu},
        'sqlite_integrity':integrity,
        'P4_P5_P6_measurements':'NOT_RUN: wall/CPU/events/attempts/uniques/forecast/actual unavailable',
        'next':'Warrior L30 unrestricted P3: source-legal equipment universe and contextual Top 5 per slot.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n')
    return {k:v for k,v in evidence.items() if k!='p2'}|{'p2':{k:v for k,v in evidence['p2'].items() if k!='rank_rows'}}
if __name__=='__main__':print(json.dumps(run(),indent=2))

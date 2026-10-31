"""Reproduce WF328 paid mode-prefix and continuous 100-mob evidence.

The held-out prior controller winner is for COMPARISON ONLY and is never
supplied to or inspected by the optimizer. This is not a 30/300s joint run.
"""
from __future__ import annotations
import json
from pathlib import Path
from time import monotonic,process_time
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix
from src.v2.source_persistent_joint_finalists import PreparedCandidate,evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]

def replay(ir,opening,fallback):
    policy=PolicyDefinition(id='wf328-compare:'+str(fallback),
        label='Source-only L2 comparison',
        rules=(PolicyRuleDefinition(id='fallback',action_id=fallback),),
        provenance={'authority':'source_budgeted_prefix_evidence'})
    c=PreparedCandidate(ir=ir,policy=policy,opening=tuple(opening),source_stage={},allocation={})
    return evaluate_persistent_candidate(c,level=20,mobs=100,max_wall_s=15,max_total_events=100000)

def run():
    ir=build_game_ir_slice(class_key='druid',level=20)
    start=monotonic();cpu=process_time()
    search=run_source_budgeted_prefix(class_key='druid',level=20,
                                     max_evaluations=30,ir_slice=ir)
    elapsed_wall=monotonic()-start;elapsed_cpu=process_time()-cpu
    w=search['winner']
    if not w:raise AssertionError('no paid L2 winner')
    fresh=replay(ir,w['prefix'],w['fallback'])
    # One previously measured WF327/source-only winner, held out of the
    # search; legitimate replay against identical naked actor and source.
    old_ref=('moonfire:8925',),'wrath:5178'
    prior=replay(ir,*old_ref)
    if fresh['status']!='COMPLETE' or prior['status']!='COMPLETE':
        raise AssertionError('100-mob replay incomplete')
    return {'schema':'wf328_bounded_production_prefix_evidence_v1',
       'checkpoint':'druid L20 unrestricted',
       'source_state':'unmodified canonical production IR, naked actor; not WF326 geared winner',
       'fresh_paid_attempts':search['attempted'],
       'fresh_l2_evaluated':search['evaluated'],
       'fresh_l2_blocked':search['blocked'],
       'fresh_source_mode_paid_attempts':search['paid_mode_prefix_attempts'],
       'fresh_distinct_source_mode_entries':search['paid_distinct_mode_entries'],
       'fresh_mode_seed_count':search['mode_seed_count'],
       'new_l2_winner':{'opening':w['prefix'],'fallback':w['fallback'],
                        'single_mob_s_per_mob':w['score_s_per_mob']},
       'new_search_wall_s':elapsed_wall,'new_search_cpu_s':elapsed_cpu,
       'prior_wf327_paid_30_attempts_winner':{'opening':list(old_ref[0]),
            'fallback':old_ref[1],'single_mob_s_per_mob':29.837956638996886,
            'provenance':'separately re-executed the unchanged WF323 source_budgeted_prefix over same canonical IR'},
       'new_winner_persistent_100mob':fresh,
       'prior_winner_persistent_100mob':prior,
       'relative_persistent_gain_pct':100*(prior['mean_s_per_mob']-fresh['mean_s_per_mob'])/prior['mean_s_per_mob'],
       'full_build_joint_search_ran':False,'thirty_second_end_to_end_ran':False,
       'three_hundred_second_search_ran':False,'PASS4':False,'PASS5':False,'PASS6':False}

if __name__=='__main__':
    result=run()
    p=ROOT/'evidence/wf328/WF328_REAL_MODE_PREFIX_30_PAID_AND_100MOB.json'
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('new_winner_persistent_100mob','prior_winner_persistent_100mob')},indent=2))

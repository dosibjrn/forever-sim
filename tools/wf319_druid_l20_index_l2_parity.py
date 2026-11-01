"""Same-build Druid L20 L2 A/B: old baked rank numbers vs canonical index.

The old source adapter is simulated ONLY by bypassing the new rank selector,
not by changing talent/gear/policy algorithms, actor or scoring parameters.
Neither result is a source-complete checkpoint or a claim of global optimum.
"""
from __future__ import annotations
import argparse,json,os,hashlib
from pathlib import Path
from time import process_time
from src.game.data.forever import druid
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents

PARAMS=dict(class_key='druid',level=20,max_evaluations=120,
  evaluations_per_talent=40,initial_search=24,search_per_gear=24,max_gear_states=3,
  max_event_transitions=15000,policy_search_backend='stateful',
  stateful_family_budget_mode='measured_balanced',required_level_policy='observed')

def run(*,as_of='2026-10-08'):
    os.environ['WOW_FOREVER_BUILD_AS_OF']=as_of
    os.environ['WOW_FOREVER_BUILD_SOURCE']='wf319_source_index_druid_L20'
    original=druid.indexed_rank_fact
    out=[]
    try:
        for title,loader in (('previous_legacy_rank_adapter',lambda **kw:None),
                              ('canonical_index_rank_adapter',original)):
            druid.indexed_rank_fact=loader
            start=process_time()
            r=run_source_budgeted_joint_talents(**PARAMS)
            w=r.get('winner') or {}
            out.append({'mode':title,'winner_score_s_per_mob':w.get('score_s_per_mob'),
                 'winner_talents':w.get('allocation'),'attempts':r.get('attempted'),
                 'events':r.get('event_transitions'),'cpu_s':process_time()-start,
                 'full_source_provenance_accepted':False,
                 'run_status':'EVALUATED_BOUNDED'})
    finally:
        druid.indexed_rank_fact=original
    return {'schema':'WF319_Druid_L20_Canonical_Index_L2_Parity/v1','as_of':as_of,
        'same_build_and_scorer':True,'params':PARAMS,
        'canonical_ability_db_sha256':hashlib.sha256(Path(DEFAULT_DB).read_bytes()).hexdigest(),
        'compared':out,'accepted_checkpoints_before':0,'accepted_checkpoints_after':0,
        'remaining_gate':'October 9 client build differs from October 8 index; source-complete 20-L legality, all effects, gear acquisition, independent unrestricted frontier not proved'}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True)
 a=p.parse_args();result=run();Path(a.output).write_text(json.dumps(result,indent=2)+'\n');
 print(json.dumps(result['compared'],indent=2))

"""One auditable 9-class x 4-level L1 source frontier; NOT L2/checkpoints."""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import argparse,json,sqlite3
from tools.wf317_source_index_single_batch import measure as singles
from tools.wf318_nine_class_composite_batch import measure as composites
from tools.wf316_verified_full_cast_canary import audit as verified
from tools.wf292_batch_verified_source_recovery import inventory

LEVELS=(20,30,40,60)

def measure(db_path:Path)->dict:
    source=inventory(db_path,max_level=60)
    rows=[]
    for level in LEVELS:
        one=singles(db_path,level)
        multi=composites(db_path,level=level)
        details=verified(db_path,level=level)
        sets={
            'single':{tuple(x) for x in one['executed_rank_keys']},
            'multi':{(x['class_key'],x['spell_id']) for x in multi['executed']},
            'detail':{(x['class_key'],x['spell_id']) for x in details['records']
                      if x['status']=='EXECUTED_FULL_TYPED_L1_CAST_NOT_L2'},
        }
        if any(sets[a]&sets[b] for a,b in (('single','multi'),('single','detail'),('multi','detail'))):
            raise ValueError('OVERLAPPING_L1_SOURCE_EXECUTION_COUNTS')
        union=set().union(*sets.values())
        rows.append({'level':level,'nine_classes':one['classes'],
            'indexed_level_eligible':one['source_index_level_eligible_rows'],
            'source_index_single_L1':len(sets['single']),
            'source_index_composite_L1':len(sets['multi']),
            'SHA_verified_detail_whole_L1':len(sets['detail']),
            'distinct_L1_executable_rank_probes':len(union),
            'L1_only_actor_proxy_detail_casts':details['bounded_actor_proxy_casts'],
            'composite_runtime_events':multi['events'],
            'source_complete_L2':0,'validated_checkpoints':0,'validated_routes':0,
            'per_class':dict(Counter(cl for cl,_ in union)),
            'composite_blockers':multi['blocker_histogram'],
            'verified_detail_blockers':details['blockers'],
            'index_single_blockers':one['blocker_reasons'],
            'CPU_s_total_L1':round(one['CPU_s']+multi['CPU_s']+details['cpu_s'],6),
        })
    return {'schema':'wf318_four_level_source_frontier_v1','source_index_rows':source['indexed'],
        'SHA_verified_HTML_pages':source['verified_unique_pages_before'],
        'pending_unique_HTML_pages_to_L60':source['pending_unique_pages'],
        'levels':rows,'unrestricted_checkpoints_accepted':0,
        'unrestricted_checkpoint_target':36,'total_checkpoint_target':148,
        'validated_routes':0,'L1_only':True,
        'no_L2_legality_from_index_or_verified_slot_composition':True}

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=measure(a.db)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'verified_HTML':r['SHA_verified_HTML_pages'],
        'pending_HTML':r['pending_unique_HTML_pages_to_L60'],
        'levels':[{k:v for k,v in x.items() if k in ('level','distinct_L1_executable_rank_probes','source_index_single_L1','source_index_composite_L1','SHA_verified_detail_whole_L1','CPU_s_total_L1')} for x in r['levels']]},indent=2))
if __name__=='__main__':main()

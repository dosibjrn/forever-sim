"""Nine-class / all-level 1-effect source-index L1 execution coverage.

NOT a checkpoint, not inferred rank-acquisition legality. Fails all unknown
semantics with explicit status and reuses canonical atom evidence/CombatRuntime.
"""
from __future__ import annotations
import argparse,json,sqlite3
from collections import Counter
from pathlib import Path
from time import process_time
from src.game.data.forever.registry import registered_class_keys
from src.game.data.forever.source_partial_l1 import bounded_actor_l1_probe_ir
from src.game.data.forever.source_index_l1 import probe_index_single_l1


def measure(db_path:Path,level:int)->dict:
    if not 1<=level<=60:raise ValueError('LEVEL_OUT_OF_RANGE')
    started=process_time()
    classes=registered_class_keys()
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT class_key,spell_id,level_hint FROM spell_index
            WHERE kind='abilities' AND level_hint BETWEEN 1 AND ?
            ORDER BY class_key,spell_id''',(level,)).fetchall()
    by_class={};samples=[];executed_rank_keys=[];reasons=Counter();status=Counter();events=0;proxies=0
    for cl in classes:
        src=[r for r in rows if r[0]==cl]
        by_class[cl]={'source_index_rows':len(src),'L1_index_simple_executed':0,'blocked':0,
                      'actor_level_proxy':False,'events':0}
        if not src:continue
        try: ir,template,proxy=bounded_actor_l1_probe_ir(class_key=cl,level=level,db_path=db_path)
        except (ValueError,RuntimeError) as exc:
            reasons['NO_ACTOR_TEMPLATE:'+str(exc)]+=len(src);by_class[cl]['blocked']=len(src)
            continue
        by_class[cl]['actor_level_proxy']=bool(proxy)
        for _,sid,_ in src:
            try:
                row=probe_index_single_l1(ir,class_key=cl,spell_id=sid,db_path=db_path)
                by_class[cl]['L1_index_simple_executed']+=1
                by_class[cl]['events']+=row['event_count'];events+=row['event_count'];proxies+=int(proxy)
                executed_rank_keys.append([cl,int(sid)])
                if len(samples)<60:samples.append({k:v for k,v in row.items() if k!='source'})
                status['EXECUTED_SOURCE_INDEX_SINGLE_L1_NOT_L2']+=1
            except (ValueError,RuntimeError) as exc:
                why=str(exc).split(':',1)[0]
                reasons[why]+=1;by_class[cl]['blocked']+=1
    return {'level':level,'classes':len(classes),'source_index_level_eligible_rows':len(rows),
            'index_single_L1_casts':sum(x['L1_index_simple_executed'] for x in by_class.values()),
            'index_single_L1_events':events,'index_single_L1_proxy_casts':proxies,
            'by_class':by_class,'blocker_reasons':dict(reasons),'sample_executions':samples,
            'executed_rank_keys':executed_rank_keys,
            'CPU_s':round(process_time()-started,6),
            'promoted_to_source_complete_L2':0,'validated_checkpoints':0,'checkpoint_target':148,
            'source_authority':'canonical_forerunner_index_patch_tooltips_plus_SHA_rechecked_atom_ledger',
            'limitation':'Simple, fully matching listview descriptions only; actor may be bounded proxy; unknown GCD, hit/crit, acquisition and version parity. Not L2.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    p.add_argument('--level',type=int,default=20);p.add_argument('--output',type=Path)
    a=p.parse_args();r=measure(a.db,a.level)
    if a.output:a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k!='sample_executions'},indent=2))

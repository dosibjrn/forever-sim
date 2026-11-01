"""Nine-class canonical index L1 composite execution inventory, never L2."""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from collections import Counter
from time import process_time_ns
from src.game.data.forever.source_partial_l1 import bounded_actor_l1_probe_ir
from src.game.data.forever.source_index_composite_l1 import probe_index_composite_l1
from src.game.data.forever.registry import registered_class_keys


def measure(db_path:Path, *, level:int)->dict:
    if not 1<=level<=60:raise ValueError('INVALID_LEVEL')
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('BAD_CANONICAL_SQLITE')
        rows=db.execute('''SELECT a.class_key,a.spell_id,COUNT(*) FROM ability_effect_atom_observations a
          JOIN spell_index i ON i.class_key=a.class_key AND i.spell_id=a.spell_id
          AND i.kind='abilities' WHERE i.level_hint<=? GROUP BY a.class_key,a.spell_id
          HAVING COUNT(*)>=2 ORDER BY a.class_key,a.spell_id''',(level,)).fetchall()
    start=process_time_ns();done=[];blocked=[];events=0
    for cls in registered_class_keys():
        subset=[r for r in rows if r[0]==cls]
        if not subset:continue
        try:ir,template,proxy=bounded_actor_l1_probe_ir(class_key=cls,level=level,db_path=db_path)
        except (ValueError,RuntimeError) as exc:
            blocked.extend({'class_key':cls,'spell_id':sid,'reason':'NO_ACTOR:'+str(exc)} for _,sid,_ in subset)
            continue
        for _,sid,_ in subset:
            try:r=probe_index_composite_l1(ir,class_key=cls,spell_id=sid,db_path=db_path)
            except (ValueError,RuntimeError,NotImplementedError) as exc:
                blocked.append({'class_key':cls,'spell_id':sid,'reason':str(exc)[:240]})
                continue
            events+=r['events']
            done.append({'class_key':cls,'spell_id':sid,'source_index_atoms':r['source_index_atom_count'],
                'kinds':r['composed_fragment_kinds'],'damage':r['damage'],
                'events':r['events'],'actor_proxy':proxy,'actor_template_level':template})
    return {'level':level,'indexed_multi_atom_candidates':len(rows),'executed_composite_l1':len(done),
        'blocked_composite_l1':len(blocked),'events':events,'CPU_s':(process_time_ns()-start)/1e9,
        'by_class':dict(Counter(x['class_key'] for x in done)),
        'blocker_histogram':dict(Counter(x['reason'] for x in blocked)),
        'executed':done,'blocked':blocked,'source_complete_L2':0,'validated_checkpoints':0,
        'legal_routes':0,'L1_periodic_timing':'one-terminal-tick proxy, NOT game timing',
        'L2_eligible':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--level',type=int,default=20);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=measure(a.db,level=a.level)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print({k:v for k,v in r.items() if k not in ('executed','blocked')})
if __name__=='__main__':main()

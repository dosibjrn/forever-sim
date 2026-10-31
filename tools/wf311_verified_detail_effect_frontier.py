"""Nine-class, source-verified spell-detail slot L1 canary (NOT L2 legality)."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import process_time_ns
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice,registered_class_keys
from src.game.data.forever.source_partial_l1 import probe_verified_detail_l1,probe_verified_detail_composite_l1,PartialSourceEvidenceError


def measure(*,db_path:Path=Path(DEFAULT_DB),level:int=20)->dict:
    if not 1<=level<=60:raise ValueError('INVALID_LEVEL')
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT s.class_key,s.spell_id,s.slot,s.typed_kind,i.level_hint
            FROM verified_spell_detail_effect_slots s JOIN spell_index i ON
            i.class_key=s.class_key AND i.spell_id=s.spell_id AND i.kind='abilities'
            WHERE i.level_hint<=? ORDER BY s.class_key,s.spell_id,s.slot''',(level,)).fetchall()
    # Source-complete *effect slots*, not complete L2 game actions.
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        candidates=db.execute("""SELECT h.class_key,h.spell_id,h.effect_slots
            FROM verified_spell_detail_effect_headers h JOIN spell_index i
            ON i.class_key=h.class_key AND i.spell_id=h.spell_id AND i.kind='abilities'
            WHERE i.level_hint<=? AND h.effect_slots=h.supported_slots
            AND h.effect_slots>0 ORDER BY h.class_key,h.spell_id""",(level,)).fetchall()
    started=process_time_ns();results={};total_events=0;done=0;blocked=Counter();kinds=Counter()
    composites_executed=0;composite_events=0;composite_blocked=Counter()
    for cls in registered_class_keys():
        ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=db_path)
        good=[];fail=[]
        for key,sid,slot,kind,_ in rows:
            if key!=cls:continue
            try:
                r=probe_verified_detail_l1(ir,class_key=cls,spell_id=sid,slot=slot,db_path=db_path)
            except (PartialSourceEvidenceError,ValueError) as exc:
                reason=str(exc);blocked[reason]+=1
                fail.append({'spell_id':sid,'slot':slot,'kind':kind,'blocker':reason})
                continue
            done+=1;total_events+=r['events'];kinds[kind]+=1
            good.append({'spell_id':sid,'slot':slot,'kind':kind,'events':r['events'],
                'damage':r['total_damage'],'tick_count':r['verified_tick_count']})
        composite_good=[]
        for key,sid,slot_count in candidates:
            if key!=cls:continue
            try:
                r=probe_verified_detail_composite_l1(ir,class_key=cls,spell_id=sid,db_path=db_path)
            except (PartialSourceEvidenceError,ValueError) as exc:
                composite_blocked[str(exc)]+=1
                continue
            composites_executed+=1;composite_events+=r['events']
            composite_good.append({'spell_id':sid,'slots':slot_count,
                'events':r['events'],'damage':r['total_damage'],
                'damage_event_times':r['damage_event_times']})
        results[cls]={'executed':good,'blocked':fail,
            'composite_executed':composite_good,'source_ir_at_level':ir is not None}
    return {'level':level,'verified_detail_effect_slots_at_level':len(rows),
            'l1_verified_effect_slots_executed':done,'runtime_events':total_events,
            'by_kind_executed':dict(kinds),'blocker_counts':dict(blocked),
            'by_class':results,'controller_cpu_ns':process_time_ns()-started,
            'verified_all_slots_typed_composite_candidates':len(candidates),
            'l1_composite_casts_executed':composites_executed,
            'l1_composite_runtime_events':composite_events,
            'composite_blockers':dict(composite_blocked),
            'canonical_ability_db_sha256':sha256(db_path.read_bytes()).hexdigest(),
            'accepted_checkpoints':0,'world_routes':0,'l2_promotions':0,
            'warning':'L1 verified slots only; all other slots, acquisition, policy, gear and L2 mechanics blocked'}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--level',type=int,default=20);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=measure(db_path=a.db,level=a.level)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print({k:v for k,v in r.items() if k not in ('by_class','canonical_ability_db_sha256')})

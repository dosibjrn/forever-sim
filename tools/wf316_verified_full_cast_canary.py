#!/usr/bin/env python3
"""Nine-class verified-source complete-cast frontier; all L1, never checkpoint.

No spell-name, ID or class dispatch. Source stage is independently SHA-checked;
all missing effect slots, costs, resources and levels remain explicit blockers.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from time import process_time
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_partial_l1 import (
    complete_verified_detail_l1_action, PartialSourceEvidenceError,
    bounded_actor_l1_probe_ir)
from src.game.runtime.simulator import execute_action
from src.game.runtime.state import ActorState, TargetState

CLASSES=('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')


def audit(db_path:Path, *,level:int=20)->dict:
    start=process_time()
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT i.class_key,i.spell_id FROM spell_detail_snapshots s
            JOIN spell_index i ON s.batch_id=i.batch_id AND s.spell_id=i.spell_id
            WHERE i.kind='abilities' ORDER BY i.class_key,i.spell_id''').fetchall()
    by_class={cl:{'verified_detail_pages':0,'complete_L1_casts':0,'blocked':0} for cl in CLASSES}
    records=[];blockers=Counter();events=0
    for cl,sid in rows:
        by_class[cl]['verified_detail_pages']+=1
        record={'class_key':cl,'spell_id':sid,'requested_level':level,
                'tier':'L1_ONLY_NOT_SOURCE_COMPLETE_L2'}
        try:
            ir,template,proxy=bounded_actor_l1_probe_ir(
                class_key=cl,level=level,db_path=db_path)
            record.update(actor_template_level=template,
                actor_level_proxy=proxy,actor_stats_not_source_validated=proxy)
            action,proof=complete_verified_detail_l1_action(ir,class_key=cl,spell_id=sid,db_path=db_path)
            actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
            for cost in action.costs:
                if not actor.can_spend(cost.resource_id,cost.amount):
                    raise PartialSourceEvidenceError('INSUFFICIENT_SOURCE_IR_RESOURCE')
            result=execute_action(action=action,actor=actor,
                target=TargetState.with_health('L1_probe',1_000_000,
                    **({'movement_speed':1.0,'spell_hit':1.0} if any(
                        e.effect_type=='target_stat_debuff' for e in action.effects) else {})),
                spell_power=0.0,allow_source_partial_l1=True)
            assert action.metadata['never_l2_legal']
            record.update(status='EXECUTED_FULL_TYPED_L1_CAST_NOT_L2',
                          effect_count=len(action.effects),events=len(result.events),
                          damage=result.total_damage,
                          source_html_sha256=proof['detail_html_sha256'],
                          paid_casts=sum(e.kind=='ActionStarted' for e in result.events))
            by_class[cl]['complete_L1_casts']+=1
            events+=len(result.events)
        except (ValueError,KeyError) as exc:
            code=str(exc).split(':',1)[0]
            record.update(status='BLOCKED',reason_code=code)
            by_class[cl]['blocked']+=1;blockers[code]+=1
        records.append(record)
    return {'class_count':len(CLASSES),'level':level,'verified_pages':len(rows),
            'full_typed_L1_casts':sum(x['complete_L1_casts'] for x in by_class.values()),
            'blocked_pages':sum(x['blocked'] for x in by_class.values()),
            'by_class':by_class,'blockers':dict(blockers),'runtime_events':events,
            'cpu_s':round(process_time()-start,6),'records':records,
            'bounded_actor_proxy_casts':sum(1 for r in records if r.get('status')=='EXECUTED_FULL_TYPED_L1_CAST_NOT_L2' and r.get('actor_level_proxy')), 
            'executable_source_complete_L2':0,'accepted_checkpoints':0,
            'validated_leveling_routes':0}


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--level',type=int,default=20);p.add_argument('--output',type=Path)
    a=p.parse_args();r=audit(a.db,level=a.level)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in r.items() if k!='records'},indent=2,sort_keys=True))
if __name__=='__main__':main()

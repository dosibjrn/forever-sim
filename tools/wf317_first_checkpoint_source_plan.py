"""Source-coverage-driven real HTML capture plan for the FIRST checkpoint.

No class/spell-specific mechanics or presumed acquire levels; the only case
parameters are checkpoint identity (class + level). Reuses the existing
indexed_ability_coverage, role_scope and WF313 verified concurrent capture.
Positive-level candidate actions precede rune/setup and unknown-level ranks.
"""
from __future__ import annotations
import argparse,json,sqlite3
from collections import Counter,defaultdict
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.data.forever.source_action_scope import scope_audit
from src.v2.source_action_proxy import checkpoint_action_proxy_coverage
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot,MissingVerifiedSpellDetail
from tools.capture_forever_abilities_sqlite import load_detail_plan

ORDER = ('UNRESOLVED_POSITIVE_LEVEL_ENTRY','MATCHED_POSITIVE_LEVEL_ENTRY',
         'SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP',
         'ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE')


def make_plan(*,class_key:str='druid',level:int=20,
              db_path:Path=Path('data/forever/catalogue/forever_abilities.sqlite')):
    if not 1<=level<=60:raise ValueError('BAD_CHECKPOINT_LEVEL')
    cls=str(class_key).lower()
    ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=db_path)
    if ir is None:raise ValueError('MISSING_SOURCE_IR_FOR_CHECKPOINT')
    coverage=indexed_ability_coverage(ir,class_key=cls,level=level,db_path=db_path)
    # Reuse the checkpoint-scoped L0 proxy to prioritize *source recovery*.
    # Uncompiled spells are never silently excluded or made executable.
    l0=checkpoint_action_proxy_coverage(ir,level=level)
    source_priority={r['spell_id']:r['l0_proxy_priority'] for r in l0['indexed_ranks']}
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT spell_id,batch_id,raw_listview_json,source_url FROM spell_index
                  WHERE class_key=? AND kind='abilities' ''',(cls,)).fetchall()
        by_id={int(x['spell_id']):x for x in rows}
        scoped=scope_audit(coverage,{sid:r['raw_listview_json'] for sid,r in by_id.items()})
        groups=defaultdict(list);details=[];seen=set(); verified=0
        for record in scoped['records']:
            sid=int(record['source_spell_id']);role=record['role']
            if role=='EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET':
                details.append({'spell_id':sid,'role':role,'status':'REMOVED_REQUIRES_PATCH_SCOPE_REVIEW_NOT_CAPTURED'})
                continue
            if role=='UNRESOLVED_POSITIVE_LEVEL_ENTRY' and record['matched_action_ids']:
                role='MATCHED_POSITIVE_LEVEL_ENTRY'
            if role not in ORDER:raise ValueError('UNKNOWN_SOURCE_ROLE:'+role)
            if sid in seen:raise ValueError('DUPLICATE_SOURCE_RANK')
            seen.add(sid)
            row=by_id[sid]
            try:
                proof=read_verified_spell_detail_snapshot(db,batch_id=row['batch_id'],spell_id=sid)
                existing='ALREADY_INDEPENDENTLY_VERIFIED_HTML';verified+=1
            except MissingVerifiedSpellDetail:
                proof=None;existing='MISSING_VERIFIED_DETAIL_HTML'
            groups[role].append({'spell_id':sid,'name':record['name'],'source_url':row['source_url'],
                                'batch_id':row['batch_id'],'prior_ir_action_ids':record['matched_action_ids'],
                                'source_level_hint':record['source_level_hint'],
                                'status':existing,'detail_sha256':proof['html_sha256'] if proof else None})
        # One chunk per (source role, batch ID); never put an ID into an
        # unvalidated list or exceed the existing fetcher's 12-chunk limit.
        chunks=[]
        for role in ORDER:
            group=sorted(groups[role],key=lambda x:(-source_priority.get(x['spell_id'],0.),
                                                   x['source_level_hint'] or 0,x['spell_id']))
            batches=defaultdict(list)
            for record in group:batches[record['batch_id']].append(record['spell_id'])
            for bid,sids in sorted(batches.items()):
                for offset in range(0,len(sids),250):
                    chunks.append({'batch_id':bid,'spell_ids':sids[offset:offset+250]})
        if not chunks or len(chunks)>12:raise ValueError('SOURCE_PLAN_NEEDS_ADDITIONAL_SESSIONS')
        plan={'schema':'forever_detail_session_v1','chunks':chunks}
        # Validate exactly the same index/batch constraints as the real browser.
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(mode='w',suffix='.json',delete=True) as f:
            json.dump(plan,f);f.flush()
            validated=load_detail_plan(Path(f.name),db)
        if validated!=chunks:raise ValueError('CAPTURE_PLAN_VALIDATOR_DRIFT')
        return {'schema':'wf317_checkpoint_capture_priority_v1',
                'class_key':cls,'level':level,'capture_plan':plan,
                'priority_roles':{k:groups[k] for k in ORDER},
                'l0_proxy_priority_used_for_capture_order':True,
                'l0_source_index_proxy_scored':l0['source_index_proxy_scored_count'],
                'counts':{'planned_source_ids':len(seen),'previously_verified_html':verified,
                          'missing_real_html':len(seen)-verified,
                          'excluded_removed_for_patch_review':len(details),
                          'indexed_at_level_or_unknown':coverage['at_or_unknown_below_level_count'],
                          'missing_gameplay_ir_action_rows':coverage['unrepresented_rank_count'],
                          'priority_role_counts':{k:len(groups[k]) for k in ORDER}},
                'patch_removed_records':details,
                'blocked_unindexed_spell_grants':'Verify source_spell_dependency_observations separately',
                'source_coverage_proven':False,'accepted_checkpoints':0,
                'checkpoint_target':148}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--db',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    ap.add_argument('--class-key',default='druid');ap.add_argument('--level',type=int,default=20)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True)
    a=ap.parse_args()
    r=make_plan(class_key=a.class_key,level=a.level,db_path=a.db)
    a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    a.plan.write_text(json.dumps(r['capture_plan'],indent=2)+'\n')
    print(json.dumps(r['counts'],indent=2))
if __name__=='__main__':main()

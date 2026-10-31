"""Class/level-scoped spell acquisition *evidence*, never an implicit grant.

The canonical Forever abilities listview includes trainer/quest hints, talent
passives, rune recipes and internal effects.  An indexed required level (even
level 1) does NOT grant an ability.  This ledger separates setup from buttons
and validates the identity of the acquisition evidence against the same SQLite
source snapshot consumed by the L0 and L2 pipelines.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import sqlite3
from pathlib import Path

from .source_action_scope import classify_indexed_ability
from .sqlite_talents import DEFAULT_DB


def acquisition_frontier(*, class_key: str, level: int, db_path: str | Path = DEFAULT_DB) -> dict:
    cls = str(class_key).strip().lower()
    if not cls or not 1 <= int(level) <= 60:
        raise ValueError('INVALID_CHECKPOINT_CLASS_LEVEL')
    p = Path(db_path).resolve()
    with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('''SELECT spell_id,name,level_hint,rank_hint,source_url,
            raw_listview_json,batch_id FROM spell_index
            WHERE class_key=? AND kind='abilities' AND
            (level_hint IS NULL OR level_hint<=?) ORDER BY spell_id''', (cls, int(level))).fetchall()
        if not rows:
            raise ValueError('NO_CLASS_SOURCE_INDEX')
        has_evidence = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_acquisition_evidence'").fetchone()
        evidence_rows = [dict(r) for r in db.execute(
            '''SELECT e.*,s.html_sha256 AS snapshot_sha,d.details_verified,
                b.status AS batch_status FROM ability_acquisition_evidence e
                LEFT JOIN spell_detail_snapshots s ON s.batch_id=e.index_batch_id AND s.spell_id=e.spell_id
                LEFT JOIN spell_details d ON d.batch_id=e.index_batch_id AND d.spell_id=e.spell_id
                LEFT JOIN capture_batches b ON b.batch_id=e.index_batch_id
                WHERE e.class_key=?''',(cls,))] if has_evidence else []
        evidence = {}
        for ev in evidence_rows:
            key = (int(ev['spell_id']), ev['index_batch_id'])
            if key in evidence:
                raise ValueError('DUPLICATE_ACQUISITION_EVIDENCE_FOR_SOURCE_BATCH')
            evidence[key] = ev
    records=[]
    for r in rows:
        row=dict(r)
        raw=json.loads(row['raw_listview_json'])
        role=classify_indexed_ability(row,row['raw_listview_json'])
        sid=int(row['spell_id'])
        codes=raw.get('source') or []
        if not isinstance(codes,list) or any(not isinstance(c,int) for c in codes):
            raise ValueError('SOURCE_INDEX_ACQUISITION_CODES_MALFORMED')
        e=evidence.get((sid,row['batch_id']))
        status='NO_MATCHING_ACQUISITION_EVIDENCE'
        methods={}
        if e:
            if (e['index_batch_id']!=row['batch_id'] or e['source_url']!=row['source_url']
                    or e['required_level_hint']!=row['level_hint']
                    or e['source_payload_sha256']!=sha256(row['raw_listview_json'].encode()).hexdigest()):
                status='STALE_INDEX_ACQUISITION_EVIDENCE'
            elif e['detail_html_sha256'] is not None and (
                    e['detail_html_sha256']!=e['snapshot_sha'] or e['details_verified']!=1
                    or e['batch_status']!='complete'):
                status='STALE_DETAIL_ACQUISITION_EVIDENCE'
            else:
                status=e['evidence_status']
                methods=json.loads(e['methods_observed_json'])
        if role['role']=='SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP':
            category='EQUIPMENT_RUNE_SETUP_NOT_COMBAT_CAST'
        elif role['role']=='ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE':
            category='PASSIVE_OR_TALENT_NOT_FREE_CAST'
        elif role['role']=='EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET':
            category='REMOVED_PENDING_PATCH_APPLICABILITY'
        elif methods.get('taught_by_npc',0)>0 and status.startswith('VERIFIED_DETAIL_'):
            category='DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION'
        elif codes:
            category='SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'
        else:
            category='NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION'
        records.append({'spell_id':sid,'name':row['name'],'level_hint':row['level_hint'],
            'rank_hint':row['rank_hint'],'category':category,'index_source_codes':codes,
            'acquisition_evidence_status':status,'observed_methods':methods,
            'source_url':row['source_url'],
            'source_row_sha256':sha256(row['raw_listview_json'].encode()).hexdigest(),
            'free_combat_action_granted_by_index':False,
            'source_acquisition_verified':category=='DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION',
            'rune_effect_legality_verified':False})
    counts=Counter(x['category'] for x in records)
    return {'checkpoint':{'class_key':cls,'level':int(level)},
        'source_rows_at_or_below_level':len(records),
        'source_role_counts':dict(counts),
        'setup_not_combat_cast_count':counts['EQUIPMENT_RUNE_SETUP_NOT_COMBAT_CAST'],
        'source_hint_unverified_count':counts['SOURCE_INDEX_ACQUISITION_HINT_UNVERIFIED'],
        'no_acquisition_hint_count':counts['NO_ACQUISITION_HINT_POSSIBLE_INTERNAL_OR_GRANTED_ACTION'],
        'detail_observed_npc_count':counts['DETAIL_OBSERVED_NPC_TEACHING_NOT_POSSESSION'],
        'legal_active_denominator_proven':False,
        'no_free_rune_or_internal_grants':True,'records':records}

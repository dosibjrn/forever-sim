"""Fail-closed inventory of Forever indexed abilities versus executable Game IR.

An index entry is NOT proof a character has learned the button: rune, quest,
trainer, specialization and item gates need independent sourcing.  Every row is
retained, including downranks and unlevelled entries. Never infer executable
coverage from a matching name or a partial tooltip alone.
"""
from __future__ import annotations

from dataclasses import replace
import json
import hashlib
import re
import sqlite3
from pathlib import Path

from .sqlite_talents import DEFAULT_DB


def _source_spell_ids(action) -> set[int]:
    """IDs proven by explicit source metadata, NOT by fuzzy spell names."""
    result = set()
    for entry in (*action.provenance, action.metadata):
        if not isinstance(entry, dict):
            continue
        for field in ('source_spell_id', 'spell_id'):
            value = entry.get(field)
            if value is not None:
                try:
                    if int(value) > 0:
                        result.add(int(value))
                except (TypeError, ValueError):
                    pass
        for field in ('url', 'source_url', 'wowhead'):
            url = entry.get(field)
            if isinstance(url, str):
                match = re.search(r'/spell=(\d+)(?:\D|$)', url)
                if match:
                    result.add(int(match.group(1)))
    return result


def indexed_ability_coverage(ir, *, class_key: str, level: int,
                             db_path: str | Path | None = None) -> dict:
    """Map EVERY source-indexed ability rank to an exact action or typed blocker.

    Includes entries whose acquisition status or training level is uncertain;
    those are never called legal or quietly dropped. No class/spell whitelist.
    """
    path = Path(db_path or DEFAULT_DB)
    if not path.is_file():
        raise FileNotFoundError(f'canonical ability SQLite missing: {path}')
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        has_candidates = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='ability_index_effect_candidates'").fetchone())
        candidates = {}
        if has_candidates:
            candidates = {(str(r['class_key']),int(r['spell_id'])): dict(r)
                for r in conn.execute("SELECT class_key,spell_id,semantic_shape,source_payload_sha256,execution_status,"
                    "missing_fields_json,acquisition_status "
                    "FROM ability_index_effect_candidates WHERE class_key=?",
                    (class_key.strip().lower(),))}
        from .source_verified_detail_headers import verified_headers_for_class
        header_rows=verified_headers_for_class(path,class_key.strip().lower())
        from .source_effect_atoms import verified_class_effect_atoms
        atom_evidence_by_id=verified_class_effect_atoms(
            path,class_key=class_key.strip().lower(),
            allow_stale_index=(db_path is not None and
                               path.resolve() != Path(DEFAULT_DB).resolve()))
        from .source_stat_aura_candidates import read_current_candidates
        stat_aura_evidence={int(x['spell_id']):x for x in read_current_candidates(path,class_key=class_key.strip().lower())}
        # Source parser drift is an explicit rank-level blocker. A known IR
        # action cannot mask a quarantined, source-conflicting detail page.
        quarantined={}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_source_ingest_blockers'").fetchone():
            from .source_ingest_blockers import read_blocker
            for q in conn.execute('''SELECT class_key,spell_id,stage
                FROM verified_source_ingest_blockers WHERE class_key=?''',
                (class_key.strip().lower(),)).fetchall():
                entry=read_blocker(conn,class_key=q['class_key'],
                    spell_id=int(q['spell_id']),stage=q['stage'])
                quarantined.setdefault(int(q['spell_id']),[]).append(entry)
        # Partial atoms are NEVER proof of action legality or completeness.
        acquisition_rows = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_acquisition_evidence'").fetchone():
            acquisition_rows = {int(r['spell_id']): dict(r) for r in conn.execute(
                "SELECT e.spell_id,e.index_batch_id,e.source_url,e.source_payload_sha256,"
                "e.required_level_hint,e.evidence_status,e.methods_observed_json,"
                "e.detail_html_sha256,s.html_sha256 AS live_detail_sha,"
                "d.details_verified AS live_detail_verified,b.status AS live_batch_status "
                "FROM ability_acquisition_evidence e "
                "LEFT JOIN spell_detail_snapshots s ON s.batch_id=e.index_batch_id AND s.spell_id=e.spell_id "
                "LEFT JOIN spell_details d ON d.batch_id=e.index_batch_id AND d.spell_id=e.spell_id "
                "LEFT JOIN capture_batches b ON b.batch_id=e.index_batch_id "
                "WHERE e.class_key=?", (class_key.strip().lower(),))}
        rows = conn.execute("SELECT i.class_key,i.spell_id,i.name,i.level_hint,i.rank_hint,"
              "i.source_url,i.batch_id,i.raw_listview_json,CASE WHEN s.spell_id IS NULL THEN 0 ELSE 1 END AS verified_semantic_row "
              "FROM spell_index i LEFT JOIN ability_semantic_source_facts s "
              "ON s.class_key=i.class_key AND s.spell_id=i.spell_id "
              "WHERE lower(i.class_key)=? AND i.kind='abilities' "
              "ORDER BY i.name,i.level_hint,i.spell_id",
              (class_key.strip().lower(),)).fetchall()
    sources: dict[int, list[str]] = {}
    for action in ir.actions:
        for source_id in _source_spell_ids(action):
            sources.setdefault(source_id, []).append(action.id)
    indexed, outside_window = [], []
    for r in rows:
        spell_id = int(r['spell_id'])
        level_hint = r['level_hint']
        candidate = candidates.get((str(r['class_key']),spell_id))
        acquisition = acquisition_rows.get(spell_id)
        header = header_rows.get(spell_id)
        atom_evidence=atom_evidence_by_id.get(spell_id)
        stat_aura=stat_aura_evidence.get(spell_id)
        quarantine=quarantined.get(spell_id,[])
        # Keep only the observed listview tooltip fields needed for a cheap
        # checkpoint L0 estimate.  They are evidence, not executable effects;
        # `after` is the observed beta listview when present, `before` is
        # explicitly marked historical and may be stale.
        raw_listview=json.loads(r['raw_listview_json'])
        change=raw_listview.get('envChange') or {}
        tooltip=change.get('after') or change.get('before') or {}
        tooltip_phase=('after' if change.get('after') else
                       'before_only' if change.get('before') else 'unavailable')
        source_codes=raw_listview.get('source') or []
        record = {'spell_id':spell_id, 'name':r['name'], 'rank_hint':r['rank_hint'],
                  'listview_tooltip':{k:tooltip.get(k) for k in ('text','cost','cast','cooldown','range')},
                  'listview_tooltip_phase':tooltip_phase,
                  'listview_source_codes':source_codes,
                  'listview_training_cost':raw_listview.get('trainingcost'),
                  'listview_sha256':hashlib.sha256(r['raw_listview_json'].encode()).hexdigest(),
                  'level_hint':level_hint, 'source_url':r['source_url'],
                  'batch_id':r['batch_id'], 'verified_semantic_row':bool(r['verified_semantic_row']),
                  'matched_action_ids':sorted(set(sources.get(spell_id, ())))}
        if quarantine:
            record['verified_source_quarantine']=[{'stage':x['stage'],
                'reason_code':x['reason_code'],'source_sha256':x['detail_html_sha256']}
                for x in quarantine]
        if stat_aura is not None:
            record['source_stat_aura_candidate']={k:v for k,v in stat_aura.items() if k not in ('class_key','spell_id')}
            record['source_stat_aura_execution_status']=stat_aura['execution_status']
        if atom_evidence is not None:
            if atom_evidence['execution_status']=='STALE_ATOM_INDEX_REINGEST_REQUIRED':
                # An explicit stage changed the indexed source after atom
                # ingestion. Expose the blocker; never reuse its old atoms.
                record['source_effect_execution_status']='STALE_ATOM_INDEX_REINGEST_REQUIRED'
            else:
                record['source_effect_atom_count']=atom_evidence['atom_count']
                record['source_effect_atom_kinds']=[a['kind'] for a in atom_evidence['atoms']]
                record['source_effect_residual_text']=atom_evidence['residual_text']
                record['source_effect_evidence_scope']=atom_evidence['source_authority']
                record['source_effect_execution_status']='BLOCKED_PARTIAL_EFFECT_EVIDENCE'
        if header:
            record['verified_detail_header_status'] = header['effect_execution_status']
            record['verified_detail_cost'] = ({'resource':header['cost_resource'],
                'amount':header['cost_amount']} if header['cost_resource'] is not None else None)
            record['verified_detail_sha256'] = header['detail_html_sha256']
        if acquisition:
            if (acquisition['source_payload_sha256'] != hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()
                    or acquisition['index_batch_id'] != r['batch_id']
                    or acquisition['source_url'] != r['source_url']
                    or acquisition['required_level_hint'] != level_hint
                    or (acquisition['detail_html_sha256'] is not None and (
                        acquisition['detail_html_sha256'] != acquisition['live_detail_sha']
                        or acquisition['live_detail_verified'] != 1
                        or acquisition['live_batch_status'] != 'complete'))):
                record['acquisition_evidence_status'] = 'STALE_SOURCE_REINGEST_REQUIRED'
            else:
                record['acquisition_evidence_status'] = acquisition['evidence_status']
                record['acquisition_methods_observed'] = json.loads(acquisition['methods_observed_json'])
            record['world_acquisition_verified'] = False
        else:
            record['acquisition_evidence_status'] = 'MISSING_ACQUISITION_EVIDENCE'
            record['world_acquisition_verified'] = False
        if candidate and candidate['source_payload_sha256'] != hashlib.sha256(
                r['raw_listview_json'].encode()).hexdigest():
            record['typed_index_status'] = 'STALE_SOURCE_CAPTURE_REINGEST_REQUIRED'
            candidate = None
        if candidate:
            record['typed_index_shape'] = candidate['semantic_shape']
            record['typed_index_missing_fields'] = json.loads(candidate['missing_fields_json'])
            record['typed_index_acquisition'] = candidate['acquisition_status']
            record['typed_index_execution_status'] = candidate['execution_status']
        if level_hint is None or int(level_hint) <= 0:
            record['status'] = 'BLOCKED_UNKNOWN_ACQUISITION_LEVEL'
        elif int(level_hint) > int(level):
            outside_window.append({**record, 'status':'INDEXED_ABOVE_SCENARIO_LEVEL'})
            continue
        elif quarantine:
            record['status']='BLOCKED_SOURCE_DETAIL_QUARANTINED'
        elif record['matched_action_ids']:
            record['status'] = 'SOURCE_ID_MATCHES_IR_ACTION_ACQUISITION_UNVERIFIED'
        elif r['verified_semantic_row']:
            record['status'] = 'BLOCKED_VERIFIED_SEMANTIC_NOT_IN_IR'
        else:
            record['status'] = 'BLOCKED_INDEX_ONLY_NO_EXECUTABLE_SEMANTICS'
        indexed.append(record)
    exact = [r for r in indexed if r['matched_action_ids'] and not r.get('verified_source_quarantine')]
    typed = [r for r in indexed if r.get('typed_index_shape')]
    headers = [r for r in indexed if r.get('verified_detail_header_status')]
    blocked = [r for r in indexed if not r['matched_action_ids'] or r.get('verified_source_quarantine')]
    atom_rank_count=sum(r.get('source_effect_atom_count',0)>0 for r in indexed)
    stat_aura_rank_count=sum('source_stat_aura_candidate' in r for r in indexed)
    atom_count=sum(r.get('source_effect_atom_count',0) for r in indexed)
    return {'class_key':class_key.lower(), 'scenario_level':int(level),
            'status':'INCOMPLETE' if blocked else 'INDEX_RANKS_MATCH_IR_ACQUISITION_UNVERIFIED',
            'not_proof_of_legal_action_coverage':True,
            'indexed_ability_rank_count':len(rows),
            'at_or_unknown_below_level_count':len(indexed),
            'above_level_count':len(outside_window),
            'typed_index_candidate_count':len(typed),
            'source_stat_aura_typed_candidate_rank_count':stat_aura_rank_count,
            'source_stat_aura_candidates_not_executable':True,
            'source_effect_atom_rank_count':atom_rank_count,
            'source_effect_atom_count':atom_count,
            'source_effect_atoms_not_executable':True,
            'source_verified_detail_header_count':len(headers),
            'source_verified_quarantined_rank_count':sum(bool(r.get('verified_source_quarantine')) for r in indexed),
            'source_verified_header_is_not_executable':True,
            'typed_index_candidate_is_not_executable':True,
            'exact_source_rank_in_ir_count':len(exact),
            'unrepresented_rank_count':len(blocked),
            'records':indexed, 'blockers':blocked}


def attach_indexed_ability_coverage(ir, *, class_key: str, level: int,
                                    db_path: str | Path | None = None):
    """Decorate a provider result without mutating action search or inventing legality."""
    report = indexed_ability_coverage(ir,class_key=class_key,level=level,db_path=db_path)
    summary = {k:v for k,v in report.items() if k not in ('records','blockers')}
    # Full ledger is reachable from source_facts for listener and acceptance gates.
    return replace(ir,
        source_facts=ir.source_facts+({'fact_kind':'canonical_indexed_ability_coverage',
                                     'summary':summary,'records':report['records']},),
        provenance={**dict(ir.provenance), 'indexed_ability_coverage':summary,
                    'complete_source_action_coverage':False})

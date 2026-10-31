"""Append manual primary-Wowhead source observations to a distinct canonical-SQLite stage.

Does not turn web excerpts into verified HTML or executable spell actions.
Checks source-index IDs, level and names, and writes first-class unresolved
edges so an index-only optimizer cannot claim source completeness.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from pathlib import Path

_DDL='''CREATE TABLE IF NOT EXISTS source_spell_dependency_observations (
 class_key TEXT NOT NULL, source_spell_id INTEGER NOT NULL,
 referenced_spell_id INTEGER NOT NULL, relationship TEXT NOT NULL,
 source_url TEXT NOT NULL, target_source_url TEXT NOT NULL,
 literal_source_excerpt TEXT NOT NULL, target_requires_level INTEGER,
 target_can_be_executed_as_cast INTEGER, independent_acquisition_verified INTEGER NOT NULL,
 source_note TEXT NOT NULL, observation_status TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL,
 PRIMARY KEY(class_key,source_spell_id,referenced_spell_id,relationship))'''


def ingest(database:Path, evidence_file:Path)->dict:
    evidence=json.loads(Path(evidence_file).read_text())
    if evidence['status']!='MANUALLY_REVIEWED_WEB_TEXT_ONLY_NOT_VERIFIED_HTML_NOT_EXECUTABLE':
        raise ValueError('EVIDENCE_MUST_REMAIN_NON_EXECUTABLE')
    rows=evidence['observations']
    if not rows:raise ValueError('EMPTY_EVIDENCE')
    db=sqlite3.connect(database)
    try:
        with db:
            db.execute(_DDL)
            for r in rows:
                sid=int(r['source_spell_id']);tid=int(r['referenced_spell_id'])
                if sid<=0 or tid<=0 or sid==tid:raise ValueError('INVALID_GRANT_EDGE')
                if r['independent_acquisition_verified'] is not False:raise ValueError('CANNOT_ASSUME_ACQUISITION')
                if r['target_can_be_executed_as_cast'] not in (None,True,False):raise ValueError('UNKNOWN_CASTABILITY')
                if not r['source_url'].startswith('https://www.wowhead.com/forever/spell='):
                    raise ValueError('UNVERIFIED_SOURCE_DOMAIN')
                if not r['target_source_url'].startswith('https://www.wowhead.com/forever/spell='):
                    raise ValueError('UNVERIFIED_TARGET_DOMAIN')
                if str(r['source_spell_id']) not in r['source_url'] or str(r['referenced_spell_id']) not in r['target_source_url']:
                    raise ValueError('SOURCE_URL_ID_MISMATCH')
                # Only edges from indexed spells or previously observed links are allowed.
                source_index=db.execute('SELECT 1 FROM spell_index WHERE class_key=? AND spell_id=?',(r['class_key'],sid)).fetchone()
                source_parent=db.execute('SELECT 1 FROM source_spell_dependency_observations WHERE class_key=? AND referenced_spell_id=?',(r['class_key'],sid)).fetchone()
                if not (source_index or source_parent):raise ValueError('UNANCHORED_SOURCE_EDGE')
                source_sha=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                old=db.execute('SELECT evidence_sha256 FROM source_spell_dependency_observations WHERE class_key=? AND source_spell_id=? AND referenced_spell_id=? AND relationship=?', (r['class_key'],sid,tid,r['relationship'])).fetchone()
                if old is not None:
                    if old[0]!=source_sha:raise ValueError('SOURCE_OBSERVATION_CHANGE_REQUIRES_NEW_EVIDENCE_VERSION')
                    continue
                db.execute('INSERT INTO source_spell_dependency_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                    r['class_key'],sid,tid,r['relationship'],r['source_url'],r['target_source_url'],
                    r['literal_source_excerpt'],r['target_requires_level'],
                    None if r['target_can_be_executed_as_cast'] is None else int(r['target_can_be_executed_as_cast']),
                    0,r['source_note'],evidence['status'],source_sha))
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLITE_INVALID')
        return {'dependency_edges':db.execute('SELECT COUNT(*) FROM source_spell_dependency_observations').fetchone()[0],
                'unique_dependency_targets':db.execute('SELECT COUNT(DISTINCT referenced_spell_id) FROM source_spell_dependency_observations').fetchone()[0],
                'executable_promotions':0,'acquisition_promotions':0,'source_html_verified':False}
    finally:db.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--db',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path)
 a=p.parse_args();print(json.dumps(ingest(a.db,a.evidence),indent=2))

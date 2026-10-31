"""Batch-normalize all nine Forever Wowhead ability indexes into typed source candidates.

This is *not* an executable-ability ingestion step. The listview supplies
base numbers and cast/cost, but generally not spell-power coefficients,
periodic tick interval, crit mechanics or actual acquisition. Unknowns are
NULL and explicit blockers. No guessed coefficients or class-specific rules.

The resulting canonical SQLite rows are directly consumed by indexed ability
coverage to identify the next source-fetch requirements for every class.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3

PATTERNS = (
    ('direct_damage', re.compile(r'Causes (\d+) to (\d+) (\w+) damage to the target\.', re.I)),
    ('direct_heal', re.compile(r'Heals a friendly target for (\d+) to (\d+)\.', re.I)),
    ('direct_periodic_heal', re.compile(r'Heals a friendly target for (\d+) to (\d+) and another (\d+) over (\d+) sec\.', re.I)),
    ('periodic_heal', re.compile(r'Heals the target (?:for|of) (\d+) (?:health|damage) over (\d+) sec\.', re.I)),
    ('periodic_damage', re.compile(r'A word of darkness that causes (\d+) Shadow damage over (\d+) sec\.', re.I)),
)
COST = re.compile(r'(\d+(?:\.\d+)?) (Mana|Energy|Rage)', re.I)
COMPLEX_DAMAGE = re.compile(
    r'(?:causes?|deals?|inflicts?|hits|for)\b.{0,150}?\b\d+(?:\.\d+)?(?:\s+to\s+\d+(?:\.\d+)?)?\s+(?:\w+\s+)?damage\b', re.I)
CAST = re.compile(r'(\d+(?:\.\d+)?) sec cast', re.I)
SCHEMA = '''CREATE TABLE IF NOT EXISTS ability_index_effect_candidates (
    class_key TEXT NOT NULL, spell_id INTEGER NOT NULL,
    index_batch_id TEXT NOT NULL, source_url TEXT NOT NULL,
    semantic_shape TEXT NOT NULL, parsed_values_json TEXT NOT NULL,
    cost_resource TEXT NOT NULL, cost_amount REAL NOT NULL, cast_time_s REAL NOT NULL,
    required_level_hint INTEGER, spell_power_coefficient REAL,
    tick_interval_s REAL, acquisition_status TEXT NOT NULL,
    execution_status TEXT NOT NULL, missing_fields_json TEXT NOT NULL,
    source_payload_sha256 TEXT NOT NULL, captured_at TEXT NOT NULL,
    PRIMARY KEY (class_key, spell_id)
)'''


def extract(row: sqlite3.Row, *, captured_at: str):
    raw = json.loads(row['raw_listview_json'])
    after = (raw.get('envChange') or {}).get('after') or {}
    tooltip = str(after.get('text') or '').strip()
    cost = COST.fullmatch(str(after.get('cost') or '').strip())
    cast_text = str(after.get('cast') or '').strip()
    cast = CAST.fullmatch(cast_text)
    if not cost or (not cast and cast_text.lower() != 'instant'):
        return None
    shape, values = next(((name, match.groups()) for name, pattern in PATTERNS
                          if (match := pattern.fullmatch(tooltip))), (None, None))
    if shape is None:
        # Identify complex offensive buttons for source-detail fetching without
        # claiming their effect can be executed. The whole tooltip remains
        # authoritative; a matching fragment is never treated as a complete
        # effect or promoted to combat IR.
        if not COMPLEX_DAMAGE.search(tooltip):
            return None
        shape, values = 'partial_damage_complex', (tooltip,)
    level = row['level_hint']
    # Listview trainingcost is a hint, not a verified trainer/quest gate.
    # Runes and talent spells are NOT assumed learned at their indexed level.
    acquisition = 'INDEX_TRAINING_COST_HINT_UNVERIFIED' if raw.get('trainingcost') is not None else 'UNKNOWN_ACQUISITION'
    missing = ['spell_power_coefficient', 'acquisition_gate']
    if shape == 'partial_damage_complex':
        missing.append('full_effect_grammar_and_secondary_mechanics')
    if shape in ('direct_periodic_heal', 'periodic_heal', 'periodic_damage'):
        missing.append('periodic_tick_interval')
    # Never use the compiler's zero coefficient as a substitute for missing facts.
    with_coeff = None
    payload_hash = hashlib.sha256(row['raw_listview_json'].encode()).hexdigest()
    return (row['class_key'], int(row['spell_id']), row['batch_id'], row['source_url'],
            shape, json.dumps(values), cost.group(2).lower(), float(cost.group(1)),
            0.0 if not cast else float(cast.group(1)), level, with_coeff, None,
            acquisition, 'BLOCKED_INDEPENDENT_MECHANICS', json.dumps(missing),
            payload_hash, captured_at)


def ingest(db_path: Path, *, captured_at: str | None = None) -> dict:
    date = captured_at  # Normally use each indexed batch's immutable capture date.
    db = sqlite3.connect(str(db_path)); db.row_factory = sqlite3.Row
    try:
        rows = db.execute('''SELECT i.class_key,i.spell_id,i.batch_id,i.source_url,
            i.level_hint,i.raw_listview_json,b.captured_at AS source_captured_at
            FROM spell_index i JOIN capture_batches b ON b.batch_id=i.batch_id
            WHERE i.kind='abilities' ORDER BY i.class_key,i.spell_id''').fetchall()
        extracted = [candidate for row in rows if (candidate := extract(row,captured_at=date or row['source_captured_at']))]
        if not extracted: raise ValueError('no fully parsed source shapes; refusing empty ingestion')
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA)
        # All candidates are reproducible from one canonical listview snapshot;
        # replace this derived table atomically to avoid stale rows after recapture.
        db.execute('DELETE FROM ability_index_effect_candidates')
        db.executemany('''INSERT INTO ability_index_effect_candidates VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',extracted)
        db.commit()
        return {'indexed_abilities':len(rows),'typed_candidates':len(extracted),
                'by_class':dict(Counter(row[0] for row in extracted)),
                'by_shape':dict(Counter(row[4] for row in extracted)),
                'executable_promotions':0,
                'note':'typed index facts only; no missing coefficients/ticks/acquisition invented'}
    except Exception:
        db.rollback(); raise
    finally:
        db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(ingest(args.db),indent=2,sort_keys=True))

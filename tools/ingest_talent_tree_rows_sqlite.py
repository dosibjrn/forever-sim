"""Import a source-evidenced, partial talent tree row capture into canonical SQLite.

The source capture, not this tool, determines all class/talent identities and
row numbers. Missing rows are never filled in, and secondary positions remain
provisional. A row is not a full legality assertion: columns, prerequisites,
rank caps and effects are independent coverage requirements.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


def ingest(db_path: Path, capture_path: Path) -> dict:
    capture = json.loads(capture_path.read_text(encoding='utf-8'))
    class_key = str(capture['class_key']).lower()
    capture_id = str(capture['capture_id'])
    facts = capture['facts']
    if not facts:
        raise ValueError('empty tree row capture')
    conn = sqlite3.connect(str(db_path))
    try:
        indexed = conn.execute('''SELECT spell_id,name FROM spell_index WHERE class_key=? AND kind='talents'
            AND batch_id=(SELECT batch_id FROM capture_lists WHERE class_key=? AND kind='talents'
                          ORDER BY batch_id DESC LIMIT 1)''', (class_key,class_key)).fetchall()
        by_name = {str(name).casefold(): int(sid) for sid,name in indexed}
        if len(by_name) != len(indexed):
            raise ValueError('ambiguous indexed talent names')
        verified = 0
        provisional = 0
        rows = []
        for fact in facts:
            name = str(fact['name'])
            spell_id = by_name.get(name.casefold())
            if spell_id is None:
                raise ValueError(f'captured talent absent from canonical SQLite: {name}')
            row = int(fact['row'])
            if not 0 <= row <= 6:
                raise ValueError(f'invalid talent row: {name}={row}')
            authority = str(fact['authority'])
            if authority not in ('wowhead_announcement_row', 'secondary_provisional_row'):
                raise ValueError(f'unsupported source authority: {authority}')
            url = str(fact['source_url'])
            if not url.startswith('https://') or not str(fact.get('evidence') or '').strip():
                raise ValueError(f'missing source evidence for {name}')
            # Dated Wowhead announcements are explicit evidence, not a
            # current-beta tree verification. Secondary rows remain provisional.
            if authority == 'wowhead_announcement_row' and 'wowhead.com/' not in url:
                raise ValueError(f'primary authority URL mismatch: {name}')
            rows.append((class_key, spell_id, row, None, authority, url,
                         str(fact['evidence']), capture_id))
            if authority == 'wowhead_announcement_row': verified += 1
            else: provisional += 1
        if len({row[1] for row in rows}) != len(rows):
            raise ValueError('duplicate talent in row capture')
        rule = capture.get('tier_rule')
        if rule is None:
            raise ValueError('capture lacks sourced tier rule')
        points_per_row = int(rule['points_per_row'])
        if points_per_row <= 0 or points_per_row > 100:
            raise ValueError('invalid sourced points-per-row rule')
        if rule.get('authority') != 'secondary_provisional_rule' or not str(rule.get('source_url','')).startswith('https://'):
            raise ValueError('tier rule requires explicit provenance')
        if not str(rule.get('evidence','')).strip():
            raise ValueError('tier rule evidence missing')
        conn.execute('''CREATE TABLE IF NOT EXISTS talent_tree_rules (
            class_key TEXT PRIMARY KEY, points_per_row INTEGER NOT NULL,
            authority TEXT NOT NULL, source_url TEXT NOT NULL,
            evidence_text TEXT NOT NULL, capture_id TEXT NOT NULL)''')
        conn.execute('''INSERT OR REPLACE INTO talent_tree_rules VALUES (?,?,?,?,?,?)''',
            (class_key,points_per_row,str(rule['authority']),str(rule['source_url']),
             str(rule['evidence']),capture_id))
        conn.execute('''CREATE TABLE IF NOT EXISTS talent_tree_row_facts (
            class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, tree_row INTEGER NOT NULL,
            tree_col INTEGER, authority TEXT NOT NULL, source_url TEXT NOT NULL,
            evidence_text TEXT NOT NULL, capture_id TEXT NOT NULL,
            PRIMARY KEY (class_key, spell_id))''')
        # Never replace unrelated existing source facts by omission.
        for row in rows:
            existing = conn.execute('''SELECT tree_row,authority FROM talent_tree_row_facts
                WHERE class_key=? AND spell_id=?''', row[:2]).fetchone()
            if existing is not None and existing[1] == 'wowhead_announcement_row' and row[4] != 'wowhead_announcement_row':
                raise ValueError(f'cannot downgrade primary source row: {row[1]}')
            conn.execute('''INSERT OR REPLACE INTO talent_tree_row_facts VALUES (?,?,?,?,?,?,?,?)''', row)
        conn.commit()
        return {'capture_id':capture_id,'class_key':class_key,'imported':len(rows),
                'explicit_wowhead_announcement':verified,'secondary_provisional':provisional,
                'canonical_index_total':len(indexed),'remaining_unknown_rows':len(indexed)-len(rows),
                'points_per_row':points_per_row,'tier_rule_authority':rule['authority']}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=Path('data/forever/catalogue/forever_abilities.sqlite'))
    p.add_argument('--capture',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(ingest(args.db,args.capture),indent=2))

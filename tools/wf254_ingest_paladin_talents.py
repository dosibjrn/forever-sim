"""Idempotent batch ingestion of client-verified Paladin rank text.

Facts live in JSON capture; no gameplay constants are imported by the engine.
Tree rows inherited from Classic without explicit Forever change are tagged
provisional, never claimed as current-server verified.
"""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf254_paladin_rank_batch_20261011.json'

def ingest(db_path=DEFAULT_DB,capture_path=CAPTURE):
    p=json.loads(Path(capture_path).read_text())
    if p['class_key']!='paladin' or p['client_build']!='1.60.1.70009' or len(p['families'])<4:
        raise ValueError('wrong class/build or incomplete batch')
    with sqlite3.connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        ids={int(r[0]):str(r[1]) for r in db.execute("SELECT spell_id,name FROM spell_index WHERE class_key=? AND kind='talents'",(p['class_key'],))}
        db.execute('''INSERT OR REPLACE INTO talent_tree_rules
          (class_key,points_per_row,authority,source_url,evidence_text,capture_id)
          VALUES(?,?,?,?,?,?)''',('paladin',5,'client_calculator_secondary_provisional',
            p['calculator_url'],'Current calculator states points needed to open each tier; five-point tier gate inherited Classic, target-client crosscheck pending',p['capture_id']))
        count=0
        for f in p['families']:
            spell_id=int(f['spell_id']);cap=int(f['max_rank'])
            if ids.get(spell_id)!=f['name'] or cap<1 or len(f['ranks'])!=cap:
                raise ValueError(f'index identity or rank curve mismatch: {spell_id}')
            if sorted(int(r['rank']) for r in f['ranks'])!=list(range(1,cap+1)):
                raise ValueError('noncontiguous rank curve')
            if not (f['source_url'].startswith('https://foreverdiff.com/talents/') or
                    f['source_url'].startswith('https://www.wowhead.com/forever/spell=')):
                raise ValueError('invalid source URL')
            old=db.execute('SELECT DISTINCT capture_id FROM talent_rank_source_facts WHERE class_key=? AND spell_id=?',('paladin',spell_id)).fetchall()
            if old and any(r[0]!=p['capture_id'] for r in old):
                raise ValueError('would overwrite a different source capture')
            for r in f['ranks']:
                if not r['raw_tooltip'].strip():raise ValueError('empty rank tooltip')
                db.execute('''INSERT OR REPLACE INTO talent_rank_source_facts
                  (class_key,spell_id,rank,max_rank,trait_id,raw_tooltip,source_url,tooltip_source_url,
                   source_authority,capture_id,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                   ('paladin',spell_id,int(r['rank']),cap,0,r['raw_tooltip'],
                    'https://www.wowhead.com/forever/spell='+str(spell_id),f['source_url'],
                    r['authority'],p['capture_id'],p['captured_at']))
                count+=1
            row=f['tree_row']
            if row is not None:
                db.execute('''INSERT OR REPLACE INTO talent_tree_row_facts
                  (class_key,spell_id,tree_row,tree_col,authority,source_url,evidence_text,capture_id)
                  VALUES(?,?,?,?,?,?,?,?)''',('paladin',spell_id,int(row),f.get('tree_col'),
                    f['tree_authority'],f['source_url'],f['tree_evidence'],p['capture_id']))
        return {'families':len(p['families']),'rank_rows':count,'capture':p['capture_id']}

if __name__=='__main__':print(ingest())

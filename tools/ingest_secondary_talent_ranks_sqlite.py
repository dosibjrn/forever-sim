"""Import verified *secondary* client-text rank captures without invented trait IDs.

The source-indexed Wowhead spell ID establishes identity; secondary client
transcriptions provide rank text.  trait_id=0 is an explicit unknown sentinel,
never a claimed client Trait ID.  Primary trait captures always take precedence.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse


def ingest(db_path: Path, capture_path: Path) -> dict:
    payload=json.loads(Path(capture_path).read_text(encoding='utf-8'))
    if payload.get('schema') != 'forever_secondary_client_talent_rank_capture_v1':
        raise ValueError('unsupported secondary rank capture schema')
    batch=str(payload['capture_id'])
    class_key=str(payload['class_key']).lower()
    entries=payload.get('entries') or []
    if not entries:
        raise ValueError('empty secondary rank capture')
    conn=sqlite3.connect(str(db_path))
    try:
        conn.execute('BEGIN IMMEDIATE')
        indexed={int(r[0]):(str(r[1]),str(r[2])) for r in conn.execute(
            'SELECT spell_id,name,source_url FROM spell_index WHERE class_key=? AND kind=?',
            (class_key,'talents'))}
        seen=set(); ranks_written=0; rows_written=0
        for entry in entries:
            spell_id=int(entry['spell_id'])
            if spell_id in seen or spell_id not in indexed or indexed[spell_id][0]!=entry['name']:
                raise ValueError(f'nonindexed or duplicate talent {spell_id}')
            seen.add(spell_id)
            url=str(entry['tooltip_source_url'])
            if urlparse(url).scheme!='https' or not urlparse(url).hostname:
                raise ValueError(f'bad secondary source URL for {spell_id}')
            cap=int(entry['max_rank']); ranks=entry['ranks']
            if cap<1 or len(ranks)!=cap or [int(x['rank']) for x in ranks]!=list(range(1,cap+1)):
                raise ValueError(f'incomplete rank capture for {spell_id}')
            existing=conn.execute('SELECT DISTINCT capture_id,trait_id FROM talent_rank_source_facts '
                                  'WHERE class_key=? AND spell_id=?',(class_key,spell_id)).fetchall()
            if existing and (len(existing)!=1 or existing[0][0]!=batch):
                raise ValueError(f'cannot overwrite existing source authority {spell_id}')
            for rank in ranks:
                text=str(rank['raw_tooltip']).strip()
                if not text: raise ValueError(f'empty tooltip {spell_id} rank {rank["rank"]}')
                conn.execute('''INSERT INTO talent_rank_source_facts
                    (class_key,spell_id,rank,max_rank,trait_id,raw_tooltip,source_url,
                    tooltip_source_url,source_authority,capture_id,captured_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    (class_key,spell_id,int(rank['rank']),cap,0,text,indexed[spell_id][1],url,
                     'secondary_client_build_transcription',batch,str(payload['captured_at'])))
                ranks_written+=1
            if entry.get('tree_row') is not None:
                row=int(entry['tree_row']); col=int(entry['tree_col'])
                if not 0<=row<=6 or not 0<=col<=4:raise ValueError('invalid tree coordinates')
                previous=conn.execute('SELECT tree_row,tree_col FROM talent_tree_row_facts '
                                      'WHERE class_key=? AND spell_id=?',(class_key,spell_id)).fetchone()
                if previous is not None:
                    if previous[0]!=row or (previous[1] is not None and previous[1]!=col):
                        raise ValueError(f'conflicting tree position for {spell_id}')
                    # Keep the higher-authority existing row provenance intact;
                    # only fill its previously missing column from secondary data.
                    conn.execute('''UPDATE talent_tree_row_facts SET tree_col=?,
                        evidence_text=evidence_text || ? WHERE class_key=? AND spell_id=?''',
                        (col,'; secondary column source: '+url,class_key,spell_id))
                else:
                    conn.execute('''INSERT INTO talent_tree_row_facts
                        (class_key,spell_id,tree_row,tree_col,authority,source_url,evidence_text,capture_id)
                        VALUES(?,?,?,?,?,?,?,?)''',
                        (class_key,spell_id,row,col,'secondary_client_build_position',url,
                         'Source page gives row and column',batch))
                rows_written+=1
        conn.commit()
        return {'class_key':class_key,'capture_id':batch,'families':len(seen),
                'ranks':ranks_written,'positions':rows_written,'indexed':len(indexed)}
    except Exception:
        conn.rollback();raise
    finally:conn.close()

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--db',type=Path,required=True)
    ap.add_argument('--capture',type=Path,required=True);a=ap.parse_args()
    print(json.dumps(ingest(a.db,a.capture),indent=2))

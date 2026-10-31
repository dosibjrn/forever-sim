"""Ingest source-indexed Flash of Light rank family into native recovery IR.

Rank 1 becomes a verified native HealEffect. Higher indexed ranks are
promoted by the existing generic source_rank_overlay, not by class code.
"""
from __future__ import annotations
import json,sqlite3,re
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf257_paladin_flash_recovery_20261011.json'

def ingest(db_path=DEFAULT_DB,capture_path=CAPTURE):
    cap=json.loads(Path(capture_path).read_text())
    if cap['class_key']!='paladin' or cap['family_key']!='flash_of_light' or not cap['capture_id']:
        raise ValueError('invalid source capture authority')
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        for f in cap['ranks']:
            r=db.execute("SELECT name,level_hint,raw_listview_json FROM spell_index WHERE class_key=? AND kind='abilities' AND spell_id=?",('paladin',f['spell_id'])).fetchone()
            if r is None or r['name']!=f['name'] or r['level_hint']!=f['level']:
                raise ValueError('canonical source index identity mismatch')
            data=json.loads(r['raw_listview_json']).get('envChange',{}).get('after',{})
            if data.get('text')!=f['tooltip'] or data.get('cost')!=f['cost_text'] or data.get('cast')!=f['cast_text']:
                raise ValueError('source rank tooltip mismatch')
            m=re.fullmatch(r'Heals a friendly target for (\d+) to (\d+)\.',data['text'])
            if m is None or [int(m.group(1)),int(m.group(2))]!=[f['min'],f['max']]:
                raise ValueError('unparsed sourced heal rank')
            if f['spell_power_coefficient']!=0.429 or not f['coefficient_source_url'].startswith('https://www.wowhead.com/forever/'):
                raise ValueError('missing coefficient source')
        f=cap['ranks'][0]
        existing=db.execute('SELECT capture_id FROM verified_native_class_actions WHERE class_key=? AND spell_id=?',('paladin',f['spell_id'])).fetchone()
        if existing:
            if existing['capture_id']!=cap['capture_id']:raise ValueError('conflicting native heal source capture')
            return {'family':'flash_of_light','verified_ranks':len(cap['ranks']),'already_installed':True}
        db.execute('''INSERT INTO verified_native_class_actions
            (class_key,spell_id,family_key,min_level,resource_id,cost,cast_s,gcd_s,cooldown_s,effect_json,source_url,capture_id,caveats_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
            'paladin',f['spell_id'],cap['family_key'],f['level'],'mana',f['mana_cost'],
            1.5,1.5,0.,json.dumps([{'kind':'heal','min':f['min'],'max':f['max'],
                'spell_power_coefficient':f['spell_power_coefficient']}]),
            f['source_url'],cap['capture_id'],json.dumps(['client tooltip values from indexed Wowhead source',
                'higher ranks promoted by shared source_rank_overlay',
                'server healing spell coefficient 0.429 from Forever Wowhead'])) )
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failed')
        db.commit()
        return {'family':'flash_of_light','verified_ranks':len(cap['ranks']),'already_installed':False}
if __name__=='__main__':print(ingest())

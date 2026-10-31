"""Idempotent source-only Paladin command talent grant and seal exclusivity ingest."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf255_paladin_command_weapon_speed_20261011.json'

def ingest(db_path=DEFAULT_DB,capture_path=CAPTURE):
    p=json.loads(Path(capture_path).read_text()); t=p['talent']; other=p['other_seal_exclusivity']
    if not p['class_key'] or not t['client_build'].startswith('1.60.1.'):
        raise ValueError('missing source class or client build')
    if t['rank']!=1 or t['max_rank']!=1 or t['required_level']<1:
        raise ValueError('invalid source rank or level')
    if not (t['source_url'].startswith('https://') and t['tree_source_url'].startswith('https://') and
            t['proc_source_url'].startswith('https://') and t['proc_authority'].startswith('CLASSIC_') and
            0<t['weapon_damage_multiplier']<=1 and t['proc_reference_speed_s']>0):
        raise ValueError('invalid sourced command mechanics')
    with sqlite3.connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        index=db.execute("SELECT name,level_hint FROM spell_index WHERE class_key=? AND kind='talents' AND spell_id=?",(p['class_key'],t['spell_id'])).fetchone()
        if index!=(t['name'],t['required_level']):raise ValueError('talent identity not in canonical index')
        old=db.execute('SELECT capture_id FROM verified_talent_rank_facts WHERE class_key=? AND spell_id=?',(p['class_key'],t['spell_id'])).fetchone()
        if old and old[0]!=p['capture_id']:raise ValueError('conflicting rank capture')
        action={k:v for k,v in t.items() if k not in ('tooltip','tree_key','tree_row_zero_indexed','tree_col_zero_indexed','tree_source_url','rank','max_rank','judge_damage_status')}
        action.update({'class_key':p['class_key'],'action_kind':'timed_aura_weapon_proc', 'cast_time_s':0.,'cooldown_s':0., 'capture_id':p['capture_id']})
        db.execute('''INSERT OR REPLACE INTO verified_talent_granted_action_facts
            (class_key,spell_id,action_json,source_url,captured_at,capture_id) VALUES(?,?,?,?,?,?)''',
            ('paladin',t['spell_id'],json.dumps(action,sort_keys=True),t['source_url'],p['captured_at'],p['capture_id']))
        modifier={'kind':'grant_source_action','target_type':'source_action',
                  'target_id':str(t['spell_id']),'value':1.0}
        db.execute('''INSERT OR REPLACE INTO verified_talent_rank_facts
            (class_key,spell_id,talent_name,tree_key,tree_row,tree_col,rank,max_rank,trait_id,modifier_json,
             rank_source_url,tree_source_url,captured_at,capture_id)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (p['class_key'],t['spell_id'],t['name'],t['tree_key'],t['tree_row_zero_indexed'],t['tree_col_zero_indexed'],
             t['rank'],t['max_rank'],0,json.dumps([modifier]),t['source_url'],t['tree_source_url'],p['captured_at'],p['capture_id']))
        columns={x[1] for x in db.execute('PRAGMA table_info(sourced_timed_aura_actions)')}
        if 'exclusive_group' not in columns:
            db.execute('ALTER TABLE sourced_timed_aura_actions ADD COLUMN exclusive_group TEXT')
        existing=db.execute('SELECT COUNT(*) FROM sourced_timed_aura_actions WHERE class_key=? AND aura_id=?',
                            (p['class_key'],other['aura_id'])).fetchone()[0]
        if existing<1 or other['exclusive_group']!=t['exclusive_group'] or not other['text'].startswith('Only one Seal'):
            raise ValueError('sourced existing seal exclusivity cannot be confirmed')
        db.execute('UPDATE sourced_timed_aura_actions SET exclusive_group=? WHERE class_key=? AND aura_id=?',
                   (other['exclusive_group'],p['class_key'],other['aura_id']))
        speed_columns={x[1] for x in db.execute('PRAGMA table_info(equipped_weapon_mode_source_facts)')}
        if 'weapon_speed_semantics' not in speed_columns:
            db.execute('ALTER TABLE equipped_weapon_mode_source_facts ADD COLUMN weapon_speed_semantics TEXT')
        if 'weapon_speed_source_url' not in speed_columns:
            db.execute('ALTER TABLE equipped_weapon_mode_source_facts ADD COLUMN weapon_speed_source_url TEXT')
        for fact in p['weapon_speed_facts']:
            if (fact['weapon_speed_semantics'] not in ('equipped','form_fixed') or
                not fact['source_url'].startswith('https://')):
                raise ValueError('unverified equipped weapon speed semantics')
            speed_identity=db.execute('''SELECT source_item_slot FROM equipped_weapon_mode_source_facts
                WHERE class_key=? AND mode_label=?''',(fact['class_key'],fact['mode_label'])).fetchone()
            if speed_identity!=(fact['source_item_slot'],):
                raise ValueError('source weapon mode identity mismatch')
            db.execute('''UPDATE equipped_weapon_mode_source_facts SET
                weapon_speed_semantics=?,weapon_speed_source_url=?
                WHERE class_key=? AND mode_label=?''',
                (fact['weapon_speed_semantics'],fact['source_url'],fact['class_key'],fact['mode_label']))
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite corrupt')
        return {'new_talent_families':1,'new_talent_ranks':1,'new_talent_grants':1,
                'existing_aura_ranks_with_exclusive_group':existing,'capture':p['capture_id']}

if __name__=='__main__':print(ingest())

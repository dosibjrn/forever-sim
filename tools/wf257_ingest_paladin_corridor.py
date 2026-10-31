"""Fail-closed rank extension from existing Forever captures and pinned live-source facts.

No class-specific rank facts are embedded in the engine. The one-time capture
identities are checked against canonical Wowhead spell_index before promotion.
"""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB

CAPTURE=Path(__file__).resolve().parents[1]/'data/forever/source_captures/wf257_paladin_l21_30_20261011.json'


def ingest(db_path=DEFAULT_DB, capture_path=CAPTURE):
    facts=json.loads(Path(capture_path).read_text())
    if facts['class_key']!='paladin' or not facts['captured_at'] or not facts['capture_id']:
        raise ValueError('invalid rank capture authority')
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM verified_native_class_scenarios WHERE class_key=?',('paladin',)).fetchone()
        if row is None or row['min_level']!=10 or row['max_level'] not in (20,30):
            raise ValueError('unexpected native scenario range; reconcile concurrent source first')
        # Older capture replay is immutable. A second ingestion of this exact
        # batch is a no-op; a partial/conflicting newer batch fails closed.
        known=(('verified_native_class_actions',680),
               ('sourced_timed_aura_actions',20289),
               ('verified_talent_granted_action_facts',20915))
        present=[db.execute('SELECT capture_id FROM '+table+
            ' WHERE class_key=? AND spell_id=?',('paladin',sid)).fetchone()
            for table,sid in known]
        if all(x is not None for x in present) and row['max_level']==30:
            if any(x['capture_id']!=facts['capture_id'] for x in present):
                raise ValueError('conflicting rank capture already installed')
            if row['capture_id'] != facts['capture_id']:
                raise ValueError('extended source level missing matching scenario authority')
            return {'source_level_max':30,
                'promoted':[{'spell_id':int(f['spell_id']),
                    'family_key':f['family_key'],'level':int(f['required_level'])}
                    for f in facts['rank_promotions']],
                'capture_id':facts['capture_id'],'already_installed':True}
        if any(x is not None for x in present) or row['max_level']!=20:
            raise ValueError('partial or stale rank capture; reconcile first')
        old_sources=json.loads(row['provenance_json'])
        extension_urls=[f['source_url'] for f in facts['rank_promotions']]
        db.execute('''UPDATE verified_native_class_scenarios
            SET max_level=?,capture_id=?,provenance_json=? WHERE class_key=?''',
            (30,facts['capture_id'],json.dumps(sorted(set(old_sources+extension_urls))), 'paladin'))
        promoted=[]
        for f in facts['rank_promotions']:
            sid=int(f['spell_id']);lvl=int(f['required_level'])
            index=db.execute("SELECT name,level_hint,source_url,raw_listview_json FROM spell_index WHERE class_key=? AND kind='abilities' AND spell_id=?",('paladin',sid)).fetchone()
            if index is None or index['level_hint']!=lvl or index['name']!=f['indexed_name']:
                raise ValueError(f'spell identity/level not confirmed by canonical index: {sid}')
            if not f['source_url'].startswith('https://') or not (f['source_build'].startswith('1.60.1.') or f['source_build'].startswith('wowhead_forever_')):
                raise ValueError('missing source URL/build')
            if f['kind']=='native_weapon_plus_holy':
                if f['family_key']!='holy_strike' or not 0<f['weapon_fraction']<=1 or f['damage_min']>f['damage_max']:
                    raise ValueError('invalid sourced weapon+Holy rank')
                prior=db.execute('SELECT * FROM verified_native_class_actions WHERE class_key=? AND family_key=? ORDER BY min_level DESC LIMIT 1',('paladin',f['family_key'])).fetchone()
                if prior is None or json.loads(prior['effect_json'])[0]['kind']!='weapon_plus_holy':
                    raise ValueError('missing compatible existing source IR family')
                # Coefficient inherited from prior source rank, explicitly marked
                # as a *proxy* until this rank's coefficient is independently verified.
                sp=json.loads(prior['effect_json'])[0]['spell_power_coefficient']
                effect=[dict(kind='weapon_plus_holy',school='holy',multiplier=f['weapon_fraction'],
                             min=f['damage_min'],max=f['damage_max'],spell_power_coefficient=sp)]
                db.execute('''INSERT INTO verified_native_class_actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('paladin',sid,f['family_key'],lvl,'mana',f['mana_cost'],0.,1.5,10.,
                     json.dumps(effect),f['source_url'],facts['capture_id'],
                     json.dumps(['source client weapon fraction/base bounds',
                         'SP coefficient inherited from prior verified rank: unverified-current proxy',
                         f.get('source_conflict','')])) )
            elif f['kind']=='timed_aura_damage_rank':
                prior=db.execute('SELECT * FROM sourced_timed_aura_actions WHERE class_key=? AND family_key=? ORDER BY min_level DESC LIMIT 1',('paladin',f['family_key'])).fetchone()
                if prior is None or prior['mechanic_kind']!='swing_damage':
                    raise ValueError('missing compatible sourced timed aura')
                raw=json.loads(index['raw_listview_json']);tooltip=(raw.get('envChange') or {}).get('after',{}).get('text','')
                if not tooltip or str(f['index_tooltip_fragment']) not in tooltip:
                    raise ValueError('new aura rank not confirmed by canonical Wowhead index')
                columns=[x[1] for x in db.execute('PRAGMA table_info(sourced_timed_aura_actions)')]
                record={k:prior[k] for k in columns}
                record.update(spell_id=sid,min_level=lvl,mana_cost=f['mana_cost'],
                              swing_min=f['swing_min'],swing_max=f['swing_max'],
                              judgement_min=f['judge_min'],judgement_max=f['judge_max'],
                              source_url=f['source_url'],crosscheck_url=f['crosscheck_url'],
                              client_build=f['source_build'],capture_id=facts['capture_id'],
                              caveats_json=json.dumps({'inherited_server_proc_formula':'unverified proxy',
                                  'inherited_judgement_sp_coefficient':'unverified proxy',
                                  'rank_base_damage_source':f['source_url'],
                                  'source_conflict':f.get('source_conflict')}))
                db.execute('INSERT INTO sourced_timed_aura_actions ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(record[k] for k in columns))
            elif f['kind']=='talent_granted_rank':
                prior=db.execute('SELECT action_json FROM verified_talent_granted_action_facts WHERE class_key=? AND spell_id=?',('paladin',f['grant_parent_spell_id'])).fetchone()
                if prior is None:raise ValueError('no canonical parent talent-granted action')
                source=json.loads(prior[0]);
                if source['action_kind']!='timed_aura_weapon_proc':raise ValueError('incompatible granted action')
                raw=json.loads(index['raw_listview_json']);tooltip=(raw.get('envChange') or {}).get('after',{}).get('text','')
                if not tooltip or str(f['index_tooltip_fragment']) not in tooltip:
                    raise ValueError('talent-granted rank not confirmed by canonical index')
                source.update(spell_id=sid,grant_parent_spell_id=int(f['grant_parent_spell_id']),
                    required_level=lvl,mana_cost=f['mana_cost'],
                    judge_damage_base=(f['judge_min']+f['judge_max'])/2,
                    judge_damage_min=f['judge_min'],judge_damage_max=f['judge_max'],
                    source_url=f['source_url'],client_build=f['source_build'],
                    capture_id=facts['capture_id'],
                    caveats=[*source.get('caveats',[]),
                        'rank-specific Judgement bounds from client tooltip; proc rate remains Classic proxy',
                        f.get('source_conflict','')])
                db.execute('''INSERT INTO verified_talent_granted_action_facts
                    (class_key,spell_id,action_json,source_url,captured_at,capture_id) VALUES(?,?,?,?,?,?)''',
                    ('paladin',sid,json.dumps(source,sort_keys=True),f['source_url'],facts['captured_at'],facts['capture_id']))
            else:raise ValueError('unknown canonical promotion effect kind')
            promoted.append({'spell_id':sid,'family_key':f['family_key'],'level':lvl})
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failed')
        db.commit()
        return {'source_level_max':30,'promoted':promoted,'capture_id':facts['capture_id']}

if __name__=='__main__':print(json.dumps(ingest(),indent=2))

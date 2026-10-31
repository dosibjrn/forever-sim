"""Index- and observation-bound generic on-next-melee-swing IR ingestion.

Only the observation file carries spell IDs, levels, costs or bonus values.
A mere listview rank never authorizes L2 execution. The same Runtime owns the
attack timer, cost, event trace and outcome table.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3

from src.forever_build import current as current_build
from src.game.model.ir import ActionDefinition, QueuedSwingEffect, ResourceCost
from .source_db_scope import active_ability_db
from .sqlite_talents import DEFAULT_DB, _slug
from .source_indexed_action_coverage import _source_spell_ids

_SCHEMA='''CREATE TABLE IF NOT EXISTS source_queued_swing_observations (
    class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, name TEXT NOT NULL,
    learn_level INTEGER NOT NULL, required_mode_id TEXT NOT NULL,
    bonus_damage REAL NOT NULL, cost_resource TEXT NOT NULL, cost_amount REAL NOT NULL,
    source_url TEXT NOT NULL, observed_at TEXT NOT NULL, index_batch_id TEXT NOT NULL,
    raw_index_sha256 TEXT NOT NULL, observation_sha256 TEXT NOT NULL,
    observation_json TEXT NOT NULL, PRIMARY KEY(class_key,spell_id))'''
_COST=re.compile(r'^(\d+(?:\.\d+)?) (Rage|Energy|Mana)$')
_EFFECT=re.compile(r"^Increases the (?:.+?)(?:'s)? next attack by (\d+(?:\.\d+)?) damage\.$",re.I)

def parse_observation(obs:dict)->dict:
    """Strict source-text grammar, including zero-GCD queued semantics."""
    cost=_COST.fullmatch(str(obs.get('cost','')))
    effect=_EFFECT.fullmatch(str(obs.get('effect_text','')))
    if (not cost or not effect or obs.get('cast')!='Next Melee'
        or obs.get('gcd')!='0 sec' or obs.get('cooldown')!='n/a'
        or str(obs.get('required_mode_id','')).lower() not in ('bear','dire_bear')
        or 'Bear Form' not in str(obs.get('form_requirement',''))):
        raise ValueError('SOURCE_QUEUED_SWING_UNPARSED_OBSERVATION')
    return {'required_mode_id':str(obs['required_mode_id']),
            'bonus_damage':float(effect.group(1)),
            'cost_resource':cost.group(2).lower(),'cost_amount':float(cost.group(1))}

def ingest(db_path:Path,observation_file:Path):
    data=json.loads(Path(observation_file).read_text())
    if data.get('schema')!='forever_public_queued_swing_observation_v1':
        raise ValueError('SOURCE_QUEUED_SWING_SCHEMA_UNSUPPORTED')
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        db.execute(_SCHEMA)
        for obs in data['observations']:
            fields=parse_observation(obs)
            sid=int(obs['spell_id']);key=str(obs['class_key'])
            row=db.execute("SELECT * FROM spell_index WHERE class_key=? AND kind='abilities' AND spell_id=?",
                           (key,sid)).fetchone()
            if (row is None or row['name']!=obs['name'] or row['level_hint']!=obs['learn_level']
                or row['rank_hint']!=obs['rank'] or row['batch_id']!=obs['index_batch_id']
                or not str(obs['source_url']).startswith(row['source_url'])):
                raise ValueError(f'SOURCE_QUEUED_SWING_INDEX_IDENTITY_DRIFT:{sid}')
            raw=json.loads(row['raw_listview_json'])
            if ((raw.get('envChange') or {}).get('status')=='removed' or raw.get('id')!=sid
                or raw.get('name')!=obs['name'] or raw.get('level')!=obs['learn_level']):
                raise ValueError('SOURCE_QUEUED_SWING_REMOVED_OR_INVALID_RANK')
            blob=json.dumps(obs,sort_keys=True,separators=(',',':'))
            db.execute('''INSERT OR REPLACE INTO source_queued_swing_observations
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
                key,sid,obs['name'],obs['learn_level'],fields['required_mode_id'],
                fields['bonus_damage'],fields['cost_resource'],fields['cost_amount'],
                obs['source_url'],obs['observed_at'],row['batch_id'],
                sha256(row['raw_listview_json'].encode()).hexdigest(),
                sha256(blob.encode()).hexdigest(),blob))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

def source_queued_swing_actions(ir,*,class_key:str,level:int,db_path=None):
    path=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_queued_swing_observations'").fetchone():
            return ir
        rows=db.execute('''SELECT o.*,i.name AS index_name,i.level_hint,i.batch_id,
                         i.source_url AS index_url,i.raw_listview_json
                         FROM source_queued_swing_observations o JOIN spell_index i
                         ON i.class_key=o.class_key AND i.spell_id=o.spell_id AND i.kind='abilities'
                         WHERE o.class_key=? AND i.level_hint<=? ORDER BY i.level_hint,o.spell_id''',
                         (class_key,int(level))).fetchall()
    modes={m.id for m in ir.modes};resources={r.id for r in ir.resources}
    known={sid for action in ir.actions for sid in _source_spell_ids(action)}
    actions=[];permissions={};facts=[]
    for row in rows:
        sid=int(row['spell_id'])
        if date.fromisoformat(row['observed_at'][:10])>current_build().as_of:continue
        if (row['name']!=row['index_name'] or row['index_batch_id']!=row['batch_id']
            or row['raw_index_sha256']!=sha256(row['raw_listview_json'].encode()).hexdigest()
            or not row['source_url'].startswith(row['index_url']) or row['learn_level']!=row['level_hint']):
            raise ValueError(f'SOURCE_QUEUED_SWING_INDEX_IDENTITY_DRIFT:{sid}')
        obs=json.loads(row['observation_json'])
        if (sha256(row['observation_json'].encode()).hexdigest()!=row['observation_sha256']
            or obs['spell_id']!=sid or obs['name']!=row['name'] or obs['class_key']!=class_key
            or obs['source_url']!=row['source_url'] or obs['observed_at']!=row['observed_at']
            or obs['index_batch_id']!=row['index_batch_id'] or obs['learn_level']!=row['learn_level']):
            raise ValueError(f'SOURCE_QUEUED_SWING_OBSERVATION_SHA_OR_IDENTITY_DRIFT:{sid}')
        fields=parse_observation(obs)
        if any(fields[k]!=row[k] for k in fields):
            raise ValueError(f'SOURCE_QUEUED_SWING_STORED_FACT_DIFFERS:{sid}')
        mode=row['required_mode_id']
        autos=[a for a in ir.auto_attacks if a.owner_actor_id==ir.actor.id
               and a.required_mode_id==mode and a.attack_type=='melee']
        if (sid in known or mode not in modes or row['cost_resource'] not in resources
            or len(autos)!=1 or row['cost_amount']<0 or row['bonus_damage']<0):
            raise ValueError(f'SOURCE_QUEUED_SWING_ILLEGAL_MODE_RESOURCE_OR_COLLISION:{sid}')
        source={'authority':'forever_web_observation_index_sha_bound',
                'source_spell_id':sid,'source_url':row['source_url'],
                'index_batch_id':row['batch_id'],'observation_sha256':row['observation_sha256'],
                'observed_at':row['observed_at'],
                'independent_detail_html_verified':False,'client_build_verified':False}
        action=ActionDefinition(
            id=f'source_queued_swing:{sid}',family_key=_slug(row['name']),name=row['name'],
            owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(row['learn_level'])},
                          {'kind':'mode_is','value':mode}),
            costs=(ResourceCost(row['cost_resource'],float(row['cost_amount'])),),
            cast_time_s=0.0,gcd_s=0.0,cooldown_s=0.0,
            effects=(QueuedSwingEffect(effect_type='queued_swing',target='enemy',
                         auto_attack_id=autos[0].id,bonus_damage=float(row['bonus_damage'])),),
            provenance=(source,),metadata={'source_spell_id':sid,
                'source_semantic_type':'queued_swing',
                'full_checkpoint_source_coverage':'BLOCKED_UNVERIFIED_CLIENT_BUILD'})
        known.add(sid);actions.append(action);permissions.setdefault(mode,[]).append(action.id)
        facts.append({'fact_kind':'sourced_next_swing_action','spell_id':sid,'source':source})
    if not actions:return ir
    return replace(ir,actions=ir.actions+tuple(actions),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None
            else m.enabled_action_ids+tuple(permissions.get(m.id,())))) for m in ir.modes),
        source_facts=ir.source_facts+tuple(facts))

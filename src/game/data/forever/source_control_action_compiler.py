"""Compile source-index cross-checked timed enemy-control observations to Game IR.

One additive SQLite-backed action compiler for control categories not covered by
`source_ability_semantics`. Never trust an index-only row as a verified effect;
only rows with a separate, provenance-bound observation may be executable.
The observation is still *not* independent client-build/HTML verification, so
this does not grant unrestricted L2 checkpoint acceptance.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import hashlib
import json
import sqlite3

from src.forever_build import current as current_build
from src.game.model.ir import ActionDefinition, ControlEffect, ResourceCost
from .sqlite_talents import DEFAULT_DB, _slug
from .source_db_scope import active_ability_db
from .source_indexed_action_coverage import _source_spell_ids
from .source_control_observations import parse_control_observation


def source_control_actions(ir, *, class_key: str, level: int, db_path=None):
    dbpath=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{dbpath}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_control_action_observations'").fetchone():
            return ir
        rows=db.execute('''SELECT s.*,i.name AS index_name,i.level_hint,i.batch_id,
                            i.source_url AS index_url,i.raw_listview_json
                  FROM source_control_action_observations s JOIN spell_index i
                  ON i.spell_id=s.spell_id AND i.class_key=s.class_key
                  AND i.kind='abilities'
                  WHERE s.class_key=? AND i.level_hint<=?
                  ORDER BY i.level_hint,s.spell_id''',(class_key,int(level))).fetchall()
    known_ids={sid for action in ir.actions for sid in _source_spell_ids(action)}
    actions=[]; facts=[]; permissions={}
    modes={m.id for m in ir.modes};resources={r.id for r in ir.resources}
    for r in rows:
        if date.fromisoformat(r['captured_at'][:10])>current_build().as_of:
            continue
        sid=int(r['spell_id'])
        if (r['name']!=r['index_name'] or r['index_batch_id']!=r['batch_id']
            or r['raw_index_sha256']!=hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()
            or not r['source_url'].startswith(r['index_url'])
            or r['required_level']!=r['level_hint']):
            raise ValueError(f'SOURCE_CONTROL_INDEX_IDENTITY_DRIFT:{sid}')
        if r['effect_kind']!='stun' or not (0<float(r['duration_s'])<=120):
            raise ValueError(f'SOURCE_CONTROL_EFFECT_UNSUPPORTED:{sid}')
        if r['required_mode_id'] not in modes or r['cost_resource'] not in resources:
            raise ValueError(f'SOURCE_CONTROL_MODE_OR_RESOURCE_UNAVAILABLE:{sid}')
        if not (0<=float(r['cost_amount'])<=1e5 and 0<=float(r['cast_time_s'])<=120
                and 0<=float(r['gcd_s'])<=10 and 0<=float(r['cooldown_s'])<=3600):
            raise ValueError(f'SOURCE_CONTROL_INVALID_COST_OR_TIMING:{sid}')
        obs=json.loads(r['observation_json'])
        if obs.get('spell_id')!=sid or obs.get('class_key')!=class_key or obs.get('name')!=r['name']:
            raise ValueError(f'SOURCE_CONTROL_EVIDENCE_IDENTITY_DRIFT:{sid}')
        if hashlib.sha256(r['observation_json'].encode()).hexdigest()!=r['observation_sha256']:
            raise ValueError(f'SOURCE_CONTROL_EVIDENCE_SHA_DRIFT:{sid}')
        parsed=parse_control_observation(obs)
        if any(parsed[k] != r[k] for k in parsed):
            raise ValueError(f'SOURCE_CONTROL_STORED_FACT_DIFFERS_FROM_OBSERVATION:{sid}')
        if (obs['source_url'] != r['source_url'] or obs['observed_at'] != r['captured_at']
            or obs['index_batch_id'] != r['index_batch_id']
            or obs['learn_level'] != r['required_level']):
            raise ValueError(f'SOURCE_CONTROL_PROVENANCE_DRIFT:{sid}')
        if sid in known_ids:
            raise ValueError(f'SOURCE_CONTROL_ACTION_ID_COLLISION:{sid}')
        source={'authority':'sourced_public_forever_web_page_observation',
                'source_url':r['source_url'],'index_source_url':r['index_url'],
                'index_batch_id':r['batch_id'],'source_spell_id':sid,
                'web_observation_sha256':r['observation_sha256'],
                'observed_at':r['captured_at'],
                'independent_html_snapshot_verified':False,
                'current_client_build_verified':False}
        action=ActionDefinition(
            id=f'source_control:{sid}',family_key=_slug(r['name']),name=r['name'],
            owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(r['required_level'])},
                          {'kind':'mode_is','value':r['required_mode_id']}),
            costs=(ResourceCost(resource_id=r['cost_resource'],amount=float(r['cost_amount'])),),
            cast_time_s=float(r['cast_time_s']),gcd_s=float(r['gcd_s']),
            cooldown_s=float(r['cooldown_s']),
            effects=(ControlEffect(effect_type='control',control_id='stun',target='enemy',
                                   duration_s=float(r['duration_s'])),),
            provenance=(source,),
            metadata={'source_spell_id':sid,'source_semantic_type':'stun_control',
                      'full_checkpoint_source_coverage':'BLOCKED_UNVERIFIED_CLIENT_BUILD',
                      'enemy_swing_phase':'scheduled_cadence_continues_during_stun_unverified'},
        )
        known_ids.add(sid);actions.append(action)
        permissions.setdefault(r['required_mode_id'],[]).append(action.id)
        facts.append({'fact_kind':'source_indexed_executable_control',
                      'spell_id':sid,'effect_type':'stun','source':source,
                      'checkpoint_eligibility':'SOURCE_INCOMPLETE'})
    updated_modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None
                           else m.enabled_action_ids+tuple(permissions.get(m.id,())))) for m in ir.modes)
    return replace(ir,actions=ir.actions+tuple(actions),modes=updated_modes,
                   source_facts=ir.source_facts+tuple(facts))

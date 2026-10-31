"""Source-bound, class-neutral area enemy melee-AP debuff compiler.

Forever spell-index tooltip gives the debuff magnitude; external Classic spell
geometry and form requirements are separately labeled evidence, never inferred
from the spell name. Unknown tooltip syntax cannot become executable.
"""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import hashlib, json, re, sqlite3
from math import isfinite
from src.game.model.ir import ActionDefinition, ResourceCost, TargetStatDebuffEffect
from .source_indexed_action_coverage import _source_spell_ids
from .source_db_scope import active_ability_db
from .sqlite_talents import DEFAULT_DB, _slug

_SCHEMA='''CREATE TABLE IF NOT EXISTS source_enemy_melee_ap_debuff_facts (
 class_key TEXT NOT NULL, spell_id INTEGER NOT NULL, name TEXT NOT NULL,
 rank_level INTEGER NOT NULL, mode_id TEXT NOT NULL, cost_resource TEXT NOT NULL,
 cost_amount REAL NOT NULL, gcd_s REAL NOT NULL, radius_yards REAL NOT NULL,
 ap_reduction REAL NOT NULL, duration_s REAL NOT NULL, index_sha256 TEXT NOT NULL,
 source_url TEXT NOT NULL, geometry_source_url TEXT NOT NULL, evidence_json TEXT NOT NULL,
 PRIMARY KEY (class_key,spell_id))'''
_TEXT=re.compile(r"^The [^,.]+, decreasing nearby enemies' melee attack power by (\d+)\. Lasts (\d+) sec\.$",re.I)
_COST=re.compile(r'^(\d+(?:\.\d+)?) (Rage|Mana|Energy)$',re.I)

def _values(row, obs):
    source=json.loads(row['raw_listview_json'])
    after=(source.get('envChange') or {}).get('after') or {}
    match=_TEXT.fullmatch(str(after.get('text') or ''))
    cost=_COST.fullmatch(str(after.get('cost') or ''))
    if not (match and cost and after.get('cast')=='Instant' and
            after.get('cooldown') in (None,'') and
            after.get('name')==row['name'] and source.get('id')==row['spell_id']):
        raise ValueError('SOURCED_ENEMY_AP_TOOLTIP_INCOMPLETE:'+str(row['spell_id']))
    if (obs['spell_id']!=row['spell_id'] or obs['name']!=row['name'] or
            obs['class_key']!=row['class_key'] or
            obs['source_url']!=row['source_url'] or
            not str(obs.get('geometry_source_url','')).startswith('https://')):
        raise ValueError('SOURCED_ENEMY_AP_PROVENANCE_IDENTITY_MISMATCH')
    return (int(row['level_hint']),str(obs['required_mode_id']),cost.group(2).lower(),
            float(cost.group(1)),float(obs['gcd_s']),float(obs['radius_yards']),
            float(match.group(1)),float(match.group(2)))

def ingest(db_path:Path, observation_path:Path):
    doc=json.loads(observation_path.read_text())
    if doc.get('schema')!='source_enemy_melee_ap_debuff_observation_v1':
        raise ValueError('SOURCED_ENEMY_AP_SCHEMA')
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        db.execute(_SCHEMA)
        for obs in doc['observations']:
            row=db.execute("SELECT * FROM spell_index WHERE class_key=? AND spell_id=? AND kind='abilities'",
                           (obs['class_key'],int(obs['spell_id']))).fetchone()
            if row is None:raise ValueError('SOURCED_ENEMY_AP_SPELL_NOT_INDEXED')
            values=_values(row,obs)
            if (not 0<=values[3]<=10000 or not 0<values[4]<=10 or
                    not 0<values[5]<=100 or not 0<values[6]<=10000 or
                    not 0<values[7]<=3600):
                raise ValueError('SOURCED_ENEMY_AP_INVALID_VALUES')
            db.execute('INSERT OR REPLACE INTO source_enemy_melee_ap_debuff_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (row['class_key'],row['spell_id'],row['name'],*values,
                        hashlib.sha256(row['raw_listview_json'].encode()).hexdigest(),
                        row['source_url'],obs['geometry_source_url'],json.dumps(obs,sort_keys=True)))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'

def source_enemy_melee_ap_debuff_actions(ir, *, class_key:str,level:int,db_path=None):
    path=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_enemy_melee_ap_debuff_facts'").fetchone():
            return ir
        rows=db.execute('''SELECT f.*,i.raw_listview_json,i.source_url AS live_url,
                                i.name AS live_name,i.level_hint AS live_level
            FROM source_enemy_melee_ap_debuff_facts f JOIN spell_index i
              ON i.class_key=f.class_key AND i.spell_id=f.spell_id AND i.kind='abilities'
            WHERE f.class_key=? AND f.rank_level<=? ORDER BY f.rank_level,f.spell_id''',
            (class_key,int(level))).fetchall()
    known={sid for a in ir.actions for sid in _source_spell_ids(a)}
    modes={m.id for m in ir.modes}; resources={r.id for r in ir.resources}
    actions=[]; permissions={}
    for r in rows:
        obs=json.loads(r['evidence_json'])
        row={'raw_listview_json':r['raw_listview_json'],'spell_id':r['spell_id'],
             'class_key':r['class_key'],'source_url':r['live_url'],
             'name':r['live_name'],'level_hint':r['live_level']}
        expected=_values(row,obs)
        stored=tuple(r[k] for k in ('rank_level','mode_id','cost_resource','cost_amount','gcd_s','radius_yards','ap_reduction','duration_s'))
        if (expected!=stored or r['index_sha256']!=hashlib.sha256(r['raw_listview_json'].encode()).hexdigest()
            or r['source_url']!=r['live_url'] or r['geometry_source_url']!=obs['geometry_source_url']):
            raise ValueError('SOURCED_ENEMY_AP_INDEX_OR_VALUE_DRIFT:'+str(r['spell_id']))
        if r['mode_id'] not in modes or r['cost_resource'] not in resources or int(r['spell_id']) in known:
            raise ValueError('SOURCED_ENEMY_AP_MODE_RESOURCE_OR_COLLISION:'+str(r['spell_id']))
        src={'authority':'indexed_forever_tooltip_with_classic_geometry_proxy',
             'source_url':r['source_url'],'geometry_source_url':r['geometry_source_url'],
             'source_spell_id':int(r['spell_id']), 'geometry_status':'CLASSIC_PROXY_NOT_FOREVER_VERIFIED'}
        effect=TargetStatDebuffEffect(effect_type='target_stat_debuff',
            aura_id='source_enemy_melee_ap:'+str(r['spell_id']),target='enemies',
            target_stat_id='melee_attack_power',delta=-float(r['ap_reduction']),
            duration_s=float(r['duration_s']),provenance=(src,))
        a=ActionDefinition(id='source_enemy_ap:'+str(r['spell_id']),family_key=_slug(r['name']),
            name=r['name'],owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(r['rank_level'])},
                          {'kind':'mode_is','value':r['mode_id']}),
            costs=(ResourceCost(resource_id=r['cost_resource'],amount=float(r['cost_amount'])),),
            cast_time_s=0.,gcd_s=float(r['gcd_s']),cooldown_s=0.,effects=(effect,),
            provenance=(src,),metadata={'source_spell_id':int(r['spell_id']),
                'source_semantic_type':'enemy_melee_ap_debuff','aoe_center':'actor',
                'aoe_radius_yards':float(r['radius_yards']),
                'aoe_source':src,'geometry_status':'CLASSIC_PROXY_NOT_FOREVER_VERIFIED'})
        actions.append(a);known.add(int(r['spell_id']))
        permissions.setdefault(r['mode_id'],[]).append(a.id)
    updated=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else
                  m.enabled_action_ids+tuple(permissions.get(m.id,())))) for m in ir.modes)
    return replace(ir,actions=ir.actions+tuple(actions),modes=updated)

def source_enrich_enemy_melee_ap_incoming(ir):
    """Provide a qualified Classic AP -> melee raw damage conversion to sourced swings.

    Unlike a made-up enemy AP pool, this computes the reduction directly from
    AP / 14 * swing_time. Applied only to physical, sourced-cadence attacks.
    """
    enriched=[]
    for attack in ir.incoming_attacks:
        if attack.school!='physical' or 'melee_ap_per_dps' in attack.metadata:
            enriched.append(attack);continue
        cadence=attack.metadata.get('representative_swing_s')
        if cadence is None or not isfinite(float(cadence)) or float(cadence)<=0:
            enriched.append(attack);continue
        enriched.append(replace(attack,metadata={**attack.metadata,'melee_ap_per_dps':14.,
            'melee_ap_conversion_status':'CLASSIC_AP_DAMAGE_PROXY_14_AP_PER_1_DPS'}))
    return replace(ir,incoming_attacks=tuple(enriched))

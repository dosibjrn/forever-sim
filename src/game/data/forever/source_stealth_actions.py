"""Generic source-typed stealth actions (Druid/Rogue/Hunter, no named branches)."""
from dataclasses import replace
from pathlib import Path
import hashlib,json,sqlite3
from src.game.model.ir import ActionDefinition, StatusAuraEffect
from .sqlite_talents import DEFAULT_DB
from .source_db_scope import active_ability_db
from .source_indexed_action_coverage import _source_spell_ids


def source_stealth_actions(ir, *, class_key:str, level:int, db_path=None):
    path=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_stealth_action_facts'").fetchone():
            return ir
        rows=db.execute('SELECT f.*,i.name AS index_name,i.level_hint,i.rank_hint,i.source_url AS index_url,i.raw_listview_json AS index_raw '
                        'FROM source_stealth_action_facts f JOIN spell_index i ON '
                        "i.class_key=f.class_key AND i.spell_id=f.spell_id AND i.kind='abilities' "
                        'WHERE f.class_key=? AND i.level_hint<=?', (class_key,int(level))).fetchall()
    best={}
    for row in rows:
        facts=json.loads(row['facts_json'])
        if (row['name']!=facts['name'] or row['index_name']!=row['name'] or row['index_url']!=row['source_url'] or
                hashlib.sha256(row['index_raw'].encode()).hexdigest()!=row['index_sha256'] or
                int(row['level_hint'])!=facts['minimum_level'] or int(row['rank_hint'])!=facts['rank']):
            raise ValueError('STEALTH_SOURCE_INDEX_DRIFT:'+str(row['spell_id']))
        name=row['name'].casefold(); old=best.get(name)
        if old is None or int(row['rank_hint'])>int(old['rank_hint']):best[name]=row
    known={sid for a in ir.actions for sid in _source_spell_ids(a)}
    new=[]
    for row in best.values():
        sid=int(row['spell_id'])
        if sid in known:continue
        f=json.loads(row['facts_json'])
        mode=f.get('required_mode_id')
        if mode is not None and str(mode) not in {m.id for m in ir.modes}:
            raise ValueError('STEALTH_REQUIRED_MODE_UNAVAILABLE')
        multiplier=float(f['movement_speed_multiplier'])
        if not 0<multiplier<=1 or not f['indefinite_until_canceled']:
            raise ValueError('UNSUPPORTED_STEALTH_OBSERVATION')
        source={'authority':'source_stealth_action_facts','source_spell_id':sid,'source_url':row['source_url']}
        requirements=({'kind':'minimum_level','value':int(f['minimum_level'])},)
        if mode is not None:
            requirements+=({'kind':'mode_is','value':str(mode)},)
        if f['out_of_combat_only']:
            requirements+=({'kind':'out_of_combat'},)
        requirements+=({'kind':'aura_missing','aura_id':f'stealth:{sid}'},)
        new.append(ActionDefinition(id=f'source_spell:{sid}',family_key=row['name'].lower().replace(' ','_'),
            name=row['name'],owner_actor_id=ir.actor.id,
            requirements=requirements,costs=(),cast_time_s=0.,gcd_s=float(f['gcd_s']),
            cooldown_s=0.,
            effects=(StatusAuraEffect(effect_type='status_aura',aura_id=f'stealth:{sid}',
                target='actor',duration_s=1.,indefinite=True,stealth=True,
                movement_speed_multiplier=multiplier),),
            provenance=(source,),metadata={'source_spell_id':sid,'stealth_precombat':True,
                          'stealth_fade_cooldown_s':float(f['cooldown_s'])}))
    if not new:return ir
    modes=[]
    for mode in ir.modes:
        if mode.enabled_action_ids is None:
            modes.append(mode)
            continue
        allowed=tuple(a.id for a in new if not any(
            r.get('kind')=='mode_is' and r.get('value')!=mode.id for r in a.requirements))
        modes.append(replace(mode,enabled_action_ids=mode.enabled_action_ids+allowed))
    return replace(ir,actions=ir.actions+tuple(new),modes=tuple(modes),
                   source_facts=ir.source_facts+tuple({'fact_kind':'source_stealth','source_spell_id':int(a.metadata['source_spell_id'])}
                       for a in new))

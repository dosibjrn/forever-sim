"""Compile sourced next-attacker control buffs into common GameIR triggers.

The parser recognizes a narrowly defined source-tooltip grammar, not a class or
spell-ID allowlist. The victim-control duration comes from the *linked* current
rank's sourced tooltip rather than from an invented model constant.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import sqlite3

from src.game.model import ActionDefinition, ControlEffect, PeriodicEffect, ResourceCost, StatusAuraEffect, TriggerDefinition
from .sqlite_talents import DEFAULT_DB
from .source_db_scope import active_ability_db
from .source_indexed_action_coverage import _source_spell_ids

_REACTIVE = re.compile(r'^The next 1 melee attack that strikes the caster will afflict the attacker with (?P<name>.+?) \(Rank (?P<rank>\d+)\)\. Castable while shapeshifted\. Lasts (?P<duration>\d+) sec\.$')
_ROOT = re.compile(r'^Roots the target in place and causes \d+ Nature damage over (?P<duration>\d+) sec\. Damage caused may interrupt the effect\. .+$')
_COST = re.compile(r'^(?P<amount>\d+) Mana$')
_CD = re.compile(r'^(?P<amount>\d+) min cooldown$')


def source_reactive_control_actions(ir, *, class_key: str, level: int, db_path=None):
    path=Path(db_path or active_ability_db(DEFAULT_DB)).resolve()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute("SELECT spell_id,name,level_hint,raw_listview_json,source_url FROM spell_index WHERE class_key=? AND kind='abilities' AND level_hint BETWEEN 1 AND ? ORDER BY spell_id",(class_key,int(level))).fetchall()
    decoded=[]
    for r in rows:
        raw=json.loads(r['raw_listview_json'])
        if (raw.get('id')!=r['spell_id'] or raw.get('name')!=r['name'] or raw.get('level')!=r['level_hint']):
            raise ValueError('REACTIVE_CONTROL_SOURCE_IDENTITY_DRIFT:'+str(r['spell_id']))
        env=raw.get('envChange') or {}
        after=env.get('after') or {}
        decoded.append((r,after))
    known={sid for a in ir.actions for sid in _source_spell_ids(a)}
    actions=[];triggers=[];source_facts=[]
    # The P1/current-combat optimizer intentionally admits only the best
    # level-legal rank. Lower known ranks are retained in SQLite, not duplicated
    # as extra executable actions in the normal checkpoint frontier.
    best_by_family={}
    for candidate,tool in decoded:
        if not _REACTIVE.fullmatch(str(tool.get('text') or '')):
            continue
        name=str(candidate['name']).casefold()
        if name not in best_by_family or (int(candidate['level_hint']),int(candidate['spell_id'])) > (int(best_by_family[name]['level_hint']),int(best_by_family[name]['spell_id'])):
            best_by_family[name]=candidate
    for row,after in decoded:
        text=str(after.get('text') or '')
        match=_REACTIVE.fullmatch(text)
        if not match or best_by_family[str(row['name']).casefold()]['spell_id'] != row['spell_id']:
            continue
        sid=int(row['spell_id'])
        if sid in known:continue
        cost=_COST.fullmatch(str(after.get('cost') or ''))
        cd=_CD.fullmatch(str(after.get('cooldown') or ''))
        if not cost or not cd or after.get('cast')!='Instant' or after.get('name')!=row['name']:
            raise ValueError('UNPARSED_REACTIVE_CONTROL_COST_OR_COOLDOWN:'+str(sid))
        roots=[(r,other) for r,other in decoded if r['name']==match['name'] and
                str(other.get('rank'))=='Rank '+match['rank']]
        if len(roots)!=1:raise ValueError('REACTIVE_CONTROL_CHILD_RANK_UNRESOLVED:'+str(sid))
        root_row,root_tooltip=roots[0]
        root=_ROOT.fullmatch(str(root_tooltip.get('text') or ''))
        if root is None:raise ValueError('REACTIVE_CONTROL_CHILD_DURATION_UNRESOLVED:'+str(sid))
        # Reuse the existing source-compiled child action. The reactive root
        # must carry exactly the same damage-over-time and control rules as
        # a normally cast Root rank, never a free, damage-less approximation.
        child=[a for a in ir.actions if int(root_row['spell_id']) in _source_spell_ids(a)]
        if len(child)!=1:
            raise ValueError('REACTIVE_CONTROL_CHILD_ACTION_UNRESOLVED:'+str(sid))
        child_controls=[e for e in child[0].effects if isinstance(e,ControlEffect)]
        child_periodics=[e for e in child[0].effects if isinstance(e,PeriodicEffect)]
        if len(child_controls)!=1 or len(child_periodics)!=1:
            raise ValueError('REACTIVE_CONTROL_CHILD_EFFECTS_UNRESOLVED:'+str(sid))
        if abs(float(child_controls[0].duration_s)-float(root['duration']))>1e-9:
            raise ValueError('REACTIVE_CONTROL_CHILD_DURATION_DRIFT:'+str(sid))
        aura_id=f'source_reactive_control:{sid}'
        source={'authority':'canonical_forever_spell_index_after_tooltip',
                'source_spell_id':sid,'source_url':row['source_url'],
                'child_spell_id':int(root_row['spell_id']), 'child_source_url':root_row['source_url']}
        action=ActionDefinition(
            id=f'source_spell:{sid}',family_key=re.sub('[^a-z0-9]+','_',str(row['name']).lower()).strip('_'),
            name=row['name'],owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(row['level_hint'])},),
            costs=(ResourceCost(resource_id='mana',amount=float(cost['amount'])),),
            cast_time_s=0.,gcd_s=1.5,cooldown_s=float(cd['amount'])*60.,
            effects=(StatusAuraEffect('status_aura',aura_id,'actor',float(match['duration'])),),
            provenance=(source,),metadata={'source_spell_id':sid,'reactive_control':True},
        )
        trigger=TriggerDefinition(
            id=f'source_reactive_control:{sid}:trigger',name=row['name']+' reactive root',
            owner_actor_id=ir.actor.id,event_kind='damage_taken',
            required_aura_id=aura_id,event_probability_field='hit_chance',
            filters={'school':'physical','attack_delivery':'melee'},
            effects=(child_controls[0],child_periodics[0]),
            provenance=(source,),
            metadata={'consume_required_aura_on_trigger':True,'target_from_incoming_attacker':True},
        )
        actions.append(action);triggers.append(trigger)
        source_facts.append({'fact_kind':'source_reactive_control','source':source,
                'root_duration_s':float(root['duration']),'aura_duration_s':float(match['duration'])})
    if not actions:return ir
    permitted={a.id for a in actions}
    modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None
        else m.enabled_action_ids+tuple(sorted(permitted)))) for m in ir.modes)
    return replace(ir,actions=ir.actions+tuple(actions),triggers=ir.triggers+tuple(triggers),
                   source_facts=ir.source_facts+tuple(source_facts),modes=modes)

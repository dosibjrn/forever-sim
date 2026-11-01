"""Batch-executable *source index* L1-only simple single-effect casts.

Reuses the canonical SQLite atom ledger and production ActionDefinition/CombatRuntime.
No spell/class dispatch, inferred GCD, acquisition, target-hit or gear. Index-only
spell descriptions are NOT enough to authorize a L2 candidate. Conservative
whole-description grammar rejects composite spells and effects with unknown tails.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from src.game.data.forever.source_effect_atoms import read_effect_atom_coverage
from src.game.data.forever.source_partial_l1 import PartialSourceEvidenceError, bounded_actor_l1_probe_ir
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import ActionDefinition, ResourceCost, DamageEffect, HealEffect
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import execute_action

_N = r'\d+(?:\.\d+)?'
_S = r'(?:Arcane|Fire|Frost|Nature|Shadow|Holy)'
# Each template describes a single direct effect. Composite/conditional spell
# descriptions MUST NOT match. No class/spell identifiers appear in the grammar.
_PATTERNS = (
    ('school_damage_range', re.compile(
        rf'^(?:Causes?|Deals?|Inflicts?) (?P<lo>{_N}) to (?P<hi>{_N}) (?P<school>{_S}) damage (?:to (?:the|an) (?:target|enemy))?\.?$', re.I)),
    ('school_damage_range', re.compile(
        rf'^(?:Casts? a bolt of lightning at the target for|Blasts? (?:the|an) (?:target|enemy) for|Instantly blasts? the target for) (?P<lo>{_N}) to (?P<hi>{_N}) (?P<school>{_S}) damage\.?$', re.I)),
    ('school_damage_fixed', re.compile(
        rf'^(?:Causes?|Deals?|Inflicts?) (?P<lo>{_N}) (?P<school>{_S}) damage (?:to (?:the|an) (?:target|enemy))?\.?$', re.I)),
    ('school_damage_fixed', re.compile(
        rf'^An instant shot that causes (?P<lo>{_N}) (?P<school>{_S}) damage\.?$', re.I)),
    ('healing_range', re.compile(
        rf'^(?:Heals? a friendly target for|Heals? (?:your|the) target for|A slow casting spell that heals a single target for) (?P<lo>{_N}) to (?P<hi>{_N})\.?$', re.I)),
)
_COST = re.compile(rf'^({_N}) (Mana|Rage|Energy|Focus)$', re.I)
_CAST = re.compile(rf'^({_N}) sec cast$', re.I)


def source_index_single_l1_action(ir, *, class_key: str, spell_id: int,
                                  db_path: Path | str = DEFAULT_DB, execution_tier: str = 'L1'):
    """Return (ActionDefinition, provenance); reject any incomplete signature.

    Source authority is current canonical *listview* only. Even a matched whole
    tooltip does not establish proc semantics, acquisition, hit/crit, GCD or
    version parity with a separate spell-detail snapshot.
    """
    if execution_tier != 'L1':
        raise PartialSourceEvidenceError('INDEX_ONLY_ACTION_L2_L3_FORBIDDEN')
    if ir is None:
        raise PartialSourceEvidenceError('NO_GAME_IR')
    cls=str(class_key).lower()
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('''SELECT class_key,spell_id,name,level_hint,batch_id,
                                 source_url,raw_listview_json FROM spell_index
                          WHERE class_key=? AND spell_id=? AND kind='abilities' ''',
                       (cls,int(spell_id))).fetchone()
        if row is None:
            raise PartialSourceEvidenceError('UNKNOWN_INDEX_RANK')
        if row['level_hint'] is None or not 1 <= int(row['level_hint']) <= 60:
            raise PartialSourceEvidenceError('UNKNOWN_SOURCE_RANK_LEVEL')
        if int(row['level_hint'])>int(ir.actor.metadata.get('level',-1)):
            raise PartialSourceEvidenceError('RANK_EXCEEDS_SOURCE_ACTOR_LEVEL')
        proof=read_effect_atom_coverage(db,class_key=cls,spell_id=int(spell_id))
        if proof is None or proof['execution_status']!='BLOCKED_PARTIAL_EFFECT_EVIDENCE' or not proof['not_legal_for_L2']:
            raise PartialSourceEvidenceError('MISSING_FRESH_SOURCE_ATOM_PROOF')
        raw=json.loads(row['raw_listview_json'])
        if int(raw['id'])!=int(spell_id) or raw['name']!=row['name'] or raw.get('level')!=row['level_hint']:
            raise PartialSourceEvidenceError('INDEX_IDENTITY_OR_LEVEL_DRIFT')
        if (raw.get('envChange') or {}).get('status')=='removed':
            raise PartialSourceEvidenceError('REMOVED_SOURCE_ABILITY')
        after=(raw.get('envChange') or {}).get('after') or {}
        tooltip=' '.join(str(after.get('text') or '').replace('\xa0',' ').split())
        if not tooltip:
            raise PartialSourceEvidenceError('NO_SOURCE_INDEX_EFFECT_TOOLTIP')
        cast_text=str(after.get('cast') or '').strip()
        if cast_text.lower()=='instant':cast_s=0.
        else:
            match=_CAST.fullmatch(cast_text)
            if match is None:raise PartialSourceEvidenceError('UNKNOWN_INDEX_CAST_TIME')
            cast_s=float(match[1])
        cost_text=str(after.get('cost') or '').strip()
        cost_match=_COST.fullmatch(cost_text)
        if cost_match is None:
            raise PartialSourceEvidenceError('UNKNOWN_SOURCE_INDEX_RESOURCE_COST')
        amount=float(cost_match[1]);resource=cost_match[2].lower()
        available={r.id for r in ir.resources if r.owner_actor_id==ir.actor.id}
        if resource not in available:
            raise PartialSourceEvidenceError('MISSING_SOURCE_ACTOR_COST_RESOURCE')
        matched=[(kind,pattern.fullmatch(tooltip)) for kind,pattern in _PATTERNS]
        matches=[(kind,m) for kind,m in matched if m is not None]
        if len(matches)!=1:
            raise PartialSourceEvidenceError('COMPOSITE_OR_UNRECOGNIZED_INDEX_TOOLTIP')
        kind,m=matches[0]
        atoms=[a for a in proof['atoms'] if a['kind']==kind]
        if len(proof['atoms'])!=1 or len(atoms)!=1:
            raise PartialSourceEvidenceError('COMPOSITE_OR_MISSING_ATOM')
        atom=atoms[0]['values'];v=m.groupdict()
        lo=float(v['lo']);hi=float(v.get('hi') or lo)
        if hi<lo or lo<0 or amount<0:
            raise PartialSourceEvidenceError('INVALID_INDEX_NUMERIC_VALUE')
        if kind=='healing_range':
            if 'health' not in available:raise PartialSourceEvidenceError('MISSING_HEALTH_RESOURCE')
            if (atom['min'],atom['max'])!=(lo,hi):raise PartialSourceEvidenceError('INDEX_ATOM_HEAL_VALUE_DRIFT')
        else:
            if ((atom.get('min',atom.get('amount')),atom.get('max',atom.get('amount')))!=(lo,hi)
                    or atom['school']!=v['school'].lower()):
                raise PartialSourceEvidenceError('INDEX_ATOM_DAMAGE_VALUE_DRIFT')
        provenance={'class_key':cls,'spell_id':int(spell_id),'source_url':row['source_url'],
                    'source_index_batch':row['batch_id'],
                    'source_index_sha256':hashlib.sha256(row['raw_listview_json'].encode()).hexdigest(),
                    'source_text_sha256':hashlib.sha256(tooltip.encode()).hexdigest(),
                    'source_authority':'canonical_index_patch_after_not_verified_detail',
                    'full_description_grammar':'single_direct_effect_strict',
                    'L2_acquisition_hit_crit_GCD_and_version_legality':'UNVERIFIED'}
        if kind=='healing_range':
            effect=HealEffect(effect_type='heal',target='self',resource_id='health',
                base_min=lo,base_max=hi,unsupported_semantics=({'semantic':'heal_target_and_coefficients',
                                  'status':'not_verified_for_L2'},))
        else:
            effect=DamageEffect(effect_type='damage',school=atom['school'],target='enemy',
                base_min=lo,base_max=hi,unsupported_semantics=({'semantic':'hit_crit_resist_and_coefficients',
                                  'status':'not_verified_for_L2'},))
        action=ActionDefinition(id=f'L1_INDEX_SINGLE:{cls}:{spell_id}',family_key=f'index_single:{cls}:{spell_id}',
            name=row['name'],owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(row['level_hint'])},),
            costs=(ResourceCost(resource_id=resource,amount=amount),),
            cast_time_s=cast_s,gcd_s=0.,cooldown_s=0.,effects=(effect,),
            provenance=(provenance,),metadata={'execution_tier':'L1_SOURCE_INDEX_ONLY',
                'never_l2_legal':True,'source_spell_id':int(spell_id),
                'index_describes_one_direct_effect':True,'unknown_GCD_probed_zero_not_game_fact':True,
                'unknown_acquisition_and_gameplay_effects':True})
        return action,provenance


def probe_index_single_l1(ir, *, class_key: str, spell_id: int,
                          db_path: Path | str = DEFAULT_DB):
    action,proof=source_index_single_l1_action(ir,class_key=class_key,spell_id=spell_id,db_path=db_path)
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    for cost in action.costs:
        if not actor.can_spend(cost.resource_id,cost.amount):
            raise PartialSourceEvidenceError('INSUFFICIENT_ACTOR_RESOURCE')
    target=TargetState.with_health('L1_index_probe',1000000.)
    result=execute_action(action=action,actor=actor,target=target,spell_power=0.,allow_source_partial_l1=True)
    return {'class_key':class_key,'spell_id':int(spell_id),'action_id':action.id,
            'damage':result.total_damage,'healing_requested':sum(float(x.payload.get('amount',0.))
                for x in result.events if x.kind=='Heal'),
            'event_count':len(result.events),'actual_cost':sum(float(c.amount) for c in action.costs),
            'source':proof,'status':'EXECUTED_SOURCE_INDEX_SINGLE_L1_NOT_L2',
            'L2_eligible':False,'checkpoint_accepted':False}

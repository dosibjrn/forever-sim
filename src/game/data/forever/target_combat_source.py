from __future__ import annotations
"""Canonical, qualified enemy armor/hit profile and sourced target debuff compiler.

No game constants or class/spell IDs in runtime or optimizer. The ordinary
melee target is a CMaNGOS CLASSIC proxy, not a Forever server observation.
"""
from dataclasses import replace
from math import isfinite
from pathlib import Path
import sqlite3
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model.ir import ActionDefinition, ResourceCost, TargetStatDebuffEffect


def load_target_combat_profile(level: int, *, db_path: Path | None = None,
                               scenario_key: str = 'ordinary_melee_classic_proxy') -> dict:
    """Read the *same* qualified, source-versioned target row for legacy and IR.

    An unknown level/profile is a hard coverage error, never zero armor or
    100% hit. This does not certify the Classic proxy as Forever server truth.
    """
    path=Path(db_path or DEFAULT_DB)
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        profile=c.execute('''SELECT * FROM outgoing_combat_profile_source_facts
            WHERE scenario_key=? AND level=?''',(scenario_key,int(level))).fetchone()
    if profile is None:
        raise ValueError(f'no sourced enemy armor/hit profile for level {level}')
    profile=dict(profile)
    if (not all(profile[k] for k in ('target_armor_source','hit_source','mitigation_source','capture_id','source_status'))
        or not all(isfinite(float(profile[k])) for k in ('target_armor','melee_hit','spell_hit','armor_constant','reduction_cap'))
        or float(profile['target_armor'])<0 or float(profile['armor_constant'])<=0
        or not 0<float(profile['melee_hit'])<=1 or not 0<float(profile['spell_hit'])<=1
        or not 0<float(profile['reduction_cap'])<=1):
        raise ValueError('invalid sourced target combat profile')
    return profile


def physical_outgoing_expected_factors(level: int, *, db_path: Path | None = None) -> dict:
    """Shared source profile for direct physical expected-value scoring.

    Bleed ticks bypass armor; attack/application hit is modeled separately.
    """
    p=load_target_combat_profile(level,db_path=db_path)
    reduction=min(float(p['reduction_cap']),float(p['target_armor'])/
                  (float(p['target_armor'])+float(p['armor_constant'])))
    return {'direct_multiplier':float(p['melee_hit'])*(1.0-reduction),
            'application_hit':float(p['melee_hit']),
            'armor_reduction':reduction,
            'target_armor':float(p['target_armor']),
            'capture_id':str(p['capture_id']),
            'source_status':str(p['source_status'])}


def source_enrich_target_combat(ir, *, db_path: Path | None = None):
    if 'target_combat_profile' in ir.provenance:
        raise ValueError('target combat source applied twice')
    path=Path(db_path or DEFAULT_DB)
    profile=load_target_combat_profile(int(ir.actor.metadata['level']),db_path=path)
    level=int(ir.actor.metadata['level'])
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute('''SELECT * FROM target_armor_debuff_source_facts
            WHERE class_key=? AND required_level<=? ORDER BY family_key,rank DESC''',
            (str(ir.actor.metadata['class_key']).lower(),level)).fetchall()
    selected={}
    for row in rows:
        selected.setdefault(row['family_key'],dict(row))
    new=[]; modes={m.id:m for m in ir.modes}
    for fact in selected.values():
        if (not fact['source_url'] or not fact['capture_id'] or not fact['source_build']
            or not isfinite(float(fact['armor_delta'])) or float(fact['armor_delta'])<=0
            or float(fact['duration_s'])<=0 or float(fact['mana_cost'])<0):
            raise ValueError('invalid sourced target armor debuff')
        allowed=set(str(fact['allowed_modes']).split(','))
        if not allowed or not allowed.issuperset(modes):
            raise ValueError('sourced target debuff does not cover existing modes')
        provenance={'source_url':fact['source_url'],'capture_id':fact['capture_id'],
                    'source_build':fact['source_build'],'spell_id':fact['spell_id']}
        new.append(ActionDefinition(
            id=f"source_spell:{fact['spell_id']}", family_key=str(fact['family_key']),
            name=str(fact['family_key']).replace('_',' ').title(), owner_actor_id=ir.actor.id,
            requirements=({'kind':'minimum_level','value':int(fact['required_level'])},),
            costs=(ResourceCost(resource_id='mana',amount=float(fact['mana_cost'])),),
            cast_time_s=0.,gcd_s=float(fact['gcd_s']),cooldown_s=0.,
            effects=(TargetStatDebuffEffect(effect_type='target_stat_debuff',
                aura_id=f"source_target_debuff:{fact['family_key']}",target_stat_id='armor',
                delta=-float(fact['armor_delta']),duration_s=float(fact['duration_s']),
                provenance=(provenance,)),),provenance=(provenance,),
            metadata={'source_spell_rank':fact['rank'],'source_semantic_type':'target_stat_debuff',
                      'source_caveat':'stealth_lock_not_modeled'}))
    existing={a.id for a in ir.actions}
    existing_families={a.family_key for a in ir.actions}
    if any(a.id in existing or a.family_key in existing_families for a in new):
        raise ValueError('duplicate sourced debuff action or family')
    new_modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else
        m.enabled_action_ids+tuple(a.id for a in new if m.id in set(
            next(x['allowed_modes'] for x in selected.values() if x['spell_id']==int(a.id.split(':')[-1])).split(',')))))
        for m in ir.modes)
    return replace(ir,actions=ir.actions+tuple(new),modes=new_modes,
        provenance={**dict(ir.provenance),'target_combat_profile':profile,
                    'source_target_debuffs':[a.id for a in new]})


def target_combat_metadata(ir):
    profile=ir.provenance.get('target_combat_profile')
    if not profile:
        raise ValueError('source target combat profile absent')
    return {'armor':float(profile['target_armor']),
            'melee_hit':float(profile['melee_hit']),
            'spell_hit':float(profile['spell_hit']),
            'armor_constant':float(profile['armor_constant']),
            'armor_reduction_cap':float(profile['reduction_cap']),
            'combat_source_status':profile['source_status'],
            'combat_capture_id':profile['capture_id']}

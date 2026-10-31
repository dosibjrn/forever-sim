"""WoW Forever source item combat stats: displayed chance % and Defense skill.

The canonical item SQLite preserves *raw client/item-listview stat amounts*;
these are not displayed percentages. The same item's Forever display gives:
  Fletcher's Gloves (#7348): 14 raw crit => +1% crit
  Sageblade (#22383):          10 raw hit  => +1% hit
  Mithril Plate Pants (#7920): 12 raw dodge => +1% dodge
  Ring of Defense (#12985):    4 raw defense => +4 Defense skill
Sources: https://theforeverera.com/en/recipes/leatherworking/fletchers-gloves/
         https://theforeverera.com/en/items/22383/
         https://theforeverera.com/en/items/7920/
         https://theforeverera.com/en/items/12985/

This adapter does NOT use level-scaled TBC rating coefficients. Its display
normalization is sourced for item stats; the 0.04%-per-Defense-skill mechanics
are historical Classic assumptions pending Forever-specific verification.
Missing parry/block/crit-suppression execution is explicitly recorded.
"""
from __future__ import annotations
from dataclasses import replace
from math import isfinite
import sqlite3
from .sqlite_talents import DEFAULT_DB

SOURCE_STATUS='FOREVER_ITEM_SOURCE_RAW_TO_DISPLAY_PERCENT_70338'
DISPLAY_RAW_PER_ONE_PERCENT={'crit':14.0,'hit':10.0,'dodge':12.0}
# One sourced item chance contributes to both execution channels.
_UNIFIED_ITEM_CHANCE_CHANNELS={
    'crit':('melee_crit_chance','spell_crit_chance'),
    'hit':('melee_hit_bonus','spell_hit_bonus'),
}
DISPLAY_SOURCE_URLS={
 'crit':'https://theforeverera.com/en/recipes/leatherworking/fletchers-gloves/',
 'hit':'https://theforeverera.com/en/items/22383/',
 'dodge':'https://theforeverera.com/en/items/7920/',
 'defense':'https://theforeverera.com/en/items/12985/',
}
DEFENSE_MECHANIC_SOURCE='https://warcraft.wiki.gg/wiki/Defense'


def _unified_chance_scope_fact(stat: str):
    """Fail closed unless the canonical Forever database pins chance scope."""
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro', uri=True) as db:
        row=db.execute('SELECT scope,source_url FROM unified_combat_chance_scope_facts '
                       "WHERE stat_key=?",(stat,)).fetchone()
    if not row or row[0] != 'spell_melee_ranged' or not row[1]:
        raise ValueError('MISSING_CANONICAL_UNIFIED_CHANCE_SCOPE')
    return {'scope':row[0],'source_url':row[1]}


def displayed_percent_from_raw(stat:str,raw:float)->float:
    """Displayed percentage *points*, e.g. 14 crit => +1.0%."""
    if stat not in DISPLAY_RAW_PER_ONE_PERCENT: raise ValueError('NOT_A_DISPLAY_PERCENT_ITEM_STAT')
    if not isfinite(float(raw)): raise ValueError('NONFINITE_ITEM_STAT')
    return float(raw)/DISPLAY_RAW_PER_ONE_PERCENT[stat]


def forever_display_chance_fraction_per_raw_point(stat:str,level:int|None=None):
    """Raw-item point -> combat chance fraction; deliberately level invariant."""
    if stat == 'defense': return None
    if stat not in DISPLAY_RAW_PER_ONE_PERCENT: raise ValueError('UNKNOWN_SOURCE_ITEM_STAT')
    if level is not None and not (1<=int(level)<=60):raise ValueError('BAD_FOREVER_LEVEL')
    return 0.01/DISPLAY_RAW_PER_ONE_PERCENT[stat]


def source_item_stat_to_combat(stat:str,raw:float,*,level:int)->dict:
    if stat not in {'crit','hit','dodge','defense'}:raise ValueError('UNKNOWN_SOURCE_ITEM_STAT')
    if not 1<=int(level)<=60:raise ValueError('BAD_FOREVER_LEVEL')
    if not isfinite(float(raw)):raise ValueError('NONFINITE_ITEM_STAT')
    raw=float(raw)
    unified_source=None
    if stat=='defense':
        chance=raw*.0004  # +1 Defense skill -> +0.04 percentage point each (Classic model)
        changes={'incoming_miss_chance_bonus':chance,'dodge_chance':chance}
        not_yet=('parry_chance','block_chance','incoming_crit_suppression',
                 'weapon_skill_level_difference_and_client_rounding')
        displayed={'unit':'defense_skill','amount':raw}
        mechanic_status='CLASSIC_DEFENSE_AVOIDANCE_PARTIAL_FOREVER_UNVERIFIED'
    else:
        fraction=forever_display_chance_fraction_per_raw_point(stat,level)*raw
        if stat in _UNIFIED_ITEM_CHANCE_CHANNELS:
            unified_source=_unified_chance_scope_fact(stat)
            changes={channel:fraction for channel in _UNIFIED_ITEM_CHANCE_CHANNELS[stat]}
        else:
            changes={'dodge_chance':fraction}
        not_yet=()
        displayed={'unit':'percentage_points','amount':displayed_percent_from_raw(stat,raw)}
        mechanic_status='SOURCE_DISPLAY_MAPPING_AND_EXECUTOR_CHANCE'
    return {'source_stat':stat,'raw_item_amount':raw,'level':int(level),
        'displayed':displayed,'channel_deltas':changes,'unmodeled_channels':not_yet,
        'status':SOURCE_STATUS,'mechanic_status':mechanic_status,
        'source_urls':[DISPLAY_SOURCE_URLS[stat]]+([DEFENSE_MECHANIC_SOURCE] if stat=='defense' else [])+([unified_source['source_url']] if unified_source is not None else []),
        'uses_tbc_level_scaled_rating':False}


def apply_source_item_stat_delta(ir,stat:str,raw:float,*,level:int):
    evidence=source_item_stat_to_combat(stat,raw,level=level)
    stats=dict(ir.actor.base_stats)
    for key,delta in evidence['channel_deltas'].items():
        stats[key]=float(stats.get(key,0.) or 0.)+float(delta)
    meta=dict(ir.provenance)
    meta['source_item_combat_stat_probes']=list(meta.get('source_item_combat_stat_probes',()))+[evidence]
    return replace(ir,actor=replace(ir.actor,base_stats=stats),provenance=meta)


def apply_source_equipped_item_stats(ir,*,class_key:str,level:int,item_ids):
    """Apply item statistics from canonical SQLite; no item-ID runtime switches."""
    from src.rulesets.forever.items.runtime_selection import available_items
    rows={int(row.item_id):row for row in available_items(class_key,level,required_level_policy='observed')}
    ids=tuple(int(i) for i in item_ids)
    if len(set(ids))!=len(ids):raise ValueError('DUPLICATE_EQUIPPED_ITEM')
    totals={key:0. for key in ('crit','hit','dodge','defense')}
    for item_id in ids:
        if item_id not in rows:raise ValueError('SOURCE_ITEM_NOT_LEGAL_IN_CATALOGUE')
        for stat in totals: totals[stat]+=float(getattr(rows[item_id],stat) or 0.)
    changed=ir
    for stat,raw in totals.items():
        if raw:changed=apply_source_item_stat_delta(changed,stat,raw,level=level)
    meta=dict(changed.provenance)
    meta['source_equipped_item_combat_stats']={
        'status':SOURCE_STATUS,'item_ids':list(ids),'raw_totals':totals,
        'displayed_crit_pct':displayed_percent_from_raw('crit',totals['crit']),
        'displayed_hit_pct':displayed_percent_from_raw('hit',totals['hit']),
        'displayed_dodge_pct':displayed_percent_from_raw('dodge',totals['dodge']),
        'defense_skill':totals['defense'],
        'complete_Forever_L2':False,
        'limitations':['defense_parry_block_crit_suppression_not_executed',
                       'source_item_procs_and_spell_crit_multiplier_fidelity_not_fully_verified']}
    return replace(changed,provenance=meta)

# Retained names for older call-sites, but the semantics are corrected: raw
# item values are normalized to display percentages, NEVER level-scaled TBC.
def rating_to_chance(stat:str,rating:float,*,level:int):
    return source_item_stat_to_combat(stat,rating,level=level)
def apply_provisional_rating_delta(ir,stat:str,rating:float,*,level:int):
    return apply_source_item_stat_delta(ir,stat,rating,level=level)
def apply_provisional_equipped_rating_items(ir,*,class_key:str,level:int,item_ids):
    return apply_source_equipped_item_stats(ir,class_key=class_key,level=level,item_ids=item_ids)

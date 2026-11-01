"""Generic sourced numeric item fields not covered by canonical aggregate gear.

The listview field names below are the *source* schema, not inferred TBC
rating conversions. Effects are applied to the actor's stat channels already
consumed by CombatRuntime. Target/encounter context controls their value.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

# School-specific resistance is distinct from `resistance_all` (e.g. Rune of
# Duty). No item IDs or class-specific conditionals are in this schema bridge.
NUMERIC_EXTRA_TO_ACTOR_STAT = {
    'arcres': 'resistance_arcane',
    'firres': 'resistance_fire',
    'frores': 'resistance_frost',
    'holres': 'resistance_holy',
    'natres': 'resistance_nature',
    'splpen': 'spell_penetration',
    # Forever listview `healthrgn` = health restored every FIVE seconds,
    # corroborated by 4 Forever item tooltips (WF347 source evidence).
    # This is a passive equipment stat, including in-combat recovery; it is
    # NOT the ordinary Spirit-dependent out-of-combat health regeneration.
    'healthrgn': 'health_regeneration_per_5s',
}


def modeled_source_numeric_extras(item) -> dict[str, float]:
    """Return executable source stat additions, without any hidden rating conversion.

    For a tooltip-confirmed all-resistance conditional passive, the generic
    listview may contain the *maximum* biome value in each school column. That
    value must not be counted as a second, unconditional bonus.
    """
    from .source_equipment_semantics import semantic_for_item
    semantic = semantic_for_item(item)
    source_all_resistance = bool(semantic and any(
        kind == 'add_actor_stat' and stat == 'resistance_all'
        for kind, stat, _ in semantic.typed_effects))
    values = {}
    for source_key, stat in NUMERIC_EXTRA_TO_ACTOR_STAT.items():
        value = float(item.extra_stats.get(source_key, 0.) or 0.)
        if not isfinite(value) or value < 0:
            raise ValueError('INVALID_SOURCE_NUMERIC_EXTRA:' + source_key)
        if value == 0:
            continue
        if source_all_resistance and source_key in {
            'arcres', 'firres', 'frores', 'holres', 'natres'
        }:
            # The already-source-typed resistance_all + environment conditional
            # is authoritative. Do not duplicate maximum-listview stats.
            continue
        values[stat] = values.get(stat, 0.) + value
    return values


def apply_source_numeric_extras(ir, *, class_key: str, level: int, item_ids):
    from .runtime_selection import available_items
    from .source_equipment_semantics import validate_equipped_item_ids
    ids = tuple(int(i) for i in item_ids)
    validate_equipped_item_ids(ids)
    by_id = {int(i.item_id): i for i in available_items(
        class_key, level, required_level_policy='observed')}
    stats = dict(ir.actor.base_stats)
    evidence = []
    for iid in ids:
        if iid not in by_id:
            raise ValueError('EQUIPPED_SOURCE_NUMERIC_EXTRA_ITEM_NOT_LEGAL')
        item = by_id[iid]
        for stat, value in modeled_source_numeric_extras(item).items():
            stats[stat] = stats.get(stat, 0.) + value
            evidence.append({'item_id': iid, 'stat': stat, 'source_value': value,
                             'source_url': item.source_url, 'channel': 'canonical_listview_numeric_extra'})
    if not evidence:
        return ir
    return replace(ir, actor=replace(ir.actor, base_stats=stats),
                   provenance={**ir.provenance, 'source_numeric_extra_effects': evidence})

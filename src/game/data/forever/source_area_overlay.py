"""Source-attested actor-centered area semantics for generic hostile GameIR effects.

The spell/radius mapping is data in the selected canonical SQLite snapshot,
not a class, family or spell-name branch in either IR or CombatRuntime.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite
import sqlite3

from src.game.model import ControlEffect, DamageEffect
from .source_db_scope import active_ability_db
from .sqlite_talents import DEFAULT_DB
from .source_indexed_action_coverage import _source_spell_ids


def source_enrich_area_actions(ir):
    if ir is None:
        return None
    with sqlite3.connect(active_ability_db(DEFAULT_DB)) as db:
        has_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                               "AND name='verified_spell_area_facts'").fetchone()
        if not has_table:
            return ir
        facts = {}
        for sid, radius, center, url, build in db.execute(
                'SELECT spell_id,radius_yards,center,source_url,source_build '
                'FROM verified_spell_area_facts'):
            if (not isinstance(sid, int) or sid <= 0 or not isfinite(float(radius))
                    or float(radius) <= 0 or center != 'actor'
                    or not str(url).startswith('https://') or not str(build).strip()):
                raise ValueError('INVALID_VERIFIED_SOURCE_AREA_FACT')
            facts[int(sid)] = {'spell_id': int(sid), 'radius_yards': float(radius),
                               'center': center, 'source_url': str(url),
                               'source_build': str(build)}
    actions = []
    evidence = []
    for action in ir.actions:
        ids = _source_spell_ids(action) & set(facts)
        if not ids:
            actions.append(action)
            continue
        if len(ids) != 1:
            raise ValueError('AMBIGUOUS_VERIFIED_SOURCE_AREA_FACT')
        fact = facts[next(iter(ids))]
        effects = []
        for effect in action.effects:
            if getattr(effect, 'target', None) == 'enemy':
                if not isinstance(effect, (DamageEffect, ControlEffect)):
                    raise ValueError('SOURCE_AREA_UNSUPPORTED_HOSTILE_EFFECT')
                effects.append(replace(effect, target='enemies'))
            else:
                effects.append(effect)
        if not any(getattr(e, 'target', None) == 'enemies' for e in effects):
            raise ValueError('SOURCE_AREA_HAS_NO_HOSTILE_EFFECTS')
        actions.append(replace(action, effects=tuple(effects),
            metadata={**action.metadata, 'aoe_center': fact['center'],
                      'aoe_radius_yards': fact['radius_yards'],
                      'aoe_source': dict(fact)}))
        evidence.append({'fact_kind': 'verified_spell_area', **fact, 'action_id': action.id})
    return replace(ir, actions=tuple(actions), source_facts=(*ir.source_facts, *evidence))

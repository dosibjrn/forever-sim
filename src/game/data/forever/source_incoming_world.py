"""Generic canonical-SQLite world incoming-attack scenario projection.

Applies only when an IR has no incoming attack of its own. The world-mob
numbers are qualified Classic proxies, not discovered Forever NPC facts.
"""
from __future__ import annotations
from dataclasses import replace
import sqlite3
from .sqlite_talents import DEFAULT_DB
from src.game.model.ir import ArmorMitigationDefinition, IncomingAttackDefinition


def source_enrich_incoming_world(ir):
    if ir.incoming_attacks:
        return ir  # Preserve already sourced class-specific encounter scenario.
    if 'health' not in {r.id for r in ir.resources}:
        return ir
    level=int(ir.actor.metadata['level'])
    with sqlite3.connect(f'file:{DEFAULT_DB}?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT * FROM world_incoming_scenario_facts WHERE level=?',(level,)).fetchone()
    if row is None:
        return ir  # Do not invent a source scenario for an unsupported level.
    if (float(row['raw_damage'])<=0 or float(row['swing_s'])<=0 or
        float(row['armor_constant'])<=0 or not row['capture_id']):
        raise ValueError('invalid canonical world incoming scenario')
    ref=({'authority':row['authority'],'source_url':row['source_url'],
          'capture_id':row['capture_id'],'scenario_status':'qualified_classic_proxy'},)
    mitigation=ArmorMitigationDefinition(id=f'world:armor:{level}',school='physical',
        armor_stat_id='armor',armor_constant=float(row['armor_constant']),
        reduction_cap=float(row['reduction_cap']),provenance=ref)
    attack=IncomingAttackDefinition(id=f'world:ordinary_melee:{level}',
        name='Qualified ordinary world melee',source_actor_id='ordinary_world_mob',
        target_actor_id=ir.actor.id,school='physical',raw_damage=float(row['raw_damage']),
        hit_chance=1.,health_resource_id='health',mitigation_rule_id=mitigation.id,
        provenance=ref,metadata={'representative_swing_s':float(row['swing_s']),
          'scenario_status':'qualified_classic_proxy',
          'melee_ap_per_dps':14.,
          'melee_ap_per_dps_source':'classic_melee_attack_power_per_dps_14'})
    # Unverified naked Armor is an explicit zero proxy; named gear Armor
    # contributes its sourced delta through the shared gear engine.
    actor=ir.actor if 'armor' in ir.actor.base_stats else replace(ir.actor,
        base_stats={**ir.actor.base_stats,'armor':0.},
        provenance=ir.actor.provenance+({'authority':'qualified_naked_armor_zero_proxy'},))
    return replace(ir,actor=actor,mitigation_rules=(*ir.mitigation_rules,mitigation),
        incoming_attacks=(*ir.incoming_attacks,attack),
        provenance={**ir.provenance,'world_incoming_source':dict(row)})

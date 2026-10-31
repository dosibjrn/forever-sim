"""Whole-action *partial* L1 probes from multiple canonical source-index atoms.

This is NOT an action discovery backend.  It joins independently observed
fragments into ONE paid cast through the existing GameIR/CombatRuntime, so a
source tooltip's direct hit and DoT are not counted as two free actions.
Only a supported, unambiguous set of atoms may be composed.  All unknown
mechanics, including index-only periodic timing, remain L2/L3 blockers.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

from src.game.data.forever.source_effect_atoms import read_effect_atom_coverage
from src.game.data.forever.source_partial_l1 import (
    PartialSourceEvidenceError, partial_source_action,
)
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import execute_action

# Mapping of generic source atom types to existing *fragment* adapters.
# No class, spell, rank, or talent IDs appear in the compiler.
FRAGMENTS = {
    'school_damage_range': 'direct_damage',
    'school_damage_fixed': 'direct_damage',
    'healing_range': 'direct_heal',
    'periodic_school_damage': 'periodic_total',
    'periodic_damage': 'periodic_total',
    'resource_gain': 'resource_gain',
    'damage_absorption': 'damage_absorption',
    'actor_attack_power_increase': 'actor_attack_power_aura',
    'target_armor_reduction': 'target_armor_debuff',
}


def source_index_composite_l1_action(ir, *, class_key: str, spell_id: int,
                                      db_path: Path | str = DEFAULT_DB,
                                      execution_tier: str = 'L1'):
    if execution_tier != 'L1':
        raise PartialSourceEvidenceError('COMPOSITE_INDEX_L2_L3_FORBIDDEN')
    if ir is None:
        raise PartialSourceEvidenceError('MISSING_EXISTING_GAME_IR')
    cls = str(class_key).lower()
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT name,level_hint,raw_listview_json FROM spell_index
            WHERE class_key=? AND spell_id=? AND kind='abilities' ''',
            (cls, int(spell_id))).fetchone()
        if row is None:
            raise PartialSourceEvidenceError('UNKNOWN_INDEXED_SPELL')
        if row['level_hint'] is None or not 1 <= int(row['level_hint']) <= 60:
            raise PartialSourceEvidenceError('UNKNOWN_SOURCE_RANK_LEVEL')
        actor_level = int(ir.actor.metadata.get('level', -1))
        if int(row['level_hint']) > actor_level:
            raise PartialSourceEvidenceError('INDEX_RANK_EXCEEDS_ACTOR_LEVEL')
        import json
        raw = json.loads(row['raw_listview_json'])
        if (int(raw.get('id',-1)) != int(spell_id) or
            raw.get('name') != row['name'] or raw.get('level') != row['level_hint']):
            raise PartialSourceEvidenceError('INDEX_IDENTITY_OR_LEVEL_DRIFT')
        if (raw.get('envChange') or {}).get('status') == 'removed':
            raise PartialSourceEvidenceError('REMOVED_SOURCE_ABILITY')
        proof = read_effect_atom_coverage(db, class_key=cls, spell_id=int(spell_id))
        if proof is None or proof['execution_status'] != 'BLOCKED_PARTIAL_EFFECT_EVIDENCE' or not proof['not_legal_for_L2']:
            raise PartialSourceEvidenceError('MISSING_FRESH_SOURCE_ATOM_PROOF')
        if proof['source_authority'] != 'source_index_listview':
            # A verified detail page can disagree with the index-change tooltip.
            # It has a separate, more authoritative full-slot composer already.
            # Never mix detail effect amounts with listview cost/cast and then
            # mislabel that hybrid as an index-only multi-atom cast.
            raise PartialSourceEvidenceError('USE_EXISTING_VERIFIED_DETAIL_COMPOSER')
        atoms = proof['atoms']
        if len(atoms) < 2:
            raise PartialSourceEvidenceError('NOT_A_MULTI_ATOM_SOURCE_ACTION')
        unknown = sorted({atom['kind'] for atom in atoms if atom['kind'] not in FRAGMENTS})
        if unknown:
            raise PartialSourceEvidenceError('UNSUPPORTED_COMPOSITE_ATOMS:' + ','.join(unknown))
        kinds = [FRAGMENTS[a['kind']] for a in atoms]
        # partial_source_action selects exactly one matching atom of each kind.
        # Ambiguous duplicate damage/heal effects require a distinct semantic
        # reducer, never an arbitrary first-match or free extra attack.
        if len(set(kinds)) != len(kinds):
            raise PartialSourceEvidenceError('AMBIGUOUS_DUPLICATE_COMPOSITE_FRAGMENT')
    parts = []
    for kind in kinds:
        action, evidence = partial_source_action(
            ir, class_key=cls, spell_id=int(spell_id), db_path=db_path,
            execution_tier='L1', fragment_kind=kind)
        if len(action.effects) != 1:
            raise PartialSourceEvidenceError('PARTIAL_ADAPTER_DID_NOT_RETURN_ONE_EFFECT')
        parts.append((action, evidence))
    primary = parts[0][0]
    for action, _ in parts[1:]:
        if (action.owner_actor_id != primary.owner_actor_id or
            action.costs != primary.costs or action.cast_time_s != primary.cast_time_s or
            action.gcd_s != primary.gcd_s or action.cooldown_s != primary.cooldown_s or
            action.requirements != primary.requirements):
            raise PartialSourceEvidenceError('COMPOSITE_SOURCE_COST_CAST_OR_LEVEL_DRIFT')
    combined = replace(primary,
        id=f'L1_INDEX_COMPOSITE:{cls}:{int(spell_id)}',
        family_key=f'index_composite:{cls}:{int(spell_id)}',
        effects=tuple(a.effects[0] for a, _ in parts),
        metadata={**primary.metadata,
            'execution_tier': 'L1_COMPOSITE_INDEX_PARTIAL_ONLY',
            'never_l2_legal': True,
            'source_spell_id': int(spell_id),
            'source_index_atom_count': len(atoms),
            'source_index_atom_kinds': tuple(a['kind'] for a in atoms),
            'source_residual_unverified': proof['residual_text'],
            'periodic_schedule_is_terminal_tick_proxy': 'periodic_total' in kinds,
            'source_composite_not_complete_gameplay_semantics': True,
            'cost_is_charged_once_for_entire_action': True,
        })
    return combined, {
        'class_key': cls, 'spell_id': int(spell_id),
        'source_authority': proof['source_authority'],
        'source_index_atom_count': len(atoms),
        'composed_fragment_kinds': kinds,
        'source_residual_unverified': proof['residual_text'],
        'all_unknown_gameplay_semantics_block_L2': True,
        'partial_not_l2': True,
    }


def probe_index_composite_l1(ir, *, class_key: str, spell_id: int,
                              db_path: Path | str = DEFAULT_DB):
    action, evidence = source_index_composite_l1_action(
        ir, class_key=class_key, spell_id=spell_id, db_path=db_path)
    actor = ActorState.from_ir(ir.actor, ir.resources, ())
    for cost in action.costs:
        if not actor.can_spend(cost.resource_id, cost.amount):
            raise PartialSourceEvidenceError('INSUFFICIENT_ACTOR_RESOURCE')
    target = TargetState.with_health('L1_composite_index_probe', 1_000_000.)
    result = execute_action(action=action, actor=actor, target=target,
                            spell_power=0., allow_source_partial_l1=True)
    return {**evidence,
        'action_id': action.id, 'status': 'EXECUTED_COMPOSITE_INDEX_L1_NOT_L2',
        'damage': result.total_damage,
        'elapsed_s_including_terminal_periodic_proxy': result.elapsed_s,
        'events': len(result.events),
        'resource_before': result.resources_before,
        'resource_after': result.resources_after,
        'source_spell_paid_casts': 1,
        'L2_eligible': False, 'checkpoint_accepted': False,
    }

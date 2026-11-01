"""Fail-closed audit of source observations against generic IR capabilities.

Candidate execution kind is informative, NOT proof of matching semantics. Never
promote source observations to runnable IR without a complete independent proof.
"""
from __future__ import annotations

from pathlib import Path

from src.game.runtime.effect_capabilities import registered_effect_types, effect_capability
from src.v2.source_sqlite_spell_semantics import extract_verified_semantic_observations

# Generic interpretation vocabulary, not spell/class/game facts. These are
# *potential* IR kinds; actual semantics still require independent proof.
_OBSERVATION_KIND_CANDIDATES = {
    'direct_school_damage_range': 'direct_damage',
    'periodic_school_damage_description': 'periodic_damage',
    'periodic_heal_description': 'periodic_heal',
    'movement_slow_description': 'control',
    'school_interrupt_lockout_description': 'control',
    'resource_gain_description': 'resource_change',
}


def audit_semantic_completeness(header: dict, semantic: dict) -> dict:
    if header.get('spell_id') != semantic.get('spell_id'):
        raise ValueError('header and semantic spell IDs differ')
    if header.get('source') != semantic.get('source'):
        raise ValueError('source lineage mismatch')
    if (header.get('execution_status') != 'BLOCKED_UNPARSED_EFFECTS'
            or semantic.get('execution_status') != 'BLOCKED_UNPARSED_EFFECTS'
            or semantic.get('semantic_completeness') is not False
            or semantic.get('executable_effects') != []):
        raise ValueError('audit input must be explicitly nonexecutable source observations')
    description = header.get('unparsed_effect_text')
    if not isinstance(description, str) or not description:
        raise ValueError('missing complete source effect text')
    capability_kinds = {effect_capability(t.__new__(t)).execution_kind for t in registered_effect_types()}
    occupied = [False] * len(description)
    observations = []
    blockers = []
    for index, obs in enumerate(semantic.get('observations', [])):
        span = obs.get('text_span')
        if (not isinstance(span, list) or len(span) != 2
                or not all(type(v) is int for v in span)):
            raise ValueError('invalid observation span')
        lo, hi = span
        if lo < 0 or hi > len(description) or hi <= lo or any(occupied[lo:hi]):
            raise ValueError('out-of-bounds or overlapping observation spans')
        if description[lo:hi] != obs.get('source_text'):
            raise ValueError('observation no longer matches source text')
        for offset in range(lo, hi):
            occupied[offset] = True
        candidate = _OBSERVATION_KIND_CANDIDATES.get(obs.get('kind'))
        kind_supported = candidate in capability_kinds if candidate is not None else False
        if not candidate:
            blockers.append({'code': 'UNKNOWN_OBSERVATION_KIND', 'observation_index': index})
        elif not kind_supported:
            blockers.append({'code': 'NO_GENERIC_EXECUTOR_CAPABILITY', 'observation_index': index})
        observations.append({'kind': obs.get('kind'), 'source_span': span,
                             'candidate_execution_kind': candidate,
                             'executor_kind_registered': kind_supported,
                             'semantics_verified': False})
    residual = ' '.join(''.join(' ' if used else ch for used, ch in zip(occupied, description)).split())
    if residual != semantic.get('unparsed_text'):
        raise ValueError('semantic residual disagrees with source coverage')
    if residual:
        blockers.append({'code': 'UNPARSED_SOURCE_CLAUSES', 'text': residual})
    if not observations:
        blockers.append({'code': 'NO_TYPED_OBSERVATIONS'})
    # Even when the source has no textual residual, the tooltip alone does not
    # establish exact targeting, trigger, aura timing, prerequisites or scaling.
    blockers.append({'code': 'TARGETING_AND_PREREQUISITES_UNVERIFIED'})
    blockers.append({'code': 'EFFECT_EXECUTION_SEMANTICS_UNVERIFIED'})
    return {'spell_id': header['spell_id'], 'source': header['source'],
            'observations': observations, 'blockers': blockers,
            'source_clause_coverage_complete': not bool(residual),
            'semantic_completeness': False, 'execution_status': 'BLOCKED_UNPARSED_EFFECTS',
            'executable_effects': [], 'ir_promotion_allowed': False}


def audit_verified_spell(database: str | Path, *, batch_id: str, spell_id: int) -> dict:
    from src.v2.source_sqlite_typed_spell_facts import extract_verified_header_facts
    header = extract_verified_header_facts(database, batch_id=batch_id, spell_id=spell_id)
    semantic = extract_verified_semantic_observations(database, batch_id=batch_id, spell_id=spell_id)
    return audit_semantic_completeness(header, semantic)

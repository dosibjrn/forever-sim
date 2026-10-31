"""Version-pinned source talent positions projected through canonical SQLite.

A position, rank cap, or prerequisite is not a combat effect.  All rank
modifiers remain absent until a matching-build tooltip/rank observation has
been independently staged.  Never carry stale modifiers across builds.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import math
import re
import sqlite3

from src.game.model.ir import TalentRankDefinition


def _rank_l0_provenance(observed: dict | None, rank: int):
    """Carry source observations as uncertain features, never executable mods."""
    if not observed or not all(len(f['rank_values']) >= rank for f in observed['features']):
        return None
    return {'expected_clause_count': len(observed['features']),
            'effects': [{'domain': feature['domain'], 'target': feature['target'],
        'sourced_value': float(feature['rank_values'][rank - 1]),
        'condition': feature['condition'], 'source': observed['source_url'],
        'context_uncertainty': observed['context_uncertainty']}
        for feature in observed['features']],
        'context_uncertainty': observed['context_uncertainty'],
        'source_url': observed['source_url']}


def apply_staged_talent_positions(conn: sqlite3.Connection, class_key: str,
                                  level: int, talents):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='checkpoint_talent_source_positions'").fetchone():
        return tuple(talents), None
    rows = conn.execute('''SELECT class_key,source_build,min_level,source_sha256,source_json
        FROM checkpoint_talent_source_positions WHERE class_key=? AND min_level<=?''',
        (class_key.lower(), level)).fetchall()
    if not rows:
        return tuple(talents), None
    if len(rows) != 1:
        raise ValueError('STAGED_TALENT_AMBIGUOUS_POSITION_SOURCE')
    _, build, min_level, digest, raw = rows[0]
    if sha256(raw.encode()).hexdigest() != digest:
        raise ValueError('STAGED_TALENT_POSITION_SHA_MISMATCH')
    data = json.loads(raw)
    if (data.get('schema') != 'forever_source_talent_positions_v1'
            or data.get('class_key') != class_key.lower()
            or data.get('source_build') != build
            or not data.get('source_generated')
            or not str(data.get('source_url', '')).startswith('https://')
            or int(data.get('min_level', -1)) != int(min_level)
            or int(min_level) > level):
        raise ValueError('STAGED_TALENT_POSITION_SCOPE_MISMATCH')
    per_row = int(data.get('points_per_row', 0))
    if per_row < 1:
        raise ValueError('STAGED_TALENT_INVALID_TIER_RULE')
    catalogue = data['talents']
    by_slug = {t.id: t for t in talents}
    by_source_id = {int(e['source_talent_id']): e for e in catalogue}
    if (len(by_slug) != len(talents)
            or len(by_source_id) != len(catalogue)
            or len({e['talent_id'] for e in catalogue}) != len(catalogue)
            or set(by_slug) != {e['talent_id'] for e in catalogue}):
        raise ValueError('STAGED_TALENT_POSITION_INVENTORY_MISMATCH')
    source_by_slug = {e['talent_id']: e for e in catalogue}
    rank_l0 = data.get('rank_l0', {})
    if set(rank_l0) - set(source_by_slug):
        raise ValueError('STAGED_TALENT_UNKNOWN_SOURCE_RANK_L0')
    for tid, observation in rank_l0.items():
        cap = int(source_by_slug[tid]['max_rank'])
        if not str(observation.get('source_url', '')).startswith('https://'):
            raise ValueError('STAGED_TALENT_RANK_L0_SOURCE_MISSING')
        if not observation.get('context_uncertainty') or not observation.get('features'):
            raise ValueError('STAGED_TALENT_RANK_L0_UNCERTAINTY_MISSING')
        for feature in observation['features']:
            values = feature.get('rank_values', [])
            if (not feature.get('domain') or not feature.get('target')
                    or not feature.get('condition') or not 1 <= len(values) <= cap
                    or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                           or not math.isfinite(v) or v < 0 for v in values)):
                raise ValueError('STAGED_TALENT_INVALID_RANK_L0_FEATURE')
    source_trees = {e['tree_key'] for e in catalogue}
    if not source_trees or any(not isinstance(tree, str) or not tree.strip() for tree in source_trees):
        raise ValueError('STAGED_TALENT_INVALID_SOURCE_TREE')
    for entry in catalogue:
        tid = entry['talent_id']
        row, col, cap = int(entry['row']), int(entry['column']), int(entry['max_rank'])
        if (not 0 <= row <= 6 or not 0 <= col <= 3 or not 1 <= cap <= 5
                or int(entry['points_required']) != row * per_row
                or entry['tree_key'] not in source_trees
                or not str(entry['source_url']).startswith('https://')
                or re.sub(r'[^a-z0-9]+', '_', entry['name'].lower()).strip('_').replace('_s_', 's_') != tid):
            raise ValueError('STAGED_TALENT_INVALID_SOURCE_POSITION')
        deps = entry.get('requires', [])
        if len(deps) > 1 or any(dep not in source_by_slug for dep in deps):
            raise ValueError('STAGED_TALENT_INVALID_SOURCE_PREREQUISITE')
        for dep in deps:
            predecessor = source_by_slug[dep]
            if (predecessor['tree_key'] != entry['tree_key']
                    or int(predecessor['row']) >= row):
                raise ValueError('STAGED_TALENT_INVALID_SOURCE_PREREQUISITE')
    output = []
    for entry in catalogue:
        tid = entry['talent_id']
        t = by_slug[tid]
        dep = entry.get('requires', [])
        prerequisite = ({'talent_id': dep[0],
                         'required_rank': int(source_by_slug[dep[0]]['max_rank'])}
                        if dep else None)
        provenance = {'source_build': build, 'source_url': entry['source_url'],
                      'source_sha256': digest,
                      'rank_effects': 'NOT_STAGED_POSITION_ONLY'}
        rank_defs = []
        observed = rank_l0.get(tid)
        for i in range(1, int(entry['max_rank']) + 1):
            rank_provenance = dict(provenance)
            l0 = _rank_l0_provenance(observed, i)
            if l0 is not None:
                rank_provenance['checkpoint_source_l0'] = l0
            rank_defs.append(TalentRankDefinition(rank=i, modifiers=(),
                                                  provenance=rank_provenance))
        ranks = tuple(rank_defs)
        output.append(replace(t, name=entry['name'], tree_key=entry['tree_key'],
            max_rank=int(entry['max_rank']), ranks=ranks, prerequisite=prerequisite,
            metadata={**t.metadata, 'row': int(entry['row']),
                'col': int(entry['column']),
                'source_position_only': True,
                'checkpoint_source_build': build,
                'checkpoint_source_sha256': digest,
                'source_talent_id': int(entry['source_talent_id']),
                'source_spell_id': int(entry['spell_id']),
                'rank_cap_verified': True,
                'source_rank_effects': 'UNKNOWN_NOT_ZERO'}))
    return tuple(output), {'source_build': build, 'sha256': digest,
                           'source_url': data['source_url'],
                           'positions': len(output), 'rank_effects_staged': sum(
                               bool(r.provenance.get('checkpoint_source_l0'))
                               for t in output for r in t.ranks),
                           'points_per_row': per_row}

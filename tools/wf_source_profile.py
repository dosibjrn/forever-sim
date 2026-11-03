"""Source-bound named-spec profile constraints shared by active optimizers.

A named tree is not itself a game rule. This module resolves an explicit
source-verified profile or versioned product search constraint, then validates
every returned full-point allocation with the canonical talent validator.
It contains no P1/P2 acceptance logic and is safe for P3/P4/P5/P6 consumers.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from src.game.talents import available_talent_points, validate_talent_selection


def _load_product_spec_profile(root: Path, class_key: str, level: int, spec: str, *,
                               source_sha256: str):
    """Load an explicit versioned optimizer profile, NOT a game-source fact.

    Source DB identity is bound at execution; talent legality still comes from
    the compiled canonical tree and validate_talent_selection. Unknown profiles
    are not silently inferred from tree names.
    """
    if spec == 'unrestricted':
        return None
    path = Path(root) / 'config/validation/source_spec_profiles.json'
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('SOURCE_PRODUCT_PROFILE_INVALID_JSON') from exc
    if (not isinstance(document, dict) or document.get('schema_version') != 1
            or document.get('authority') != 'PRODUCT_PROFILE_CONSTRAINT'
            or not isinstance(document.get('profiles'), list)):
        raise ValueError('SOURCE_PRODUCT_PROFILE_SCHEMA')
    matches = [entry for entry in document['profiles']
               if isinstance(entry, dict) and entry.get('class_key') == class_key
               and entry.get('level') == level and entry.get('spec') == spec]
    if len(matches) > 1:
        raise ValueError('SOURCE_PRODUCT_PROFILE_DUPLICATE')
    if not matches:
        return None
    entry = matches[0]
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64
            or any(c not in '0123456789abcdef' for c in source_sha256.lower())):
        raise ValueError('SOURCE_PRODUCT_PROFILE_SOURCE_SHA')
    if (entry.get('tree_key') != spec
            or entry.get('constraint_kind') != 'minimum_tree_points'
            or entry.get('source_binding') != 'CANONICAL_RUNTIME_TALENT_TREE'
            or not isinstance(entry.get('contract_version'), str)
            or not entry['contract_version']
            or type(entry.get('minimum_points')) is not int
            or entry['minimum_points'] <= 0):
        raise ValueError('SOURCE_PRODUCT_PROFILE_INVALID_RULE')
    return {
        'class_key': class_key, 'level': level, 'tree_key': spec,
        'minimum_points': entry['minimum_points'],
        'constraint_kind': entry['constraint_kind'],
        'authority_kind': 'PRODUCT_PROFILE_CONSTRAINT',
        'contract_version': entry['contract_version'],
        'contract_path': 'config/validation/source_spec_profiles.json',
        'source_db_sha256': source_sha256,
    }


def _source_spec_profile(ir, spec: str, *, level: int, bonus: int, step: int,
                         source_sha256=None, frontier_builder=None, profile_rule=None):
    """Resolve a named profile to SOURCE tree identity and legal full builds.

    A source tree is not itself a gameplay spec rule. Accept either a
    source-verified game rule or an explicitly versioned PRODUCT constraint,
    then independently check every allocation against canonical talent rules.
    Neither contract alone proves talent-rank behavior or an overall active-gate PASS.
    """
    if spec == 'unrestricted':
        return None, {'source_spec_profile_verified': True,
                      'source_spec_tree': None}
    trees={t.tree_key for t in ir.talents}
    if not isinstance(spec,str) or spec not in trees:
        raise ValueError('SPEC_PROFILE_NOT_A_SOURCE_TREE:'+str(spec))
    tier_rows=[int(t.metadata['row']) for t in ir.talents
               if t.tree_key==spec and t.metadata.get('row') is not None]
    if not tier_rows:
        raise ValueError('SPEC_SOURCE_TREE_POSITIONS_MISSING:'+spec)
    points=available_talent_points(level,bonus_talent_points=bonus)
    # Structural candidate only: the deepest sourced tier's unlock floor is
    # NOT itself evidence of a game-defined spec profile or a talent preset.
    tier_floor=max(tier_rows)*step+1
    raw=(profile_rule if profile_rule is not None else
         (ir.provenance.get('source_spec_profile_rules') or {}).get(spec))
    identity_ok=(isinstance(raw,dict) and raw.get('tree_key')==spec
                 and raw.get('class_key')==ir.actor.metadata.get('class_key')
                 and raw.get('level')==level
                 and isinstance(source_sha256,str) and len(source_sha256)==64
                 and raw.get('source_db_sha256')==source_sha256
                 and type(raw.get('minimum_points')) is int
                 and tier_floor<=raw['minimum_points']<=points)
    source_accepted=(identity_ok and
                     isinstance(raw.get('source_url'),str) and
                     raw['source_url'].startswith('https://') and
                     raw.get('evidence_status')=='VERIFIED_SOURCE_PROFILE')
    product_accepted=(identity_ok and
                      raw.get('authority_kind')=='PRODUCT_PROFILE_CONSTRAINT' and
                      raw.get('constraint_kind')=='minimum_tree_points' and
                      isinstance(raw.get('contract_version'),str) and
                      bool(raw['contract_version']) and
                      raw.get('contract_path')=='config/validation/source_spec_profiles.json')
    accepted=bool(source_accepted or product_accepted)
    required=raw['minimum_points'] if accepted else tier_floor
    if required>points:
        raise ValueError('SOURCE_SPEC_TREE_UNREACHABLE_AT_LEVEL:'+spec)
    if frontier_builder is None:
        from src.v2.source_bounded_joint_frontier import source_spec_talent_frontier
        frontier_builder = source_spec_talent_frontier
    builds,evidence=frontier_builder(
        ir,(),tree_key=spec,minimum_points=required,level=level,
        bonus_talent_points=bonus,max_frontier=256)
    # Validate even the returned frontier against the *real* source rules.
    definitions={t.id:t for t in ir.talents}
    if not builds:
        raise ValueError('SOURCE_SPEC_FRONTIER_EMPTY')
    for allocation in builds:
        if (not isinstance(allocation, Mapping) or
            any(type(tid) is not str or tid not in definitions
                for tid in allocation) or
            any(type(rank) is not int or rank<=0
                for rank in allocation.values()) or
            sum(allocation.values())!=points or
            sum(rank for tid,rank in allocation.items()
                if definitions[tid].tree_key==spec)<required):
            raise ValueError('SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION')
        # A full point total and a named source tree do NOT establish legal
        # ranks, prerequisites or per-tree tier unlocks. Recheck every returned
        # candidate using the same canonical validator as production search.
        try:
            validate_talent_selection(ir,allocation,level=level,
                                      bonus_talent_points=bonus)
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError('SOURCE_SPEC_FRONTIER_ILLEGAL_ALLOCATION:'
                             +str(exc)) from exc
    return builds, {
        'source_spec_profile_verified':bool(accepted),
        'source_spec_profile_game_fact_claimed':bool(source_accepted),
        'source_spec_profile_contract_verified':bool(accepted),
        'source_spec_tree':spec,
        'source_spec_structural_tier_floor':tier_floor,
        'source_spec_required_points':required,
        'source_spec_candidate_count':len(builds),
        'source_spec_candidate_frontier_exhaustive':False,
        'source_spec_profile_kind':('PRODUCT_PROFILE_CONSTRAINT' if product_accepted
            else 'VERIFIED_SOURCE_PROFILE' if source_accepted
            else 'UNVERIFIED_SOURCE_TREE_ONLY'),
        'source_spec_profile_authority':(raw['contract_path'] if product_accepted
            else raw['source_url'] if source_accepted
            else 'UNVERIFIED_SOURCE_TREE_ONLY'),
        'source_spec_profile_contract_version':(raw.get('contract_version') if product_accepted
            else None),
        'source_spec_frontier_evidence':evidence,
    }


"""Generic, source-bound talent-rank L0 opportunity frontier.

This does not pretend that source features in incomparable units are s/mob.
It turns every legal, source-valued on/off/rank delta into a bounded,
unit-normalized *proposal prior* consumed by the paid joint optimizer.
Unsupported executable ranks remain visible in the L0 frontier, not free
spells or fictitious L2 modifiers. No class, level or talent IDs are encoded.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Mapping
from math import isfinite


def rank_opportunity_frontier(certificate: dict, *, class_key: str, level: int) -> dict:
    scope = certificate.get('checkpoint') or {}
    if (scope.get('class_key', '').lower() != class_key.lower()
            or scope.get('level') != level or not certificate.get('p2_pass')):
        raise ValueError('P2_UNVERIFIED_CHECKPOINT_CERTIFICATE')
    source = certificate.get('rank_rows') or []
    by_rank = {(r['talent_id'], int(r['rank'])): r for r in source}
    if len(by_rank) != len(source):
        raise ValueError('P2_DUPLICATE_RANK_CERTIFICATE')
    norm = defaultdict(float)
    for row in source:
        if not row.get('l0_effects'):
            raise ValueError('P2_L0_UNSCORED_RANK')
        for feature in row['l0_effects']:
            domain = (str(feature['domain']), str(feature.get('target', '')))
            v = float(feature.get('context_l0_value', feature['sourced_value']))
            if not isfinite(v):
                raise ValueError('P2_NONFINITE_RANK_FEATURE')
            norm[domain] = max(norm[domain], abs(v))
    scored = []
    for (talent_id, rank), row in sorted(by_rank.items()):
        parent = by_rank.get((talent_id, rank - 1)) if rank > 1 else None
        if rank > 1 and parent is None:
            raise ValueError(f'P2_MISSING_PREVIOUS_RANK:{talent_id}:{rank}')
        current = {(str(x['domain']), str(x.get('target', ''))): float(x.get('context_l0_value', x['sourced_value']))
                   for x in row['l0_effects']}
        previous = {(str(x['domain']), str(x.get('target', ''))): float(x.get('context_l0_value', x['sourced_value']))
                    for x in parent['l0_effects']} if parent else {}
        delta_features = []
        magnitude = 0.0
        for key in sorted(set(current) | set(previous)):
            delta = current.get(key, 0.0) - previous.get(key, 0.0)
            if abs(delta) < 1e-12:
                continue
            scale = norm[key]
            if scale <= 0:
                raise ValueError('P2_ZERO_NORM_NONZERO_DELTA')
            normalized = abs(delta) / scale
            magnitude += normalized
            delta_features.append({'domain': key[0], 'target': key[1],
                'source_rank_delta': delta, 'scale_within_domain': scale,
                'normalized_opportunity': normalized})
        # A zero *marginal* (e.g., an actual flat rank curve) is valid, but is
        # not inferred from absent data: every rank has a source-valued vector.
        scored.append({'talent_id':talent_id, 'rank':rank,
            'l0_rank_delta':delta_features, 'relative_opportunity':magnitude,
            'conditional':bool(row.get('potentially_contextual')),
            'l2_supported':bool(row.get('l2_supported')),
            'comparison_unit':'within_effect_domain_not_seconds_per_mob'})
    return {'checkpoint':dict(scope),'rank_count':len(scored),
        'families':len({r['talent_id'] for r in scored}),
        'source_only_count':sum(not r['l2_supported'] for r in scored),
        'ranks':scored,'ready':len(scored)==len(source) and not certificate.get('blocked')}


def proposal_l0_opportunity(frontier:dict, from_allocation: Mapping[str,int],
                            to_allocation: Mapping[str,int]) -> dict:
    """Opportunity prior from source on/off deltas, without a paid evaluation.

    Scalar is an ordering prior, not an objective estimate; sign/direction
    of gameplay benefit is not assumed by an absolute magnitude.
    """
    rows={(r['talent_id'],r['rank']):r for r in frontier['ranks']}
    features=[]
    changed=sorted(set(from_allocation)|set(to_allocation))
    for talent in changed:
        old = int(from_allocation.get(talent,0))
        new = int(to_allocation.get(talent,0))
        if old == new:
            continue
        for rank in range(min(old,new)+1, max(old,new)+1):
            row=rows.get((talent,rank))
            if row is None:
                raise ValueError(f'P2_UNSCORED_ALLOCATION_DELTA:{talent}:{rank}')
            features.append({'talent_id':talent,'rank':rank,
                'sign':1 if new > old else -1,
                'relative_opportunity':row['relative_opportunity'],
                'conditional':row['conditional'],'l2_supported':row['l2_supported']})
    return {'changes':features,
        'l0_opportunity':sum(float(x['relative_opportunity']) for x in features),
        'not_s_per_mob':True,
        'source_only_rank_changes':sum(not x['l2_supported'] for x in features)}

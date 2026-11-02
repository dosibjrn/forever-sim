"""WF401: bounded, source-neutral paid proposal ordering tests."""
from itertools import product

import pytest

from src.v2.source_bounded_joint_frontier import (
    _diagonal_coordinates, _marginal_screen_coordinates,
    _coordinate_order_key,
)


def _pilot(dimensions, score):
    attempted=[]
    generator=_marginal_screen_coordinates(dimensions, attempted)
    anchors=1+sum(d-1 for d in dimensions)
    head=[]
    for _ in range(anchors):
        coords=next(generator)
        head.append(coords)
        result=score(coords)
        attempted.append(dict(screen_status=('COMPLETE' if result is not None else 'OS_TIMEOUT'),
                              screen_s_per_mob=result))
    return head,generator


def test_source_neutral_warmup_then_cross_axis_combination_earlier_than_diagonal():
    dims=(3,3,8,3)
    # An independent, non-Druid, non-Mage scoring fixture: lower is better.
    # Scores come from a paid screen, not a guessed per-class/spell table.
    weights=((0,-2.5,-1.3),(0,-.75,.25),(0,-.1,-.1,1.0,1.1,1.2,1.3,1.4),
             (0,-4.2,-4.2))
    head,iter_tail=_pilot(dims,lambda c:30+sum(weights[i][j] for i,j in enumerate(c)))
    assert len(head)==14 and head[0]==(0,0,0,0)
    # Critical cross-axis interactions should be screened in the bounded prefix.
    early=head+list(next(iter_tail) for _ in range(15))
    target=(2,1,0,1)
    assert target in early
    assert list(_diagonal_coordinates(dims)).index(target)>=35
    assert len(set(early))==len(early)


def test_marginal_scheduler_eventually_covers_every_legal_coordinate_once():
    dims=(2,2,3,2)
    head,tail=_pilot(dims,lambda c:7-sum(c))
    got=head+list(tail)
    assert len(got)==24
    assert len(set(got))==len(got)
    assert set(got)==set(product(*(range(n) for n in dims)))


def test_missing_source_screen_never_counts_as_free_bonus():
    dims=(2,2,2,2)
    def result(c):
        if c==(0,0,1,0):return None
        return 10-sum(c)
    head,tail=_pilot(dims,result)
    remainder=list(tail)
    assert (1,1,0,1) in remainder
    assert (1,1,1,1) in remainder
    assert remainder.index((1,1,0,1)) < remainder.index((1,1,1,1))


def test_failed_incumbent_screen_falls_back_to_complete_diagonal():
    dims=(2,2,2,2)
    head,tail=_pilot(dims,lambda c:None if c==(0,0,0,0) else 10.)
    got=head+list(tail)
    assert set(got)==set(product(*(range(2) for _ in dims)))
    assert len(got)==len(set(got))


def test_invalid_product_and_upper_bound_safe_fallback():
    assert list(_marginal_screen_coordinates((2,0,2,2),[]))==[]
    # Large source-backed legal spaces cannot create a Cartesian materialization.
    dims=(201,501,3,2)
    attempted=[]
    g=_marginal_screen_coordinates(dims,attempted)
    for i in range(10):
        next(g)
        attempted.append({'screen_status':'COMPLETE','screen_s_per_mob':10.})
    assert len(attempted)==10

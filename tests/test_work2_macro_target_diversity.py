"""Work2: short paid talent sampling explores legal receiver families fairly."""
from src.game.talent_frontier import Neighbor
from src.v2.source_bounded_joint_frontier import (
    _interleave_macro_transfer_targets, _spread_candidates,
)


def test_macro_sampling_spreads_across_distinct_receiver_talents():
    # The source proposer can emit many donor/depth variants for each receiver.
    # At count=1, a short beam should cycle receiver families rather than
    # repeatedly paying one receiving talent.
    pool=tuple(
        Neighbor(((donor, 2), (receiver, 3)), 'macro_transfer:3',
                 (donor, receiver))
        for donor in ('d1', 'd2', 'd3')
        for receiver in ('r1', 'r2', 'r3', 'r4')
    )
    ordered=_interleave_macro_transfer_targets(pool)
    assert len(ordered)==len(pool)
    assert set(ordered)==set(pool)
    assert [n.changed_ids[-1] for n in ordered[:4]]==['r1','r2','r3','r4']
    assert [n.changed_ids[-1] for n in ordered[4:8]]==['r1','r2','r3','r4']
    sampled=[_spread_candidates(ordered,1,i)[0].changed_ids[-1]
             for i in range(4)]
    assert len(set(sampled))==4
    assert ordered==_interleave_macro_transfer_targets(pool)


def test_empty_macro_frontier_remains_empty():
    assert _interleave_macro_transfer_targets(())==()

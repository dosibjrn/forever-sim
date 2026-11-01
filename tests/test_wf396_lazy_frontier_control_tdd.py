"""WF396: source-legal bounded search must scale without false incumbents."""
from itertools import islice, product
from time import perf_counter
from unittest.mock import patch

from src.v2 import source_bounded_joint_frontier as frontier


def _old_order(dimensions):
    return sorted(product(*(range(n) for n in dimensions)),
                  key=lambda c: (sum(c), max(c), tuple(-x for x in c)))


def test_lazy_diagonal_frontier_matches_exact_previous_order_on_small_domains():
    for dims in ((1,1,1,1),(2,3,4,2),(4,2,1,3),(3,3,3,3)):
        assert list(frontier._diagonal_coordinates(dims)) == _old_order(dims)


def test_lazy_frontier_produces_1000_from_billion_space_without_cartesian_product():
    start=perf_counter()
    with patch.object(frontier, 'product', side_effect=AssertionError('EAGER_CARTESIAN'), create=True):
        rows=list(islice(frontier._diagonal_coordinates((1000,1000,1000,1000)),1000))
    assert len(rows)==len(set(rows))==1000
    assert rows[0]==(0,0,0,0)
    assert all(sum(a)<=sum(b) for a,b in zip(rows,rows[1:]))
    assert perf_counter()-start<2.0


def test_finalist_control_must_be_exact_four_axis_reference_not_same_labels():
    def row(talent,score,is_control):
        return ({'allocation':{'talent':talent},'screen_s_per_mob':score,
                 'gear_move':'incumbent','policy':'incumbent',
                 'recovery':'incumbent','is_control':is_control},object(),None)
    # All three have identical gear, APL and recovery labels; ONLY the exact
    # legal full-build reference may consume the reserved finalist slot.
    fast=row(3,1.0,False)
    wrong=row(2,2.0,False)
    actual=row(1,10.0,True)
    result=frontier._select_screen_finalists([fast,wrong,actual],2)
    assert len(result)==2
    assert fast in result and actual in result and wrong not in result


def test_no_false_control_when_explicit_control_did_not_complete_screen():
    def row(talent,score):
        return ({'allocation':{'talent':talent},'screen_s_per_mob':score,
                 'gear_move':'incumbent','policy':'incumbent',
                 'recovery':'incumbent','is_control':False},object(),None)
    first,second=row(3,1.0),row(2,2.0)
    assert frontier._select_screen_finalists([first,second],1)==[first]


def test_legal_full_point_source_seed_is_exact_search_reference():
    from pathlib import Path
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.talent_execution_coverage import compile_talent_runtime
    root=Path(__file__).resolve().parents[1]
    ir=build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=root/'data/forever/staged_druid_l30_talents_70338.sqlite')
    compiled,_=compile_talent_runtime(ir)
    legal={'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'feral_instinct':1}
    candidates=[{'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'heart_of_the_wild':1}]
    result,origin=frontier._source_reference_talents(
        compiled,level=30,candidates=candidates,source_allocation=legal)
    assert result[0]==legal
    assert len(result)==len(candidates)
    assert origin=='LEGAL_SOURCE_FULL_BUILD'


def test_incomplete_source_stage_is_not_falsely_marked_as_incumbent():
    from pathlib import Path
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.talent_execution_coverage import compile_talent_runtime
    root=Path(__file__).resolve().parents[1]
    ir=build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=root/'data/forever/staged_druid_l30_talents_70338.sqlite')
    compiled,_=compile_talent_runtime(ir)
    incomplete={'furor':5,'naturalist':5,'gift_of_nature':2,
                'improved_rejuvenation':1,'natural_shapeshifter':3}
    candidates=[{'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'feral_instinct':1}]
    result,origin=frontier._source_reference_talents(
        compiled,level=30,candidates=candidates,source_allocation=incomplete)
    assert result==candidates
    assert origin=='FIRST_INDEPENDENT_SOURCE_LEGAL_PROPOSAL_NOT_SOURCE_SEED'

"""P2 accepts actual effect amplitudes, not unrelated talent or IR activity."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from tools import wf_gate_p2_live as p2
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, talented_bonus_for_level
from src.game.data.forever.source_checkpoint_p2 import _witness


def sample(talent_id, rank=1):
    ir,_ = compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))
    talent=next(t for t in ir.talents if t.id==talent_id)
    witness=_witness(talent,rank,ir.talents,16,5)
    # Ordinary source witness can include an unrelated unsupported filler.
    if talent_id == 'gift_of_nature':
        witness={'gift_of_nature':1,'furor':5,'ferocity':5}
    new,_=apply_talent_selection(ir,witness,level=20,
                                bonus_talent_points=talented_bonus_for_level(20))
    prior=dict(witness)
    if rank==1:prior.pop(talent_id)
    else:prior[talent_id]=rank-1
    old,_=apply_talent_selection(ir,prior,level=20,
                                bonus_talent_points=talented_bonus_for_level(20))
    modifier=talent.ranks[rank-1].modifiers[0]
    previous=talent.ranks[rank-2].modifiers[0].value if rank>1 else 0
    return old,new,replace(modifier,provenance={**modifier.provenance,
             '_gate_relative_factor':(1+modifier.value)/(1+previous)})


def test_damage_moonfire_real_runtime_witness():
    a,b,mod=sample('improved_moonfire')
    witness=p2._runtime_effect_witness(a,b,mod)
    assert witness and witness['after_amount'] > witness['before_amount']
    assert witness['metric']=='direct_damage'


def test_second_rank_uses_cumulative_magnitude():
    a,b,mod=sample('improved_moonfire',2)
    witness=p2._runtime_effect_witness(a,b,mod)
    assert witness and abs(witness['ir_factor'] - 1.1/1.05)<1e-6


def test_periodic_real_runtime_tick_outcome():
    a,b,mod=sample('genesis')
    witness=p2._runtime_effect_witness(a,b,mod)
    assert witness and witness['metric'] in ('periodic_damage','periodic_heal')
    assert witness['after_amount'] > witness['before_amount']


def test_incorrect_magnitude_must_not_pass():
    a,b,mod=sample('improved_moonfire')
    wrong=replace(mod,provenance={**mod.provenance,'_gate_relative_factor':1.99})
    assert p2._runtime_effect_witness(a,b,wrong) is None


def test_unrelated_action_does_not_pass():
    a,b,mod=sample('improved_moonfire')
    wrong=replace(mod,target_id='entangling_roots')
    assert p2._runtime_effect_witness(a,b,wrong) is None


def test_no_runtime_observation_must_not_pass():
    a,b,mod=sample('improved_moonfire')
    with patch.object(p2,'_action_runtime_probe',return_value=None):
        assert p2._runtime_effect_witness(a,b,mod) is None


def test_no_actual_delta_must_not_pass():
    a,b,mod=sample('improved_moonfire')
    x={'direct_damage':20.,'periodic_damage':30.,'direct_heal':0.,'periodic_heal':0.}
    with patch.object(p2,'_action_runtime_probe',return_value=x):
        assert p2._runtime_effect_witness(a,b,mod) is None


def test_wrong_direction_runtime_must_not_pass():
    a,b,mod=sample('improved_moonfire')
    old={'direct_damage':20.,'periodic_damage':10.,'direct_heal':0.,'periodic_heal':0.}
    new={'direct_damage':10.,'periodic_damage':10.,'direct_heal':0.,'periodic_heal':0.}
    with patch.object(p2,'_action_runtime_probe',side_effect=[old,new]*20):
        assert p2._runtime_effect_witness(a,b,mod) is None

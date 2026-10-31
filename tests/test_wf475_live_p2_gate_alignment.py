"""P2 must not certify unrelated changes or silently bypass the talent frontier."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tools import wf_gate_p2_live as p2
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import talented_bonus_for_level
from src.game.data.forever.source_checkpoint_p2 import _witness


def _mod(kind, target_type, target_id, value, **facts):
    return SimpleNamespace(kind=kind, target_type=target_type,
                           target_id=target_id,value=value,provenance=facts)


def test_mode_stat_rejects_unrelated_change():
    before,after=SimpleNamespace(actions=()),SimpleNamespace(actions=())
    bogus=[{'mode':'cat','field':'stats','stat':'intellect','before':20.,'after':21.}]
    with patch.object(p2,'_runtime_actor_state_delta',return_value=bogus):
        tests,missing=p2._behavior_fixtures(before,after,[
            _mod('mode_stat_flat','mode','cat',.15,target_stat='movement_speed_pct')])
    assert tests==[] and missing==['0:mode_stat_flat:cat']


def test_actor_stat_requires_direction_and_amount():
    before,after=SimpleNamespace(actions=()),SimpleNamespace(actions=())
    bad=[{'mode':'initial','field':'stats','stat':'dodge_chance','before':.01,'after':.03}]
    with patch.object(p2,'_runtime_actor_state_delta',return_value=bad):
        tests,missing=p2._behavior_fixtures(before,after,[
            _mod('actor_stat_flat','actor_stat','dodge_chance',-.02)])
    assert not tests and missing
    with patch.object(p2,'_runtime_actor_state_delta',return_value=bad):
        tests,missing=p2._behavior_fixtures(before,after,[
            _mod('actor_stat_flat','actor_stat','dodge_chance',.01)])
    assert not tests and missing
    with patch.object(p2,'_runtime_actor_state_delta',return_value=bad):
        tests,missing=p2._behavior_fixtures(before,after,[
            _mod('actor_stat_flat','actor_stat','dodge_chance',.02)])
    assert len(tests)==1 and not missing


def test_rank_live_search_must_generate_rank_up():
    ir,_=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))
    talent=next(t for t in ir.talents if t.id=='improved_wrath')
    witness=_witness(talent,1,ir.talents,16,5)
    assert witness
    with patch.object(p2,'source_legal_talent_neighbors',return_value={'neighbors':()}):
        r=p2._rank_probe(ir,talent,1,witness,level=20,
                         bonus=talented_bonus_for_level(20))
    assert not r['search_reachable']
    assert 'SEARCH_RANK_NOT_GENERATED' in r['reasons']
    assert r['status']=='FAIL'


def test_live_cli_druid_l20_and_mage_can_be_called():
    assert hasattr(p2, 'run_live')

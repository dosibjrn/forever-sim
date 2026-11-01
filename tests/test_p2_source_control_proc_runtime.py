"""Source-backed P2 control-proc witness: actual Druid GameIR + CombatRuntime."""
from dataclasses import replace

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p2 import _witness
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import (
    apply_talent_selection, available_talent_points, talented_bonus_for_level,
)
from tools.wf_gate_p2_live import _behavior_fixtures


def test_source_control_proc_rank_executes_and_wrong_chance_fails_closed():
    # Discover the talent and its sourced chance; do not hardcode a proc rate
    # or construct a fake GameIR/ControlApplied event.
    source=build_game_ir_slice(class_key='druid',level=60,
                               ability_db_path=DEFAULT_DB)
    assert source is not None
    compiled,_=compile_talent_runtime(source)
    candidates=[(talent,rank,mod)
                for talent in compiled.talents
                for rank in talent.ranks if rank.rank==1
                for mod in rank.modifiers if mod.kind=='action_control_proc']
    assert candidates, 'canonical Druid L60 source has no control-proc rank'
    talent,rank,mod=candidates[0]
    bonus=talented_bonus_for_level(60)
    points=available_talent_points(60,bonus_talent_points=bonus)
    step=int(compiled.provenance['talent_tree_rules']['points_per_row'])
    witness=_witness(talent,rank.rank,compiled.talents,points,step)
    assert witness is not None
    before_alloc=dict(witness)
    before_alloc.pop(talent.id,None)
    before,_=apply_talent_selection(compiled,before_alloc,level=60,
                                    bonus_talent_points=bonus)
    after,_=apply_talent_selection(compiled,witness,level=60,
                                   bonus_talent_points=bonus)

    executed,missing=_behavior_fixtures(before,after,(mod,))
    assert not missing
    assert len(executed)==1
    evidence=executed[0]
    assert evidence['probe']=='paired_production_control_proc'
    assert evidence['runtime_control_applied'] is True
    assert evidence['after_chance']>evidence['before_chance']
    assert evidence['proc_roll'] is not None

    # A fabricated source probability must not inherit the real proc's PASS.
    wrong=replace(mod,value=float(mod.value)+0.01)
    false_tests,false_missing=_behavior_fixtures(before,after,(wrong,))
    assert not false_tests
    assert false_missing

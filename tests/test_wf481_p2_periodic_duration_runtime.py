"""P2 duration modifier: source value + all ranks + actual tick behavior."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model.ir import PeriodicEffect, PeriodicHealEffect
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, talented_bonus_for_level
from tools import wf_gate_p2_live as gate


@pytest.fixture(scope='module')
def source():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))[0]


@pytest.fixture(scope='module')
def original_and_modified(source):
    from src.game.data.forever.source_checkpoint_p2 import _witness
    level=20
    talent=next(x for x in source.talents if x.id=='natures_splendor')
    from src.game.talents import available_talent_points
    bonus=talented_bonus_for_level(level)
    points=available_talent_points(level,bonus_talent_points=bonus)
    step=int(source.provenance['talent_tree_rules']['points_per_row'])
    witness=_witness(talent,1,source.talents,points,step)
    assert witness is not None
    baseline=dict(witness)
    baseline.pop(talent.id)
    before,_=apply_talent_selection(source,baseline,level=level,bonus_talent_points=bonus)
    after,_=apply_talent_selection(source,witness,level=level,bonus_talent_points=bonus)
    return before,after,talent.ranks[0].modifiers


@pytest.mark.parametrize('family,expected_delta', [('moonfire',3),('rejuvenation',3),('regrowth',6)])
def test_source_exact_duration_and_real_periodic_ticks(original_and_modified, family, expected_delta):
    before, after, modifiers=original_and_modified
    mod=next(m for m in modifiers if m.target_id==family)
    result=gate._periodic_duration_witness(before,after,mod)
    assert result is not None
    assert result['source_duration_delta_s']==expected_delta
    assert result['probe']=='paired_production_periodic_tick_series'
    assert result['after_tick_count']>result['before_tick_count']
    assert result['after_tick_amount']==result['before_tick_amount']
    assert len(result['checked_ir_actions'])>=1


def _alter_family_action(ir, family, index, alter):
    actions=list(ir.actions)
    matched=[i for i, action in enumerate(actions) if action.family_key==family]
    assert matched
    selected=matched[index]
    action=actions[selected]
    effects=list(action.effects)
    pos=next(i for i,e in enumerate(effects) if isinstance(e,(PeriodicEffect,PeriodicHealEffect)))
    effects[pos]=alter(effects[pos])
    actions[selected]=replace(action,effects=tuple(effects))
    return replace(ir,actions=tuple(actions))


def test_rejects_wrong_compiled_duration_in_one_rank(original_and_modified):
    old,new,mods=original_and_modified
    mod=next(m for m in mods if m.target_id=='regrowth')
    assert len([a for a in new.actions if a.family_key=='regrowth'])>=2
    altered=_alter_family_action(new,'regrowth',-1,lambda e: replace(e,duration_s=e.duration_s-3))
    assert gate._periodic_duration_witness(old,altered,mod) is None


def test_rejects_wrong_source_increment(original_and_modified):
    old,new,mods=original_and_modified
    for mod in mods:
        assert gate._periodic_duration_witness(old,new,replace(mod,value=mod.value+3)) is None


def test_rejects_increased_tick_strength(original_and_modified):
    old,new,mods=original_and_modified
    mod=next(m for m in mods if m.target_id=='moonfire')
    altered=_alter_family_action(new,'moonfire',0,lambda e: replace(e,total_base_damage=e.total_base_damage*1.2))
    assert gate._periodic_duration_witness(old,altered,mod) is None


def test_rejects_unexecuted_extra_tick(original_and_modified,monkeypatch):
    old,new,mods=original_and_modified
    mod=next(m for m in mods if m.target_id=='rejuvenation')
    assert gate._periodic_duration_witness(old,new,mod)
    original=gate._action_runtime_probe
    count=0
    def miss_last_tick(ir,action,*,observe_periodic=False):
        nonlocal count
        result=original(ir,action,observe_periodic=observe_periodic)
        count+=1
        if count==2 and result is not None:
            result={**result,'events':result['events'][:-1]}
        return result
    monkeypatch.setattr(gate,'_action_runtime_probe',miss_last_tick)
    assert gate._periodic_duration_witness(old,new,mod) is None


def test_all_target_family_ranks_are_validated(original_and_modified):
    old,new,mods=original_and_modified
    for mod in mods:
        observed=gate._periodic_duration_witness(old,new,mod)
        assert set(observed['checked_ir_actions'])=={
            a.id for a in new.actions if a.family_key==mod.target_id}

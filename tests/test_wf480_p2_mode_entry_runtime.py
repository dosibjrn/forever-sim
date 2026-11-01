"""One P2 improvement: source-accurate form-entry resource witnesses."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, talented_bonus_for_level
from src.game.runtime.state import ActorState
from tools import wf_gate_p2_live as gate


@pytest.fixture(scope='module')
def source():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid', level=20))[0]


def setup_rank(source, rank):
    before = {'furor':rank-1} if rank>1 else {}
    after = {'furor':rank}
    bonus = talented_bonus_for_level(20)
    old,_ = apply_talent_selection(source,before,level=20,bonus_talent_points=bonus)
    new,_ = apply_talent_selection(source,after,level=20,bonus_talent_points=bonus)
    talent = next(t for t in source.talents if t.id=='furor')
    old_rank = talent.ranks[rank-2] if rank>1 else None
    result=[]
    for i,mod in enumerate(talent.ranks[rank-1].modifiers):
        previous = old_rank.modifiers[i].value if old_rank else 0
        result.append(replace(mod,value=mod.value-previous))
    return old,new,result


@pytest.mark.parametrize('rank',range(1,6))
def test_both_runtime_mode_entry_effects(source,rank):
    old,new,mods=setup_rank(source,rank)
    for mod in mods:
        witnessed=gate._mode_entry_resource_witness(old,new,mod)
        assert witnessed is not None, (rank,mod.kind)
        assert witnessed['probe']=='paired_production_mode_transition'
        assert witnessed['after']['amount']>witnessed['before']['amount']


def test_wrong_source_increment_rejected(source):
    old,new,mods=setup_rank(source,3)
    for mod in mods:
        assert gate._mode_entry_resource_witness(old,new,mod)
        assert gate._mode_entry_resource_witness(old,new,replace(mod,value=mod.value*1.5)) is None


def test_wrong_compiled_resource_gain_rejected(source):
    old,new,mods=setup_rank(source,2)
    bear=next(m for m in new.modes if m.id=='bear')
    altered=replace(bear,entry_resource_modifiers=(replace(bear.entry_resource_modifiers[0],value=999.),))
    broken=replace(new,modes=tuple(altered if m.id=='bear' else m for m in new.modes))
    assert gate._mode_entry_resource_witness(old,broken,mods[0]) is None


def test_wrong_restore_rate_and_cap_rejected(source):
    old,new,mods=setup_rank(source,2)
    cat=next(m for m in new.modes if m.id=='cat')
    for field in ('outside_regen_per_s','max_restored'):
        e=cat.entry_resource_modifiers[0]
        broken_entry=replace(e,**{field:getattr(e,field)+7})
        wrong=replace(new,modes=tuple(replace(m,entry_resource_modifiers=(broken_entry,)) if m.id=='cat' else m for m in new.modes))
        assert gate._mode_entry_resource_witness(old,wrong,mods[1]) is None


def test_wrong_runtime_transition_rejected(source,monkeypatch):
    old,new,mods=setup_rank(source,1)
    original=ActorState.transition_mode
    def sabotaged(self,mode):
        event=original(self,mode)
        if any(e['phase']=='talent_entry' for e in event['resource_changes']):
            # Simulates a missing executor effect, while the GameIR still looks correct.
            for row in event['resource_changes']:
                if row['phase']=='talent_entry':
                    self.resources[row['resource_id']]=row['before']
        return event
    monkeypatch.setattr(ActorState,'transition_mode',sabotaged)
    for mod in mods:
        assert gate._mode_entry_resource_witness(old,new,mod) is None

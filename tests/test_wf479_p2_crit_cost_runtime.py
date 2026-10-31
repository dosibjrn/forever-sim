"""P2 new generic runtime witnesses: real positive and sabotage negative controls."""
from dataclasses import replace
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, talented_bonus_for_level
from tools import wf_gate_p2_live as gate


@pytest.fixture(scope='module')
def ir():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=20))[0]


def _pair(ir,name):
    talent=next(t for t in ir.talents if t.id==name)
    # Rank1 may need supporting talent points to meet tier prerequisites.
    from src.game.data.forever.checkpoint_p2_execution_gate import _executable_filler_witness
    from src.game.talents import available_talent_points
    bonus=talented_bonus_for_level(20)
    witness=_executable_filler_witness(talent,1,ir.talents,
        points=available_talent_points(20,bonus_talent_points=bonus),step=5)
    assert witness is not None
    prior=dict(witness);prior.pop(name,None)
    base,_=apply_talent_selection(ir,prior,level=20,bonus_talent_points=bonus)
    changed,_=apply_talent_selection(ir,witness,level=20,bonus_talent_points=bonus)
    return talent,base,changed


@pytest.mark.parametrize('name,target',[
    ('ferocity','swipe'),
    ('moonglow','damage_spell'),
    ('natural_shapeshifter','shapeshift_mana'),
])
def test_real_cost_and_wrong_amount(ir,name,target):
    talent,base,changed=_pair(ir,name)
    mod=next(x for x in talent.ranks[0].modifiers if x.target_id==target)
    if mod.kind=='resource_cost_pct':
        mod=replace(mod,provenance={**mod.provenance,'_gate_cost_ratio':1+mod.value})
    good=gate._isolated_resource_cost_witness(base,changed,mod)
    assert good is not None, (name,target)
    assert good['probe']=='paired_production_resource_spend'
    # Corrupt the modified cost in the IR: even if the runtime executes, the
    # resource magnitude assertion must reject it.
    changed_actions=[]
    for action in changed.actions:
        if action.id==good['action_id']:
            corrupted=tuple(replace(c,amount=c.amount*0.92) for c in action.costs)
            action=replace(action,costs=corrupted)
        changed_actions.append(action)
    broken=replace(changed,actions=tuple(changed_actions))
    assert gate._isolated_resource_cost_witness(base,broken,mod) is None


def test_cost_requires_runtime_resource_spend(ir,monkeypatch):
    talent,base,changed=_pair(ir,'ferocity')
    mod=talent.ranks[0].modifiers[0]
    assert gate._isolated_resource_cost_witness(base,changed,mod)
    def no_effect(*args,**kwargs):
        return {'spent':{'rage':20.0,'mana':20.0,'energy':20.0}}
    monkeypatch.setattr(gate,'_action_runtime_probe',no_effect)
    assert gate._isolated_resource_cost_witness(base,changed,mod) is None


@pytest.mark.parametrize('talent_name', ['improved_moonfire','natures_majesty'])
def test_crit_requires_precise_ir_bonus_and_runtime(ir,talent_name,monkeypatch):
    talent,base,changed=_pair(ir,talent_name)
    mod=next(x for x in talent.ranks[0].modifiers if x.kind=='crit_chance_pct')
    good=gate._isolated_crit_witness(base,changed,mod)
    assert good is not None,talent_name
    assert good['after_amount']>good['before_amount']
    # Correct production effect is mandatory; reported IR changes alone fail.
    monkeypatch.setattr(gate,'_action_runtime_probe',lambda *a,**kw: {
        'direct_damage':10.,'periodic_damage':10.,'direct_heal':10.})
    assert gate._isolated_crit_witness(base,changed,mod) is None


def test_wrong_crit_bonus_is_rejected(ir):
    talent,base,changed=_pair(ir,'improved_moonfire')
    mod=next(x for x in talent.ranks[0].modifiers if x.kind=='crit_chance_pct')
    assert gate._isolated_crit_witness(base,changed,mod)
    actions=[]
    for action in changed.actions:
        if action.family_key=='moonfire':
            effects=tuple(replace(effect,crit_chance_bonus=effect.crit_chance_bonus+0.2)
                if hasattr(effect,'crit_chance_bonus') else effect for effect in action.effects)
            action=replace(action,effects=effects)
        actions.append(action)
    assert gate._isolated_crit_witness(base,replace(changed,actions=tuple(actions)),mod) is None

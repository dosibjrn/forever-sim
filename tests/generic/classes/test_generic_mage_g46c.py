"""G46c root is an actual generic timed status, not fake damage reduction."""
from dataclasses import replace
from src.game.data.forever.mage import build_source_slice
from src.game.model import ControlEffect, PolicyDefinition, PolicyRuleDefinition
from src.v2.generic_backend import _policy_combat_evaluation

def test_frost_nova_source_and_timed_control_in_generic_runtime():
    ir = build_source_slice(10)
    nova = next(a for a in ir.actions if a.id == 'frost_nova:122')
    assert nova.costs[0].amount == 55 and nova.cooldown_s == 25
    assert isinstance(nova.effects[1], ControlEffect)
    assert nova.effects[1].duration_s == 8
    single = PolicyDefinition(id='probe-nova',label='nova then wand',rules=(
        PolicyRuleDefinition('nova','frost_nova:122'),),provenance={'scope':'proof'})
    ev, ex, _ = _policy_combat_evaluation(ir,level=10,policy_override=single)
    kinds = [(e.kind,e.time_s) for e in ex.timeline.events]
    assert any(k=='ControlApplied' for k,_ in kinds)
    # The target may die before expiry: the *application* and expiry scheduling
    # are authoritative, not an ungrounded promise of eight seconds of safety.
    assert any(e.kind=='Damage' and e.action_id=='frost_nova:122' for e in ex.timeline.events)
    assert not any(e.kind=='Damage' and e.action_id=='root' for e in ex.timeline.events)

def test_no_class_specific_root_runtime_fork():
    from pathlib import Path
    runtime = Path('src/game/runtime/simulator.py').read_text().lower()
    assert 'frost_nova' not in runtime and 'if mage' not in runtime

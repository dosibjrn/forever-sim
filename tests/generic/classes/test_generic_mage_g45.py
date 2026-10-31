from pathlib import Path
from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.registry import registered_class_keys
from src.game.model import DamageEffect, PeriodicEffect
from src.v2.generic_backend import _policy_combat_evaluation, build_partial_generic_records
from src.version import SOFTWARE_VERSION


def test_g45_source_adapter_and_scope():
    assert 'mage' in registered_class_keys()
    assert build_game_ir_slice(class_key='mage',level=9) is None
    assert build_game_ir_slice(class_key='mage',level=21) is None
    for level in (10,15,20):
        ir=build_game_ir_slice(class_key='mage',level=level)
        assert ir.actions[0].id=='frostbolt:116'
        assert ir.actions[1].id=='fireball:133'
        assert isinstance(ir.actions[0].effects[0],DamageEffect)
        assert isinstance(ir.actions[1].effects[1],PeriodicEffect)
        assert ir.auto_attacks[0].exclusive_with_casts
        assert ir.provenance['g45_proof_scope']=='mage_L10_20_caster_wand'
        assert len(ir.unsupported_semantics)>=4


def test_g45_generic_cast_and_exclusive_wand_both_damage():
    for level in (10,15,20):
        ir=build_game_ir_slice(class_key='mage',level=level)
        ev,ex,_=_policy_combat_evaluation(ir,level=level)
        assert ev is not None and ex.timeline.target_defeated
        assert ex.timeline.auto_attack_damage>0
        assert any(e.kind=='Damage' and e.action_id=='frostbolt:116' for e in ex.timeline.events)
        assert any(e.kind=='AutoAttackSwing' and e.action_id=='mage:auto:wand' for e in ex.timeline.events)


def test_g45_no_class_combat_fork():
    code=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'if mage' not in code and 'if class_key == "mage"' not in code


def test_g45_release_version():
    assert SOFTWARE_VERSION=='0.11.48.167'

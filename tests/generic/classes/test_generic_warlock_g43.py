from pathlib import Path
from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.registry import registered_class_keys
from src.game.model import PeriodicEffect, SummonEffect
from src.v2.generic_backend import _policy_combat_evaluation


def test_g43_registry_and_scope():
    assert 'warlock' in registered_class_keys()
    assert build_game_ir_slice(class_key='warlock',level=9) is None
    assert build_game_ir_slice(class_key='warlock',level=21) is None
    for level in (10,12,20):
        ir=build_game_ir_slice(class_key='warlock',level=level)
        assert len(ir.companions)==1 and len(ir.timed_summons)==1
        assert isinstance(ir.actions[0].effects[0], SummonEffect)
        assert isinstance(ir.actions[1].effects[0], PeriodicEffect)
        assert ir.actions[1].effects[0].total_base_damage==40.
        assert next(r for r in ir.policies[0].rules if r.action_id=='corruption:172').conditions[0].kind=='aura_missing'
        assert ir.actions[2].id==('shadow_bolt:705' if level>=12 else 'shadow_bolt:695')


def test_g43_generic_pet_and_dot_both_execute():
    for level in (10,12,20):
        ir=build_game_ir_slice(class_key='warlock',level=level)
        ev,ex,_=_policy_combat_evaluation(ir,level=level)
        assert ev is not None and ex.timeline.target_defeated
        assert ex.timeline.damage_by_actor['warlock:imp'] > 0
        assert ex.timeline.damage_by_actor['player'] > 0
        assert ex.timeline.periodic_damage > 0
        assert any(a['action_id']=='summon_imp:688' for a in ex.selected_actions)
        assert any(a['action_id'].startswith('shadow_bolt:') for a in ex.selected_actions)
        assert ex.timeline.target_death_s < 120


def test_g43_no_class_runtime_fork():
    runtime=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'warlock' not in runtime


def test_g43_version():
    from src.version import SOFTWARE_VERSION
    assert tuple(map(int, SOFTWARE_VERSION.split('.'))) >= (0, 11, 48, 165)

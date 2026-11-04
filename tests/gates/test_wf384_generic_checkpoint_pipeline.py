"""Only retained source-IR helpers consumed by the live bounded-joint frontier."""
from dataclasses import replace
import pytest

from src.game.checkpoint_pipeline import checkpoint_enemy, discover_source_damage_seeds
from src.game.data.forever import build_game_ir_slice


@pytest.mark.parametrize('cls,level,hp', [('druid',20,484),('druid',30,955),('mage',30,955),('warrior',30,955)])
def test_checkpoint_enemy_resolves_same_source_profile_without_class_switch(cls,level,hp):
    ir=build_game_ir_slice(class_key=cls,level=level)
    enemy=checkpoint_enemy(ir=ir,level=level)
    assert enemy.hp == hp
    assert enemy.enemy_level == level
    assert enemy.combat_capture_id
    assert enemy.armor > 0
    assert not enemy.exact_forever_enemy_verified
    assert enemy.hp_authority.startswith('CMANGOS_')


def test_mismatched_level_or_missing_source_profile_fail_closed():
    ir=build_game_ir_slice(class_key='mage',level=30)
    with pytest.raises(ValueError,match='LEVEL_IR_MISMATCH'):
        checkpoint_enemy(ir=ir,level=20)
    with pytest.raises(ValueError,match='TARGET_COMBAT_NOT_SOURCED'):
        checkpoint_enemy(ir=replace(ir,provenance={}),level=30)


@pytest.mark.parametrize('cls,level', [('mage',30),('druid',20),('druid',30)])
def test_generic_seed_actions_discovered_for_live_source_frontier(cls,level):
    ir=build_game_ir_slice(class_key=cls,level=level)
    seeds=discover_source_damage_seeds(ir)
    assert seeds and len(seeds)>=2
    ids={action.id for action in ir.actions}
    assert all(r.action_id in ids for policy in seeds for r in policy.rules)
    assert all(not p.provenance['complete_apl_search'] for p in seeds)

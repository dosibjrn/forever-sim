from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_button_discovery import discover_source_combat_buttons
from src.v2.legal_candidate_enumeration import enumerate_legal_source_candidates


def test_mage_source_discovers_offensive_buttons_not_in_seed_policy():
    ir = build_game_ir_slice(class_key='mage', level=10)
    result = discover_source_combat_buttons(ir, level=10)
    canonical = {r.action_id for r in ir.policies[0].rules if r.phase == 'combat'}
    assert {'fireball:133', 'frost_nova:122'} <= set(result['action_ids']) - canonical
    assert not result['complete_policy_search']


def test_druid_excludes_heals_and_modes_from_initial_offensive_buttons():
    result = enumerate_legal_source_candidates(class_key='druid', level=10)
    assert set(result['discovered_combat_buttons']) == {'wrath:5177', 'moonfire:8924', 'source_spell:339'}
    assert any(x['id'] == 'healing_touch:rank@8' and x['reason'] == 'not_offensive' for x in result['discovery_excluded_actions'])


def test_generic_requirement_gates_fail_closed():
    ir = build_game_ir_slice(class_key='mage', level=10)
    a = ir.actions[0]
    changed = replace(ir, actions=(replace(a, requirements=({'kind':'mystery'},)),))
    found = discover_source_combat_buttons(changed, level=10)
    assert not found['action_ids']
    assert found['excluded'][0]['reason'] == 'unsupported_requirement:mystery'
    changed = replace(ir, actions=(replace(a, requirements=({'kind':'minimum_level','value':20},)),))
    assert discover_source_combat_buttons(changed, level=10)['excluded'][0]['reason'] == 'level_locked'


def test_duplicate_actions_fail_closed():
    ir = build_game_ir_slice(class_key='mage', level=10)
    with pytest.raises(ValueError, match='duplicate'):
        discover_source_combat_buttons(replace(ir, actions=(ir.actions[0], ir.actions[0])), level=10)

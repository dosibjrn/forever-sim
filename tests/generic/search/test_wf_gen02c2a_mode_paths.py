from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_mode_search import discover_mode_paths


def test_source_druid_bear_path_is_discovered_without_named_rules():
    ir = build_game_ir_slice(class_key='druid', level=10)
    found = discover_mode_paths(ir, level=10)
    assert any(row['combat_mode'] == 'bear' and row['combat_auto_attack_ids']
               for row in found['paths'])
    assert all(row['status'] == 'DISCOVERED_NOT_SCORED' for row in found['paths'])


def test_source_mode_graph_survives_class_and_mode_renaming():
    ir = build_game_ir_slice(class_key='druid', level=10)
    changed = replace(ir, id='unknown-class', policies=())
    assert discover_mode_paths(changed, level=10)['paths'] == discover_mode_paths(ir, level=10)['paths']


def test_missing_source_exit_fails_closed_no_fake_recovery():
    ir = build_game_ir_slice(class_key='druid', level=10)
    changed = replace(ir, actions=tuple(a for a in ir.actions if a.id != 'cancel_mode:bear'))
    assert not [p for p in discover_mode_paths(changed, level=10)['paths'] if p['combat_mode'] == 'bear']


def test_cap_rejects_instead_of_truncating():
    ir = build_game_ir_slice(class_key='druid', level=20)
    results = discover_mode_paths(ir, level=20)
    if len(results['paths']) > 1:
        with pytest.raises(ValueError, match='cap'):
            discover_mode_paths(ir, level=20, max_paths=1)
    with pytest.raises(ValueError):
        discover_mode_paths(ir, level=20, max_paths=0)

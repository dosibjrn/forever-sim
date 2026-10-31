"""WF398: concurrent 2D packs must pay the same source upkeep/recovery as sequential pulls."""
import json
from dataclasses import replace
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import (
    evaluate_persistent_candidate, prepare_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate():
    ir = build_game_ir_slice(
        class_key='druid', level=30,
        ability_db_path=ROOT / 'data/forever/staged_druid_l30_talents_70338.sqlite',
    )
    stage = json.loads((ROOT / 'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return prepare_candidate(class_key='druid', level=30, stage=stage,
                             source_ir=ir, allow_partial_gear_stats=True)


def test_source_maintenance_is_paid_and_recast_across_100_concurrent_2d_mobs():
    candidate = _candidate()
    result = evaluate_persistent_candidate(candidate, level=30, mobs=100,
                                           pack_size=2, max_wall_s=20)
    assert result['status'] == 'COMPLETE', result
    assert result['mob_completed'] == 100 and result['packs'] == 50
    assert result['maintenance_casts'] >= 2  # source Thorns + Mark, not a synthetic aura
    assert result['maintenance_s'] > 0
    assert result['maintenance_runtime_events'] > 0
    assert result['events'] >= result['maintenance_runtime_events']
    assert abs(result['total_s'] - (result['combat_s'] + result['recovery_s']
                                   + result['maintenance_s'])) < 1e-6


def test_paid_source_cat_exit_reentry_survives_100_concurrent_2d_mobs():
    candidate = _candidate()
    recovery = BetweenPullPolicy(health_fraction=.95, mana_fraction=.90,
                                 exit_action_id='cancel_mode:cat',
                                 reentry_action_id='cat_form:768')
    result = evaluate_persistent_candidate(candidate, level=30, mobs=100,
                                           pack_size=2, recovery_policy=recovery,
                                           max_wall_s=25)
    assert result['status'] == 'COMPLETE', result
    assert result['mob_completed'] == 100 and result['packs'] == 50
    assert result['between_pull_runtime_events'] > 0
    assert result['source_recovery_action_counts']['cancel_mode:cat'] > 0
    assert result['source_recovery_action_counts']['cat_form:768'] > 0
    assert result['maintenance_casts'] >= 2
    assert result['recovery_s'] > 0 and result['events'] > 0


def test_missing_sourced_maintenance_action_fails_closed_in_2d():
    candidate = _candidate()
    ir = replace(candidate.ir, actions=tuple(a for a in candidate.ir.actions
                                              if a.id != 'source_spell:1075'))
    result = evaluate_persistent_candidate(replace(candidate, ir=ir),
                                           level=30, mobs=2, pack_size=2)
    assert result['status'] == 'BLOCKED_SOURCE_MAINTENANCE_UPKEEP', result
    assert result['mob_completed'] == 0

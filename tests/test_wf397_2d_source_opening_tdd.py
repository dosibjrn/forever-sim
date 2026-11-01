"""Real sourced opening must survive 20-yard simultaneous 2D pack movement."""
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import evaluate_repeated_pulls
from src.v2.source_persistent_joint_finalists import prepare_candidate

ROOT = Path(__file__).resolve().parents[1]


def _candidate():
    ir = build_game_ir_slice(class_key='druid', level=30,
        ability_db_path=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    stage = json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return prepare_candidate(class_key='druid', level=30, stage=stage,
        source_ir=ir, allow_partial_gear_stats=True)


def test_sourced_cat_opening_retargets_only_when_2d_enemy_is_reachable():
    candidate = _candidate()
    assert len(candidate.opening) == 2
    result = evaluate_repeated_pulls(ir_slice=candidate.ir, policy=candidate.policy,
        level=30, target_health=60, count=2, pack_size=2,
        schedule_incoming_attacks=True, opening_action_ids=candidate.opening)
    assert len(result.pulls) == 1
    pull = result.pulls[0]
    assert pull['pack_all_defeated']
    assert pull['mob_count'] == 2
    assert pull['event_transitions'] > 0
    assert any(a['action_id'] == candidate.opening[-1] for a in pull['selected_actions'])
    assert result.seconds_per_mob > 0


def test_sourced_cat_opening_persists_across_two_concurrent_packs():
    candidate = _candidate()
    result = evaluate_repeated_pulls(ir_slice=candidate.ir, policy=candidate.policy,
        level=30, target_health=60, count=4, pack_size=2,
        schedule_incoming_attacks=True, opening_action_ids=candidate.opening)
    assert len(result.pulls) == 2
    assert all(p['pack_all_defeated'] and p['mob_count'] == 2 for p in result.pulls)
    assert result.end_time_s > result.start_time_s
    assert result.seconds_per_mob == (result.end_time_s-result.start_time_s)/4

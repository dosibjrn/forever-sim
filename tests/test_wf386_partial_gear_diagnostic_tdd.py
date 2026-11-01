"""Source gear with unsupported effects is runnable only as an explicitly partial diagnostic."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_db_scope import ability_source_scope
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/forever/staged_mage_l30_stamina_70374.sqlite'
EVIDENCE = ROOT / 'evidence/wf383/WF383_MAGE_L30_WAND_GEAR_100MOB.json'


def mage_stage():
    gear = json.loads(EVIDENCE.read_text())['baseline']['gear']
    return {'allocation': {}, 'gear_policy_result': {'winner': {
        'gear': gear, 'winner': {'fallback': 'fire_blast:8412', 'prefix': []}}}}


def mage_ir():
    return build_game_ir_slice(class_key='mage', level=30, ability_db_path=SOURCE)


def test_default_and_strict_preparation_still_fail_closed_on_unknown_weapon_dps():
    with ability_source_scope(SOURCE):
        for strict in (False, True):
            with pytest.raises(ValueError, match='BLOCKED_UNSUPPORTED_GEAR_STATS'):
                prepare_candidate(class_key='mage', level=30, stage=mage_stage(),
                                  source_ir=mage_ir(), strict_l2_item_effects=strict)


def test_explicit_partial_diagnostic_runs_source_gear_with_uncertainty():
    with ability_source_scope(SOURCE):
        candidate = prepare_candidate(class_key='mage', level=30, stage=mage_stage(),
                                      source_ir=mage_ir(), allow_partial_gear_stats=True)
        coverage = candidate.ir.provenance['gear_effect_coverage']
        assert coverage['complete'] is False
        assert coverage['mode'] == 'EXPLICIT_PARTIAL_DIAGNOSTIC_NOT_CHECKPOINT_L2'
        assert coverage['unsupported_stats']['weapon_dps'] > 0
        assert coverage['unsupported_stats'].get('stamina', 0) == 0
        outcome = evaluate_persistent_candidate(candidate, level=30, mobs=3,
                                                max_wall_s=5, max_cpu_s=5,
                                                max_total_events=10000)
        assert outcome['status'] == 'COMPLETE', outcome
        assert outcome['events'] > 0


def test_partial_diagnostic_cannot_claim_strict_l2():
    with ability_source_scope(SOURCE):
        with pytest.raises(ValueError, match='PARTIAL_GEAR_DIAGNOSTIC_CANNOT_BE_STRICT'):
            prepare_candidate(class_key='mage', level=30, stage=mage_stage(),
                              source_ir=mage_ir(), strict_l2_item_effects=True,
                              allow_partial_gear_stats=True)


def test_cold_worker_resolves_mage_checkpoint_not_hardcoded_druid():
    from tools.wf353_p3_eval_worker import run
    result = run(mage_stage(), SOURCE, allow_partial_gear_stats=True)
    assert result['status'] == 'COMPLETE', result
    assert result['checkpoint'] == {'class_key': 'mage', 'level': 30}
    assert result['gear_effect_coverage']['complete'] is False
    assert result['gear_effect_coverage']['unsupported_stats']['weapon_dps'] > 0
    assert result['events'] > 0
    assert result['mean_s_per_mob'] > 0


def test_cold_subprocess_partial_mage_100mob_is_opt_in_and_source_bound():
    from src.game.data.forever.source_checkpoint_p3_swaps import subprocess_stage_100mob
    blocked = subprocess_stage_100mob(stage=mage_stage(), source_db_path=SOURCE, timeout_s=10.)
    assert blocked['status'] != 'COMPLETE', blocked
    complete = subprocess_stage_100mob(stage=mage_stage(), source_db_path=SOURCE,
                                        allow_partial_gear_stats=True, timeout_s=10.)
    assert complete['status'] == 'COMPLETE', complete
    assert complete['checkpoint'] == {'class_key': 'mage', 'level': 30}
    assert complete['gear_effect_coverage']['complete'] is False
    assert complete['mean_s_per_mob'] > 0


def test_atomic_twohand_swap_evicts_only_implicit_offhand():
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_stage
    stage = substituted_stage(stage=mage_stage(), class_key='mage', level=30,
                              slot='weapon', item_id=6689)
    slots = stage['gear_policy_result']['winner']['gear']['slots']
    assert slots['weapon']['item_id'] == 6689
    assert 'offhand' not in slots
    assert stage['gear_policy_result']['winner']['gear']['item_count'] == 17
    outcome = run_mage_100mob(stage)
    assert outcome['status'] == 'COMPLETE', outcome


def run_mage_100mob(stage):
    from tools.wf353_p3_eval_worker import run
    return run(stage, SOURCE, allow_partial_gear_stats=True)


def test_atomic_twohand_plus_explicit_offhand_still_rejected():
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    with pytest.raises(ValueError, match='P3_SWAP_ILLEGAL_EQUIPMENT'):
        substituted_multi_stage(stage=mage_stage(), class_key='mage', level=30,
                                swaps={'weapon': 6689, 'offhand': 249394})


def test_untyped_trinket_effect_remains_unknown_in_partial_diagnostic():
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_stage
    stage = substituted_stage(stage=mage_stage(), class_key='mage', level=30,
                              slot='trinket1', item_id=276895)
    with ability_source_scope(SOURCE):
        with pytest.raises(ValueError, match='BLOCKED_UNTYPED_ITEM_EFFECTS'):
            prepare_candidate(class_key='mage', level=30, stage=stage,
                              source_ir=mage_ir(), strict_l2_item_effects=True)
        candidate = prepare_candidate(class_key='mage', level=30, stage=stage,
                                      source_ir=mage_ir(), allow_partial_gear_stats=True)
    unknown = candidate.ir.provenance['gear_effect_coverage']['unresolved_item_effects']
    assert 'item_effect_tooltip_not_typed' in unknown['trinket1']
    assert candidate.ir.provenance['gear_effect_coverage']['complete'] is False

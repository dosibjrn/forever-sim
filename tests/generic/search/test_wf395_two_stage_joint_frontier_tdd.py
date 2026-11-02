"""WF395 TDD: real source-bounded two-stage search with paid 100-mob finalists."""
from pathlib import Path
import json

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (search_bounded_joint_frontier,
                                                  source_gear_seed_stage)

ROOT=Path(__file__).resolve().parents[3]


def _scenario(class_key):
    db=ROOT / ('data/forever/staged_mage_l30_talent_positions_70374.sqlite'
               if class_key=='mage' else 'data/forever/staged_druid_l30_talents_70338.sqlite')
    ir=build_game_ir_slice(class_key=class_key,level=30,ability_db_path=db)
    if class_key=='mage':
        evidence=ROOT/'evidence/wf383/WF383_MAGE_L30_WAND_GEAR_100MOB.json'
        gear=json.loads(evidence.read_text())['baseline']['gear']
        stage=source_gear_seed_stage(gear=gear,ir=ir,source_evidence=str(evidence))
    else:
        stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    return ir,stage


def _assert_real_finalists(result):
    assert result['search_strategy']=='screen_then_full'
    assert result['paid_candidates']>=result['complete_100mob_candidates']+2
    assert result['screen_complete_candidates']>result['complete_100mob_candidates']
    assert result['complete_100mob_candidates']>=1
    assert result['events']>0
    assert result['winner']['status']=='COMPLETE'
    assert result['winner']['mobs']==100
    assert result['winner']['full_events']>0
    assert result['winner']['seconds_per_mob']>0
    assert result['unique_full_builds']<=result['paid_candidates']
    assert result['winner']['seconds_per_mob']==min(
        r['seconds_per_mob'] for r in result['rows'] if r['status']=='COMPLETE')
    assert all(r.get('seconds_per_mob') is None for r in result['rows']
               if r['status']!='COMPLETE')
    assert result['screen_phase_wall_s']>0
    assert result['finalist_phase_wall_s']>0
    assert not result['eligible_for_checkpoint_acceptance']


def test_mage_two_stage_paid_search_reaches_many_screens_and_real_100mob_finalists():
    ir,stage=_scenario('mage')
    result=search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=1,
        max_policies=12,max_recovery_policies=2,max_paid_builds=24,
        max_cpu_s=14.,per_candidate_wall_s=3.,screen_then_finalists=True,
        max_finalists=3)
    _assert_real_finalists(result)
    assert result['screen_complete_candidates']>=6
    assert len({r['policy_signature'] for r in result['rows']})>=4
    assert any(r['gear_move']!='incumbent' for r in result['rows'])
    assert any(r['recovery']!='incumbent' for r in result['rows'])


def test_druid_two_stage_search_preserves_full_100mob_and_reports_four_axes():
    ir,stage=_scenario('druid')
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=2,max_gear_moves=1,
        max_policies=5,max_recovery_policies=2,max_paid_builds=25,
        max_cpu_s=25.,per_candidate_wall_s=5.,screen_then_finalists=True,
        max_finalists=3)
    _assert_real_finalists(result)
    assert result['talent_allocations_proposed']>=2
    assert result['policy_variants']>=2
    assert result['recovery_variants']>=2
    assert result['full_evaluated_candidates']<=3
    assert result['screen_complete_candidates']>=result['full_evaluated_candidates']


def test_two_stage_finalist_budget_must_be_positive():
    ir,stage=_scenario('mage')
    try:
        search_bounded_joint_frontier(class_key='mage',level=30,
            source_ir=ir,seed_stage=stage,max_cpu_s=2.,
            screen_then_finalists=True,max_finalists=0)
    except ValueError as e:
        assert 'INVALID_JOINT_SEARCH_BUDGET' in str(e)
    else:
        raise AssertionError('zero finalist budget must not silently run a screen-only search')



def test_single_finalist_retains_fastest_real_paid_build_over_slower_control():
    """A one-slot 100-mob budget must not silently discard the paid winner.

    Compare genuine source-legal Mage L30 equipment variants using the
    production persistent CombatRuntime, then hand those measured screens to
    the production finalist selector. The slower legal build is the control.
    This is not a full P4 acceptance or a synthetic score.
    """
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    from src.v2.source_persistent_slot_search import _source_slot_proposals
    from src.v2.source_persistent_joint_finalists import (
        prepare_candidate, evaluate_persistent_candidate)
    from src.v2.source_bounded_joint_frontier import _select_screen_finalists
    from src.game.policy_evolution import _identity as policy_identity

    ir, seed = _scenario('mage')
    gear = seed['gear_policy_result']['winner']['gear']
    moves, _ = _source_slot_proposals(
        class_key='mage', level=30, base=gear, per_slot=3,
        max_proposals=24)
    stages = [('source_seed', seed)]
    for slot, item in moves:
        try:
            variant = substituted_multi_stage(
                stage=seed, class_key='mage', level=30,
                swaps={slot: int(item.item_id)})
        except (ValueError, KeyError):
            continue
        stages.append((f'{slot}:{item.item_id}', variant))
    paid = []
    for label, stage in stages[:16]:
        candidate = prepare_candidate(
            class_key='mage', level=30, stage=stage, source_ir=ir,
            allow_partial_gear_stats=True)
        result = evaluate_persistent_candidate(
            candidate, level=30, mobs=2, max_total_events=200000)
        if result['status'] == 'COMPLETE':
            paid.append((float(result['mean_s_per_mob']), label, candidate, result))
    assert len(paid) >= 2, paid
    paid.sort(key=lambda entry: entry[0])
    fastest, slowest = paid[0], paid[-1]
    assert slowest[0] > fastest[0], [(x[0], x[1]) for x in paid]

    def screened(entry, *, control):
        score, label, candidate, result = entry
        row = {
            'screen_s_per_mob': score, 'allocation': candidate.allocation,
            'gear_move': 'incumbent' if control else label,
            'policy': 'incumbent', 'policy_signature': policy_identity(candidate.policy),
            'policy_ir': candidate.policy.as_dict(), 'recovery': 'always',
            'equipped_gear': candidate.source_stage['gear_policy_result']['winner']['gear'],
            'is_control': control, 'screen_events': result['events'],
            'screen_status': result['status'],
        }
        return row, candidate, None

    finalists = _select_screen_finalists(
        [screened(slowest, control=True), screened(fastest, control=False)],
        max_finalists=1)
    assert len(finalists) == 1
    assert finalists[0][0]['screen_s_per_mob'] == fastest[0]
    assert not finalists[0][0]['is_control']

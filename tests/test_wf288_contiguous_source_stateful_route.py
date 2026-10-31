"""Production L2 routes: not source-complete or acquisition-complete claims."""
from copy import deepcopy
import pytest
from src.v2.source_stateful_level_route import search_stateful_contiguous_route


OPTS=dict(max_candidates_per_level=1,beam_width=1,attempts_per_candidate=6,
          events_per_candidate=1000,global_event_cap=9000)


def test_druid_real_l10_15_no_respec_and_resume_scratch_equality():
    scratch=search_stateful_contiguous_route(class_key='druid',end_level=15,**OPTS)
    prefix=search_stateful_contiguous_route(class_key='druid',end_level=12,**OPTS)
    resumed=search_stateful_contiguous_route(class_key='druid',start_level=13,
                                             end_level=15,resume_from=prefix,**OPTS)
    assert scratch['status']=='EVALUATED_BOUNDED_CONTIGUOUS_NAKED_TALENT_ROUTE'
    assert resumed['status']==scratch['status']
    assert resumed['bounded_route']==scratch['bounded_route']
    assert len(scratch['bounded_route'])==6
    assert resumed['resume_verification']['scratch_verified']
    assert resumed['resume_verification']['events_charged']>0
    for level,row in enumerate(scratch['bounded_route'],start=10):
        assert row['level']==level and sum(row['talents'].values())==level-9
        assert row['score_s_per_mob']>0 and row['source_context']
    assert scratch['budget']['charged_event_transitions']<=OPTS['global_event_cap']
    assert resumed['budget']['charged_event_transitions']<=OPTS['global_event_cap']
    assert scratch['fully_validated_class_level_checkpoints']==0
    assert not scratch['legal_complete_leveling_route']


def test_changed_source_or_unverified_previous_level_cannot_resume():
    prefix=search_stateful_contiguous_route(class_key='druid',end_level=11,**OPTS)
    corrupted=deepcopy(prefix)
    corrupted['bounded_route'][0]['source_context']='source-changed'
    with pytest.raises(ValueError,match='fingerprint changed'):
        search_stateful_contiguous_route(class_key='druid',start_level=12,
                                        end_level=12,resume_from=corrupted,**OPTS)
    corrupted=deepcopy(prefix)
    corrupted['level_reports'][1]['evaluations'][0]['scratch_verified']=False
    with pytest.raises(ValueError,match='no matching scratch-verified L2'):
        search_stateful_contiguous_route(class_key='druid',start_level=12,
                                        end_level=12,resume_from=corrupted,**OPTS)


def test_hunter_l10_missing_executable_talent_fails_closed():
    r=search_stateful_contiguous_route(class_key='hunter',end_level=12,**OPTS)
    assert r['status']=='BLOCKED_PARTIAL_BOUNDED_ROUTE'
    assert r['completed_level_count']==0
    assert r['blocked']['reason']=='NO_SOURCE_EXECUTABLE_LEGAL_NEXT_TALENT_POINT'
    assert r['budget']['l2_attempts']==0
    assert not r['legal_complete_leveling_route']


def test_cross_class_real_l2_and_hard_global_event_cap():
    for key in ('mage','paladin','rogue','warrior'):
        r=search_stateful_contiguous_route(class_key=key,end_level=12,**OPTS)
        assert r['status']=='EVALUATED_BOUNDED_CONTIGUOUS_NAKED_TALENT_ROUTE'
        assert len(r['bounded_route'])==3
        assert r['budget']['l2_attempts']>0
        assert r['budget']['charged_event_transitions']<=OPTS['global_event_cap']
    low=search_stateful_contiguous_route(class_key='druid',end_level=15,
        max_candidates_per_level=2,beam_width=1,attempts_per_candidate=6,
        events_per_candidate=1000,global_event_cap=300)
    assert low['budget']['charged_event_transitions']<=300
    assert low['status']=='BLOCKED_PARTIAL_BOUNDED_ROUTE'
    assert low['completed_level_count']<6


def test_canonical_classic_hp_l1_10_no_longer_clamped_to_l11():
    from src.shared.leveling.objective import representative_hp
    # CMaNGOS unit class=1 BaseHealthExp0, explicit Classic proxy source.
    assert [representative_hp(l) for l in range(1,12)] == [
        42.,55.,71.,86.,102.,120.,137.,156.,176.,198.,222.]
    assert representative_hp(20)==484.


def test_druid_l1_12_full_cycle_join_and_source_scenario_invalidation(monkeypatch):
    from src.v2.source_stateful_level_route import (
        search_source_pretalent_prefix,join_source_bounded_leveling_route)
    from src.v2.source_stateful_budgeted import source_execution_context
    from src.game.data.forever.registry import build_game_ir_slice
    pre=search_source_pretalent_prefix(class_key='druid')
    talent=search_stateful_contiguous_route(class_key='druid',end_level=12,**OPTS)
    joined=join_source_bounded_leveling_route(pre,talent)
    assert joined['status']=='EVALUATED_BOUNDED_CONTIGUOUS_L1_TO_N'
    assert [r['level'] for r in joined['bounded_route']]==list(range(1,13))
    assert all(r['score_s_per_mob']>0 for r in joined['bounded_route'])
    assert not joined['legal_complete_leveling_route']
    assert joined['fully_validated_class_level_checkpoints']==0
    ir=build_game_ir_slice(class_key='druid',level=1)
    before=source_execution_context(ir)
    import src.shared.leveling.objective as objective
    monkeypatch.setitem(objective.MOB_BASE_HP,1,43)
    assert source_execution_context(ir)!=before
    with pytest.raises(ValueError,match='source/engine/scenario mismatch'):
        join_source_bounded_leveling_route(pre,talent)


def test_other_class_pretalent_missing_ir_does_not_claim_route():
    from src.v2.source_stateful_level_route import search_source_pretalent_prefix
    r=search_source_pretalent_prefix(class_key='hunter')
    assert r['status']=='BLOCKED_PARTIAL_PRETALENT'
    assert r['blocked']['reason']=='MISSING_CANONICAL_GAME_IR'
    assert r['bounded_route']==[]


def test_packaged_druid_l1_60_bounded_evidence_still_matches_current_source():
    """Historical .288 evidence is stale under .289; require native replay.

    Retain the original historical artifact unchanged, and use the .289
    independently re-executed evidence before certifying source-scenario
    continuity. A source/engine patch must never reuse historical hashes.
    """
    import json
    from pathlib import Path
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.talents import apply_talent_selection
    from src.v2.source_stateful_budgeted import source_execution_context
    from src.v2.source_reference_route_evidence import checked_reference_druid_route
    from src.version import SOFTWARE_VERSION
    root=Path(__file__).resolve().parents[1]
    historical=json.loads((root/'WF288_RELEASE_DRUID_L1_60_BOUNDED_ROUTE.json').read_text())
    assert len(historical['bounded_route']) == 60
    assert historical['status']=='EVALUATED_BOUNDED_CONTIGUOUS_L1_TO_N'
    assert any(
        source_execution_context(apply_talent_selection(
            build_game_ir_slice(class_key='druid',level=row['level']),
            row['talents'],level=row['level'])[0]) != row['source_context']
        for row in historical['bounded_route'])
    replay,rows=checked_reference_druid_route(root,version=SOFTWARE_VERSION)
    assert replay['valid'],replay
    assert replay['independently_replayed_levels']==60
    assert len(rows)==60

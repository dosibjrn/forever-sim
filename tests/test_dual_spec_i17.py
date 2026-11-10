from __future__ import annotations

import pytest

from src.v2.decision_result import DecisionResult, RouteResult
from src.v2.dual_spec import build_status, solve_decision_result
from src.v2.path_dp import LevelNode, PathResult, PathStep


def _path(name: str, scores: dict[int, float]) -> PathResult:
    steps=[]
    cumulative=0.0
    for i,(level,cost) in enumerate(sorted(scores.items())):
        cumulative += float(cost)
        node=LevelNode(
            level=level,
            talents=(name, level),
            score_s_per_100=float(cost),
            source='i17-fixture',
            details={
                'allocation':f'{name}@{level}',
                'talent_family':name,
                'combat_profile':name,
                'gear':f'{name}_gear',
                'pull_size':1,
                'rotation':f'{name}_rotation',
            },
        )
        steps.append(PathStep(node,'start' if i==0 else 'point',None,0,cumulative))
    return PathResult(tuple(steps),cumulative,0,max(scores))


def _result(target: int=23) -> DecisionResult:
    a=_path('frost',{20:10,21:10,22:100,23:100})
    b=_path('fire',{20:110,21:110,22:10,23:10})
    unconstrained=_path('best',{20:30,21:30,22:30,23:30})
    routes={
        'unconstrained':RouteResult('unconstrained',target,'available',{'kind':'unconstrained'},unconstrained),
        'frost':RouteResult('frost',target,'available',{'kind':'tree_points','tree':'frost'},a),
        'fire':RouteResult('fire',target,'available',{'kind':'tree_points','tree':'fire'},b),
    }
    return DecisionResult('mage',(),{target:routes},published_targets=(target,))


def test_i17_unlock_after_target_is_not_architecture_block():
    row=build_status('mage',30,_result(),unlock_level=40,target_level=23)
    assert row['status']=='unlock_after_target'
    assert row['pair'] is None


def test_i17_uses_only_canonical_decision_result_routes_and_switches_by_level():
    row=solve_decision_result(_result(),unlock_level=20,target_level=23,verified_level_cap=30)
    assert row['status']=='available'
    assert row['authority']=='canonical_level_frontier_dp'
    assert row['method']=='canonical_decision_result_route_pair_v1'
    assert row['switch_model']=='level_boundaries_only'
    assert {row['pair']['A']['route'],row['pair']['B']['route']}=={'frost','fire'}
    assert [(p['start_level'],p['end_level'],p['route']) for p in row['phases']]==[
        (20,21,'frost'),(22,23,'fire')
    ]
    assert len(row['switches'])==1
    assert row['switches'][0]['level']==22
    assert row['switches'][0]['to_route']=='fire'
    assert row['switches'][0]['from_slot'] != row['switches'][0]['to_slot']
    assert 'L22' in row['switch_recommendation']


def test_i17_pair_cannot_be_worse_than_best_single_canonical_route_under_level_boundary_switch_model():
    row=solve_decision_result(_result(),unlock_level=20,target_level=23,verified_level_cap=30)
    assert row['objective_seconds'] <= row['best_single_objective_seconds'] + 1e-12
    assert row['gain_seconds'] >= 0
    assert row['gain_percent'] >= 0


def test_i17_provisional_metadata_survives_above_verified_cap():
    row=solve_decision_result(_result(),unlock_level=20,target_level=23,verified_level_cap=21)
    assert row['status']=='available'
    assert row['uses_unverified_levels'] is True
    assert row['unverified_from_level']==22
    assert 'verified snapshot ends at level 21' in row['confidence_note']


def test_i17_deterministic_pair_result():
    a=solve_decision_result(_result(),unlock_level=20,target_level=23,verified_level_cap=30)
    b=solve_decision_result(_result(),unlock_level=20,target_level=23,verified_level_cap=30)
    assert a['pair']==b['pair']
    assert a['phases']==b['phases']
    assert a['objective_seconds']==pytest.approx(b['objective_seconds'])


def test_i17_unrestricted_single_baseline_prevents_fictitious_dual_savings():
    """The user can keep the already-faster unrestricted single-spec route."""
    result = _result()
    fast = _path('best_single', {20:10, 21:10, 22:10, 23:10})
    routes = dict(result.targets[23])
    routes['unconstrained'] = RouteResult(
        'unconstrained', 23, 'available', {'kind': 'unconstrained'}, fast)
    actual = DecisionResult('mage', (), {23: routes}, published_targets=(23,))
    row = solve_decision_result(actual, unlock_level=20, target_level=23,
                                verified_level_cap=30)
    assert row['status'] == 'available'
    assert row['best_single_route'] == 'unconstrained'
    assert row['best_single_objective_seconds'] == pytest.approx(40)
    assert row['pair_candidate_objective_seconds'] == pytest.approx(40)
    assert row['objective_seconds'] == pytest.approx(40)
    assert row['gain_seconds'] == 0
    assert row['recommended_strategy'] == 'single_spec'
    assert row['dual_spec_purchase_recommended'] is False
    assert row['switches'] == []
    assert row['choices'] == []
    assert 'No optional dual-spec purchase' in row['switch_recommendation']
    # Candidate pair evidence is retained without presenting it as selected.
    assert row['pair_candidate_switches'][0]['level'] == 22


def test_i17_optional_single_baseline_survives_missing_second_named_route():
    result = _result()
    routes = {key: value for key, value in result.targets[23].items()
              if key != 'fire'}
    actual = DecisionResult('mage', (), {23: routes}, published_targets=(23,))
    row = solve_decision_result(actual, unlock_level=20, target_level=23,
                                verified_level_cap=30)
    assert row['status'] == 'insufficient_canonical_routes'
    assert row['best_single_route'] == 'unconstrained'
    assert row['best_single_objective_seconds'] == pytest.approx(120)
    assert row['recommended_strategy'] == 'single_spec'
    assert row['dual_spec_purchase_recommended'] is False

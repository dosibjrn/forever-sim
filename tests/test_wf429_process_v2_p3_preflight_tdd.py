"""Approved PROCESS v2: a *complete external catalogue* is not a P3 gate.

Only the current legal top-five-by-ilvl contextual scoring smoke can PASS P3;
missing that smoke is a blocker. Missing universe attestation is advisory.
"""
from src.game.checkpoint_pipeline import checkpoint_preflight


def test_available_canonical_items_get_a_p3_v2_smoke_blocker_not_external_capture_gate():
    for cls in ('druid','mage'):
        result=checkpoint_preflight(class_key=cls,level=30)
        codes={b['code'] for b in result['blockers']}
        assert result['equipment_l0_inventory']['legal_items']>0
        assert result['equipment_l0_inventory']['is_build_specific_top5'] is False
        assert 'P3_ILVL_TOP5_CONTEXTUAL_SMOKE_NOT_RUN' in codes
        assert 'P3_SOURCE_ITEM_INVENTORY_INCOMPLETE' not in codes
        advisories={a['code'] for a in result['advisories']}
        assert 'SOURCE_CLASS_ITEM_MEMBERSHIP_UNATTESTED_ADVISORY' in advisories
        assert result['eligible_for_checkpoint_acceptance'] is False


def test_preflight_remains_red_on_unverified_enemy_and_missing_executable_talents():
    r=checkpoint_preflight(class_key='druid',level=30)
    codes={x['code'] for x in r['blockers']}
    assert 'FOREVER_NAMED_ENEMY_UNVERIFIED' in codes
    assert 'L2_TALENT_RANK_EXECUTION_INCOMPLETE' in codes
    assert 'JOINT_BUILD_OPTIMUM_NOT_CERTIFIED' in codes

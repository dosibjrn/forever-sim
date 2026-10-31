"""WF412: paid non-degenerate Stamina and equipped-feral DPS effects."""
from dataclasses import replace
from pathlib import Path
import json
from src.game.gear import _replace_equipped_weapon_dps
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity

ROOT=Path(__file__).resolve().parents[1]

def _candidate():
    stage=json.loads((ROOT/'evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    return prepare_candidate(class_key='druid',level=20,stage=stage)


def test_feral_named_weapon_swap_rewrites_real_damage_and_paid_kills():
    candidate=_candidate()
    claw=next(a for a in candidate.ir.actions if a.family_key=='claw')
    original=next(e for e in claw.effects if e.effect_type=='weapon_damage').damage_source.flat_dps
    assert abs(original - 19.71) < 1e-6  # observed named item's actual gear DPS, not 20.44 scenario anchor
    improved_ir=_replace_equipped_weapon_dps(candidate.ir, original+10)
    improved_claw=next(a for a in improved_ir.actions if a.family_key=='claw')
    improved=next(e for e in improved_claw.effects if e.effect_type=='weapon_damage').damage_source.flat_dps
    assert abs(improved-original-10)<1e-8
    before=evaluate_persistent_candidate(candidate,level=20,mobs=8)
    after=evaluate_persistent_candidate(replace(candidate,ir=improved_ir),level=20,mobs=8)
    assert before['status']==after['status']=='COMPLETE'
    assert after['mean_s_per_mob'] < before['mean_s_per_mob']


def test_stamina_recovery_reselection_has_positive_paid_100mob_value():
    candidate=_candidate()
    policies=(
        BetweenPullPolicy(.25,.10,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'),
        BetweenPullPolicy(.50,.10,exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768'),
    )
    r=reoptimized_stat_sensitivity(candidate=candidate,stat='stamina',delta=20,
                                   level=20,recovery_policies=policies)
    assert r['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert r['positive'] and r['weight_s_saved_per_mob_per_unit']>0
    assert all(x['mobs']==100 for x in [r])
    assert r['best']['before']['recovery_s'] > r['best']['after']['recovery_s']
    assert r['best']['before']['between_pull_full_recoveries'] > r['best']['after']['between_pull_full_recoveries']


def test_sensitivity_cannot_fake_100mob_or_empty_frontier():
    import pytest
    c=_candidate()
    with pytest.raises(ValueError,match='INVALID_STAT_SENSITIVITY_REQUEST'):
        reoptimized_stat_sensitivity(candidate=c,stat='stamina',delta=20,
                                     level=20,mobs=20,recovery_policies=(None,))
    with pytest.raises(ValueError,match='EMPTY_OR_DUPLICATED_POLICY_FRONTIER'):
        reoptimized_stat_sensitivity(candidate=c,stat='stamina',delta=20,
                                     level=20,recovery_policies=())

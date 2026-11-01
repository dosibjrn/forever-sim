"""WF263: observed L2 ordering, not L1 self-confidence, decides L1 spend."""
import pytest
from src.v2.source_stateful_budgeted import _l1_value_evidence, run_source_stateful_budgeted
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def test_l1_gate_requires_held_out_l2_rank_and_error_evidence():
    actual = [10., 12., 14., 16.]
    samples = [{'actual_s': t, 'l0_predicted_s': p0, 'l1_predicted_s': p1}
               for t, p0, p1 in zip(actual, [16., 14., 12., 10.],
                                     [10.2, 12.2, 14.2, 16.2])]
    good = _l1_value_evidence(samples)
    assert good['l1_has_observed_ranking_value']
    assert good['l1_correct_pairs'] == 6 and good['l0_correct_pairs'] == 0
    assert not _l1_value_evidence(samples[:2])['l1_has_observed_ranking_value']
    bad = _l1_value_evidence([{**s, 'l0_predicted_s': s['l1_predicted_s'],
                              'l1_predicted_s': s['l0_predicted_s']} for s in samples])
    assert not bad['l1_has_observed_ranking_value']
    # Identical L2 outcomes provide no evidence of superior ranking.
    tied = _l1_value_evidence([{**s, 'actual_s': 10.} for s in samples])
    assert tied['comparable_pairs'] == 0 and not tied['l1_has_observed_ranking_value']


def test_real_druid_l1_gate_reduces_paid_work_without_score_substitution():
    common = dict(class_key='druid', level=10, max_l2_attempts=40,
                  max_event_transitions=1500)
    legacy = run_source_stateful_budgeted(**common, l1_mode='legacy')
    gated = run_source_stateful_budgeted(**common, l1_mode='value_gated')
    assert gated['l1_attempts'] < legacy['l1_attempts']
    assert gated['event_transitions'] < legacy['event_transitions'] <= 1500
    assert gated['winner']['score_s_per_mob'] == legacy['winner']['score_s_per_mob']
    assert gated['l1_value_evidence']['l1_correct_pairs'] < gated['l1_value_evidence']['l0_correct_pairs']
    assert any(x['reason']=='no_measured_ranking_value' and not x['use_l1']
               for x in gated['l1_decisions'])
    assert all(x['matches_scratch'] for x in gated['scratch_verification'])


def test_l1_gate_mode_is_validated_and_propagated_to_real_joint_search():
    with pytest.raises(ValueError, match='l1_mode'):
        run_source_stateful_budgeted(class_key='druid', level=10, l1_mode='unknown')
    r = run_source_budgeted_joint_talents(class_key='druid', level=10,
        max_evaluations=20, evaluations_per_talent=12, initial_search=6,
        search_per_gear=6, max_gear_states=1, policy_search_backend='stateful',
        max_event_transitions=650, stateful_l1_mode='value_gated')
    assert r['stateful_l1_mode']=='value_gated'
    assert r['attempted']==r['evaluated']+r['blocked']<=20
    assert r['event_transitions']<=650
    assert r['winner']['score_s_per_mob']>0


def test_production_joint_default_disables_unproven_l1_but_keeps_l2():
    r = run_source_budgeted_joint_talents(class_key='mage', level=20,
        max_evaluations=24, evaluations_per_talent=12, initial_search=6,
        search_per_gear=6, max_gear_states=1, policy_search_backend='stateful',
        max_event_transitions=1300)
    assert r['stateful_use_l1'] is False
    assert r['stateful_l1_attempts'] == 0
    assert r['winner']['score_s_per_mob'] > 0
    assert r['event_transitions'] <= 1300

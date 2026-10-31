import copy, json
from pathlib import Path
from src.game.data.forever.source_checkpoint_p3_acceptance import l0_gear_top5_certificate
from src.game.data.forever.source_checkpoint_p3_consistency import audit_stat_weight_curves
ROOT=Path(__file__).resolve().parents[1]

def _report():return json.loads((ROOT/'evidence/wf352/WF352_L30_P3_TOP5.json').read_text())
def _curves():return json.loads((ROOT/'evidence/wf352/WF352_P3_ADVERSARIAL_CURVES.json').read_text())

def test_previous_pass_is_revoked_because_it_only_measured_single_small_steps():
    cert=l0_gear_top5_certificate(_report())
    assert not cert['pass']
    assert 'MISSING_100MOB_MULTISCALE_VALIDATION' in cert['failures']
    assert 'UNVALIDATED_NEGATIVE_GEAR_WEIGHT' in cert['failures']

def test_real_100mob_source_probes_detect_both_degeneracies():
    audit=audit_stat_weight_curves(report=_report(),curves=_curves())
    assert not audit['pass']
    assert 'ADVERSE_POSITIVE_STAT_PERTURBATION' in audit['axes']['agility']['issues']
    assert 'NONLINEAR_SLOPE_EXTRAPOLATION_UNSAFE' in audit['axes']['weapon_dps']['issues']
    cert=l0_gear_top5_certificate(_report(),stat_curve_audit=audit)
    assert not cert['pass']
    assert 'NONLINEAR_STAT_WEIGHTS_INVALIDATE_TOP5' in cert['failures']

def test_mismatched_candidate_invalidates_curve_evidence():
    curve=_curves(); curve['build_identity_sha256']='wrong'
    a=audit_stat_weight_curves(report=_report(),curves=curve)
    assert not a['pass'] and 'AUDIT_WRONG_BUILD_IDENTITY' in a['failures']

def test_monotonic_nearlinear_probe_can_be_accepted_by_consistency_algorithm():
    report=_report(); curve=_curves()
    base=report['stat_weights']['base_s_per_mob']
    for axis,step in [('agility',20.),('weapon_dps',10.)]:
        curve['axes'][axis]['probes']=[
            {'delta':step,'s_per_mob':base-0.02,'status':'COMPLETE'},
            {'delta':step*2.,'s_per_mob':base-0.04,'status':'COMPLETE'}]
    audit=audit_stat_weight_curves(report=report,curves=curve)
    assert audit['pass']
    # Even an otherwise stable multiscale curve cannot whitewash the original
    # negative agility coefficient inside the old ranking contributions.
    assert 'UNVALIDATED_NEGATIVE_GEAR_WEIGHT' in l0_gear_top5_certificate(report,stat_curve_audit=audit)['failures']

def test_bad_top5_source_still_fails_with_audited_model():
    d=_report()
    d['slots']['weapon']['weighted_top'][0]['item_url']=''
    assert 'TOP_FIVE_MISSING_SOURCE_URL' in l0_gear_top5_certificate(d)['failures']

def test_degenerate_zero_model_still_fails():
    d=_report()
    for v in d['stat_weights']['weights'].values():v['weight_s_saved_per_mob_per_unit']=None
    assert 'DEGENERATE_WEIGHT_MODEL' in l0_gear_top5_certificate(d)['failures']

"""Large, 100-mob, two-step stat perturbations must not be silently regressed."""
import json
from pathlib import Path
from types import SimpleNamespace
from src.game.data.forever.source_checkpoint_p3_weights import PROBE_STEPS
from src.game.data.forever.source_checkpoint_p3_consistency import audit_stat_weight_curves
from src.game.data.forever import source_checkpoint_p3_isolated as iso


def _complete_linear(q,candidate,stat,delta,level,mobs,weapon):
    q.put({'status':'COMPLETE','s_per_mob':10.-0.02*delta,'events':100})


def test_coarse_step_minimums_are_source_inputs_not_effect_coefficients():
    assert PROBE_STEPS['agility'] >= 20.
    assert PROBE_STEPS['weapon_dps'] >= 10.


def test_both_coarse_deltas_are_actually_run_and_cached(tmp_path,monkeypatch):
    candidate=SimpleNamespace(source_stage={
        'gear_policy_result':{'winner':{'gear':{'slots':{'weapon':{'weapon_dps':17.}}}}},
        'source_context_sha256':'context'}, ir=SimpleNamespace(actor=SimpleNamespace(base_stats={})))
    cat=tmp_path/'items.sqlite';cat.write_bytes(b'catalogue')
    monkeypatch.setattr(iso,'_identity',lambda stage:'build')
    monkeypatch.setattr(iso,'catalogue_path',lambda:cat)
    monkeypatch.setattr(iso,'available_items',lambda *a,**k:[SimpleNamespace()])
    monkeypatch.setattr(iso,'_features',lambda row:{'agility':20.,'weapon_dps':12.})
    monkeypatch.setattr(iso,'executable_gear_stats',lambda ir:('agility','weapon_dps'))
    monkeypatch.setattr(iso,'context_weapon_speed_semantics',lambda ir:'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY')
    out=iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
        base_score_s_per_mob=10.,out_dir=tmp_path/'cache',axes=['agility','weapon_dps'],
        worker=_complete_linear)
    assert [x['delta'] for x in out['weights']['agility']['probes']]==[20.,40.]
    assert [x['delta'] for x in out['weights']['weapon_dps']['probes']]==[10.,20.]
    assert all(out['weights'][s]['status']=='MEASURED_COARSE_MULTISCALE_PRIOR'
               for s in ('agility','weapon_dps'))
    assert all(out['weights'][s]['weight_s_saved_per_mob_per_unit']>0 for s in ('agility','weapon_dps'))
    # A prior small-step weight must never be recycled as a gear ranking weight.
    old=json.loads(json.dumps(out));old['weights']['agility']={
        'status':'MEASURED_100MOB_OS_ISOLATED',
        'probe_delta':5.,'weight_s_saved_per_mob_per_unit':-0.002}
    alt=iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
        base_score_s_per_mob=10.,out_dir=tmp_path/'other_cache',axes=['weapon_dps'],
        prior_weights=old,worker=_complete_linear)
    assert alt['weights']['agility']['weight_s_saved_per_mob_per_unit'] is None
    assert alt['weights']['agility']['status']=='STALE_SMALL_STEP_REQUIRES_REMEASUREMENT'


def test_legacy_tiny_positive_steps_do_not_pass_multiscale_audit():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    report=json.loads((root/'evidence/wf352/WF352_L30_P3_TOP5.json').read_text())
    curve=json.loads((root/'evidence/wf352/WF352_P3_ADVERSARIAL_CURVES.json').read_text())
    base=report['stat_weights']['base_s_per_mob']
    for stat,small in [('agility',5.),('weapon_dps',2.)]:
        curve['axes'][stat]['probes']=[
            {'delta':small,'s_per_mob':base-small*.01,'status':'COMPLETE'},
            {'delta':small*2,'s_per_mob':base-small*.02,'status':'COMPLETE'}]
    out=audit_stat_weight_curves(report=report,curves=curve)
    assert not out['pass']
    assert all('NO_TWO_ITEM_RELEVANT_COARSE_STEPS' in out['axes'][s]['issues']
               for s in ('agility','weapon_dps'))

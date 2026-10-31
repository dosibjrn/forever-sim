"""First pull begins prepared; later resource states are genuinely carried."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_wf264_decision_cat_sustained import _case, _run
import pytest


def test_first_cat_prepared_energy_and_rage_then_continuity_no_free_reset():
    _,gear,policy,_ = _case()
    kwargs=dict(count=15,recovery_mode='threshold',retain_mode_between_pulls=True,
                recovery_health_fraction=.5,recovery_mana_fraction=.1,travel_time_s=2.2)
    baseline=_run(gear,policy,**kwargs)
    actual=_run(gear,policy,**kwargs,prepared_first_pull_resources={'energy':100.,'rage':0.})
    assert baseline.seconds_per_mob==pytest.approx(16.224919334523893,abs=1e-8)
    assert actual.seconds_per_mob==pytest.approx(16.03474375005995,abs=1e-8)
    assert actual.pulls[0]['kill_s']==pytest.approx(10.)
    assert actual.pulls[0]['prepared_first_pull_resources']=={'energy':100.,'rage':0.}
    assert actual.pulls[1]['prepared_first_pull_resources']=={}
    assert actual.pulls[0]['energy_at_next_pull']==pytest.approx(47.)
    assert actual.pulls[1]['kill_s']>actual.pulls[0]['kill_s']
    assert actual.pulls[1]['energy_at_next_pull']!=pytest.approx(100.)


def test_first_preparation_rejects_unknown_or_out_of_bounds_resource():
    _,gear,policy,_ = _case()
    for preparation in ({'energy':101.},{'rage':-1.},{'fake_energy':100.}):
        with pytest.raises(ValueError,match='invalid prepared first-pull resource'):
            _run(gear,policy,count=2,prepared_first_pull_resources=preparation)

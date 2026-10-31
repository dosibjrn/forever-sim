from src.rulesets.forever.classes.druid.mechanics import _simulate_cat_rotation, _cat_single
from src.rulesets.forever.classes.druid.talents import Talents


def test_cat_energy_never_negative_and_cp_bounded():
    r=_simulate_cat_rotation(
        hp=1200, white_dps=18, energy_regen_per_s=10,
        builder_cost=40, builder_damage=90, cp_per_builder=1.0,
        rake=(24,40,20,40,9.0), use_rake=True, finisher='Rip',
        rip=(20,30,180,12.0), bite=None, t=Talents(), builder_crit_ev=.1,
    )
    assert r['combat_s'] > 0
    assert r['energy_spent'] >= 0
    assert 0 <= r['ending_energy'] <= 100
    assert 0 <= r['ending_cp'] <= 5


def test_cat_finisher_requires_generated_combo_points():
    r=_simulate_cat_rotation(
        hp=2500, white_dps=5, energy_regen_per_s=10,
        builder_cost=40, builder_damage=80, cp_per_builder=1.0,
        rake=None, use_rake=False, finisher='Ferocious Bite',
        rip=None, bite=(32,35,194,210,1.0), t=Talents(), builder_crit_ev=.05,
    )
    casts=r['casts']
    assert 'Ferocious Bite' in casts
    first=casts.index('Ferocious Bite')
    assert casts[:first].count('Claw') >= 5


def test_cat_rotation_candidates_are_first_class_and_can_select_finisher():
    t=Talents(ferocity=5, sharpened_claws=2, blood_frenzy=2)
    r=_cat_single(40,t)
    assert r['profile'] == 'cat'
    assert r['gear'].endswith('druid_feral')
    assert r['cat_resource_model'] == 'finite_target_energy_cp_v1'
    assert r['cat_rotation_candidates'] >= 4
    assert r['feral_finisher'] in {'none','Rip','Ferocious Bite'}
    assert 0 <= r['cat_ending_energy'] <= 100
    assert 0 <= r['cat_ending_combo_points'] <= 5


def test_cat_talent_effect_can_improve_controlled_fixture():
    base=_cat_single(40,Talents())
    talented=_cat_single(40,Talents(ferocity=5, sharpened_claws=2, blood_frenzy=2))
    assert talented['dps'] > base['dps']

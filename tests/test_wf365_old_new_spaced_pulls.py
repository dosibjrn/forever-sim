from __future__ import annotations
import pytest
from src.rulesets.forever.classes.druid import Talents
from src.rulesets.forever.classes.druid.mechanics import _bear_pack
from src.shared.leveling.spaced_pulls import SpacedPullLayout


def test_legacy_bear_pack_charges_20_yard_movement_before_any_grouped_aoe():
    t=Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=1)
    far=_bear_pack(30,t,3,mob_spacing_yards=20)
    stack=_bear_pack(30,t,3,mob_spacing_yards=0)
    assert far['mob_positions_yards']==SpacedPullLayout(3).positions_yards
    assert far['initial_melee_targets']==1
    assert stack['initial_melee_targets']==3
    assert far['mob_spacing_yards']==20
    assert far['spatial_multi_pull_fidelity'].startswith('PROVISIONAL')
    assert far['cycle_s']-stack['cycle_s']==pytest.approx(30/7)


def test_new_geometry_and_old_legacy_agree_on_positions():
    t=Talents(ferocity=5,mangle=1)
    r=_bear_pack(30,t,2)
    layout=SpacedPullLayout(2)
    assert r['mob_positions_yards']==layout.positions_yards
    assert r['initial_melee_targets']==len(layout.initial_melee_targets())==1

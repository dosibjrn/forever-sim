import pytest

from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes.paladin import mechanics as mech


def _gear(level, name):
    return next(g for g in pala.archetypes(level) if g.name == name)


def test_forever_paladin_rank_ladders_extend_through_60():
    assert pala.latest(pala.SEAL_FURY, 60)[:2] == (58, 200)
    assert pala.latest(pala.SEAL_RIGHTEOUSNESS, 60)[:2] == (58, 200)
    assert pala.latest(pala.SEAL_COMMAND, 60)[:2] == (60, 210)
    assert pala.latest(pala.HOLY_LIGHT, 60) == (60, 660, 2.5, 1590, 1770)
    assert pala.latest(pala.FLASH_OF_LIGHT, 60) == (58, 140, 1.5, 348, 389)


def test_forever_sor_judgement_is_pure_50pct_spellpower():
    g=_gear(40, '2h_normal')
    a=mech._base_damage(40, pala.Talents(), g, 'retribution')
    b=mech._base_damage(40, pala.Talents(), g.with_delta('spell_damage', 100), 'retribution')
    # Seal multipliers are unchanged between the two snapshots; isolate raw judgement delta.
    assert b['judgement_dps'] - a['judgement_dps'] == pytest.approx(50.0 / a['judgement_cd'])


def test_forever_fury_is_10pct_per_swing_and_45pct_judgement_without_rank_base_damage():
    g=_gear(40, '1h_shield_normal')
    t=pala.Talents()
    a=mech._base_damage(40, t, g, 'protection')
    b=mech._base_damage(40, t, g.with_delta('spell_damage', 100), 'protection')
    assert b['seal_hit'] - a['seal_hit'] == pytest.approx(10.0)
    assert b['judgement_dps'] - a['judgement_dps'] == pytest.approx(45.0 / a['judgement_cd'])


def test_forever_soc_proc_adds_29pct_spellpower_and_judgement_has_source_base_plus_42_9pct():
    g=_gear(40, '2h_normal')
    t=pala.Talents(seal_of_command=1)
    a=mech._base_damage(40, t, g, 'retribution')
    b=mech._base_damage(40, t, g.with_delta('spell_damage', 100), 'retribution')
    # 7 PPM expected proc model: raw 29 SP damage per proc, then hit expectation.
    # Current Forever SoC Judgement also carries rank base damage; the SP derivative remains 42.9%.
    assert a['judgement_dps'] == pytest.approx((129.0 + g.spell_damage_bonus * .429) / a['judgement_cd'])
    expected_proc_dps=(7.0/60.0)*29.0*a['hit']*(1+a['crit']*.5)
    assert b['seal_dps'] - a['seal_dps'] == pytest.approx(expected_proc_dps)
    assert b['judgement_dps'] - a['judgement_dps'] == pytest.approx(42.9 / a['judgement_cd'])


def test_forever_consecration_spellpower_is_capped_to_first_four_targets():
    g=_gear(40, '1h_shield_normal')
    t=pala.Talents()
    policy=next(p for p in pala.POLICIES if p.name == 'aggressive')
    a=mech._base_damage(40,t,g,'protection')
    gb=g.with_delta('spell_damage',100)
    b=mech._base_damage(40,t,gb,'protection')
    inc=mech._incoming(40,t,g,4,'devotion',a)
    incb=mech._incoming(40,t,gb,4,'devotion',b)
    _,c4,_=mech._aoe_dps(40,t,g,4,'devotion',a,policy,inc)
    _,c4b,_=mech._aoe_dps(40,t,gb,4,'devotion',b,policy,incb)
    inc8=mech._incoming(40,t,g,8,'devotion',a)
    inc8b=mech._incoming(40,t,gb,8,'devotion',b)
    _,c8,_=mech._aoe_dps(40,t,g,8,'devotion',a,policy,inc8)
    _,c8b,_=mech._aoe_dps(40,t,gb,8,'devotion',b,policy,inc8b)
    assert c4b-c4 == pytest.approx(100*.095)
    assert c8b-c8 == pytest.approx(100*.095*.5)


def test_forever_divinity_applies_both_outgoing_and_received_to_self_heal():
    g=_gear(40, '1h_shield_normal')
    t=pala.Talents()
    h=mech._heal_model(40,t,g,0.0)
    rows = pala.HOLY_LIGHT if h['name'] == 'Holy Light' else pala.FLASH_OF_LIGHT
    r=pala.latest(rows,40)
    raw=((r[3]+r[4])/2.0)+g.healing_bonus*h['healing_coeff']
    assert h['heal'] == pytest.approx(raw * 1.05 * 1.05)

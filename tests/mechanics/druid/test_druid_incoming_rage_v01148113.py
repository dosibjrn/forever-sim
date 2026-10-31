import math

from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid.rage import (
    forever_rage_equivalent_damage_per_second,
    incoming_damage_rage_per_second,
)
from src.rulesets.forever.classes.druid.talents import Talents


def test_forever_fixed_armor_rule_uses_half_prearmor_damage():
    assert math.isclose(forever_rage_equivalent_damage_per_second(100.0), 50.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(forever_rage_equivalent_damage_per_second(100.0, successful_hit_fraction=0.8), 40.0, rel_tol=0, abs_tol=1e-12)


def test_incoming_rage_is_independent_of_real_armor_but_not_avoidance(monkeypatch):
    # Direct resource helper has no real-Armor input by design.
    full = incoming_damage_rage_per_second(30, 100.0, successful_hit_fraction=1.0)
    avoided = incoming_damage_rage_per_second(30, 100.0, successful_hit_fraction=0.75)
    assert math.isclose(avoided, full * 0.75, rel_tol=1e-12)

    low_armor = mechanics._bear_pack(30, Talents(), 2)
    original = mechanics._feral_form_armor
    monkeypatch.setattr(mechanics, '_feral_form_armor', lambda level, t, gear, bear: (0.0, original(level,t,gear,bear=bear)[1] * 4.0))
    high_armor = mechanics._bear_pack(30, Talents(), 2)
    assert high_armor['armor_reduction'] > low_armor['armor_reduction']
    assert math.isclose(high_armor['incoming_damage_rage_rate_proxy'], low_armor['incoming_damage_rage_rate_proxy'], rel_tol=1e-10)
    assert high_armor['avg_incoming_dps'] < low_armor['avg_incoming_dps']


def test_bear_publication_exposes_fixed_armor_rule():
    row = mechanics._bear_pack(30, Talents(), 2)
    assert row['incoming_damage_rage_fixed_armor_fraction'] == 0.5
    prov = row['incoming_damage_rage_provenance']
    assert prov['status'] == 'forever_source_backed_fixed_armor_rule'
    assert prov['parameters']['fixed_armor_damage_taken_fraction'] == 0.5
    assert '24301514' in prov['forever_first_party_source']

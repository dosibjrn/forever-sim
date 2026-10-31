from __future__ import annotations

import pytest

from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.items.runtime_selection import available_items
from src.rulesets.forever.shared.item_budget import weapon_peer_exchange_budget_units
from src.v2.stat_weight_model import compute_for_engine


def _spend(names):
    t=pala.Talents()
    for name in names:
        assert pala.legal_add(t,name), name
        t=pala.add_point(t,name)
    return t


def test_weapon_peer_budget_is_a_real_separate_domain_for_1h_and_2h():
    rows=available_items('paladin',60)
    one=weapon_peer_exchange_budget_units(rows,20,weapon_hands=1)
    two=weapon_peer_exchange_budget_units(rows,20,weapon_hands=2)
    assert one['method']=='forever_weapon_peer_item_exchange_v1'
    assert two['method']=='forever_weapon_peer_item_exchange_v1'
    assert one['weapon_hands']==1 and two['weapon_hands']==2
    assert one['units_per_budget']['weapon_dps'] > 0
    assert two['units_per_budget']['weapon_dps'] > 0
    assert one['confidence']['weapon_dps']['peer_samples'] >= 2
    assert two['confidence']['weapon_dps']['peer_samples'] >= 2
    # Different slot envelopes are independently calibrated, not one magic DPS rate.
    assert one['units_per_budget']['weapon_dps'] != pytest.approx(two['units_per_budget']['weapon_dps'])


def test_paladin_stat_weights_keep_weapon_dps_out_of_body_budget_and_publish_weapon_domain():
    t=_spend(['improved_holy_strike']*2+['benediction']*5+['improved_judgement']*2+['deflection']*2)
    row=pala.experimental_level_score(20,t,'auto')
    sw=compute_for_engine(pala,20,t,baseline=row,profile='all')
    assert sw['equal_item_budget']['method']=='forever_peer_item_exchange_v1'
    # The old correctness requirement remains: never fabricate a BODY-slot rate for weapon DPS.
    assert 'empirical_units_per_equal_budget' not in sw['stats']['weapon_dps']
    domain=sw['equal_item_budget_domains']['weapon_slot']
    expected_hands=1 if 'shield' in str(row.get('gear','')) else 2
    assert domain['weapon_hands']==expected_hands
    assert domain['method']=='forever_weapon_peer_item_exchange_v1'
    assert 'weapon_dps' in domain['rank']
    wr=sw['stats']['weapon_dps']['equal_budget_domains']['weapon_slot']
    assert wr['empirical_units_per_equal_budget'] > 0
    assert wr['seconds_saved_per_100_per_equal_budget'] == pytest.approx(
        sw['stats']['weapon_dps']['seconds_saved_per_100_per_point'] * wr['empirical_units_per_equal_budget']
    )


def test_paladin_budget_provider_selects_2h_domain_for_2h_baseline():
    budget=pala.item_budget_units(30,baseline={'gear':'2h_normal','profile':'retribution'},profile='retribution')
    weapon=budget['domains']['weapon_slot']
    assert weapon['weapon_hands']==2
    assert weapon['units_per_budget']['weapon_dps'] > 0
    assert weapon['units_per_budget']['strength'] > 0

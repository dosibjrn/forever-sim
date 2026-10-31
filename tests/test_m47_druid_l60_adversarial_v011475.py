from tools.m47_druid_l60_adversarial import build

def test_m47_druid_l60_bear_survives_bounded_adversarial_and_oracle():
    report = build()
    assert report['gate_a']['cell_closed'] is True
    assert report['independent_oracle']['ok'] is True
    assert report['independent_oracle']['exact_fixture_match'] is True
    assert report['baseline']['profile'] == 'bear'
    assert report['global_bounded_best']['observed_profile'] == 'bear'
    assert report['global_bounded_best']['mobs_per_hour'] <= report['baseline']['mobs_per_hour'] + 1e-9
    assert report['bear_vs_best_balance_margin_pct'] > 10.0

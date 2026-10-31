from src.rulesets.forever.classes.druid import mechanics as m
from src.rulesets.forever.classes.druid.talents import Talents
from src.rulesets.forever.classes.druid.rage import incoming_damage_rage_per_second


def test_incoming_damage_increases_bear_rage_income():
    assert incoming_damage_rage_per_second(30, 100.0) > incoming_damage_rage_per_second(30, 50.0) > 0.0


def test_survival_mitigation_changes_recovery_not_offensive_identity():
    base = m._bear_pack(30, Talents(), 1)
    thick = m._bear_pack(30, Talents(thick_hide=3), 1)
    assert base['profile'] == thick['profile'] == 'bear'
    assert thick['bear_survival_model']['armor'] > base['bear_survival_model']['armor']
    assert thick['bear_survival_model']['avg_incoming_dps'] < base['bear_survival_model']['avg_incoming_dps']
    assert thick['bear_survival_model']['incoming_damage'] < base['bear_survival_model']['incoming_damage']


def test_natural_reaction_improves_survival_pressure_and_returns_rage():
    base = m._bear_pack(40, Talents(), 1)
    nr = m._bear_pack(40, Talents(natural_reaction=5), 1)
    assert nr['bear_survival_model']['total_avoidance'] > base['bear_survival_model']['total_avoidance']
    assert nr['bear_survival_model']['avg_incoming_dps'] < base['bear_survival_model']['avg_incoming_dps']
    assert nr['natural_reaction_rage_rate'] > 0.0


def test_multipull_fails_closed_without_swipe(monkeypatch):
    original = m._latest
    def fake_latest(rows, level):
        if rows is m.wh.SWIPE_RANKS:
            return None
        return original(rows, level)
    monkeypatch.setattr(m, '_latest', fake_latest)
    row = m._bear_pack(30, Talents(), 3)
    assert row['requested_pull_size'] == 3
    assert row['pull_size'] == 1
    assert row['multipull_supported'] is False
    winner = m._bear(30, Talents())
    assert winner['pull_size'] == 1


def test_bear_survival_model_is_explicit_and_separate_from_dps():
    row = m._bear_pack(36, Talents(thick_hide=3), 3)
    s = row['bear_survival_model']
    assert s['authority'] == 'bear_survival_pressure_v1'
    assert s['player_hp'] > 0
    assert s['avg_incoming_dps'] >= 0
    assert s['incoming_rage_per_s'] >= 0
    assert isinstance(s['feasible'], bool)
    assert row['dps'] > 0

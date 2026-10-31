from src.rulesets.forever.classes.druid.mechanics import _balance
from src.rulesets.forever.classes.druid.talents import Talents


def test_balance_does_not_publish_clearcasting_before_level_20():
    r = _balance(14, Talents(improved_wrath=4, genesis=1))
    assert "Clearcasting" not in r["rotation"]
    assert r["clearcasting_available"] is False


def test_balance_publishes_clearcasting_policy_at_level_20_plus():
    r = _balance(20, Talents(improved_wrath=5, genesis=5, moonglow=1))
    assert "Clearcasting" in r["rotation"]
    assert r["clearcasting_available"] is True

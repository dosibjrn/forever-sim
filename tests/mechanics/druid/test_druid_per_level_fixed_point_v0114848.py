from src.rulesets.forever.classes.druid import mechanics as dm
from src.rulesets.forever.classes.druid.talents import Talents


def test_druid_feral_uses_bounded_sql_gear_stat_fixed_point():
    row=dm.experimental_level_score(20,Talents(),"feral")
    fp=row["gear_fixed_point"]
    assert fp["class"] == "druid"
    assert fp["role"] == "druid_feral"
    assert 1 <= fp["iterations"] <= 4
    assert fp["trace"]
    assert all(step["gear_signature"] for step in fp["trace"])
    slots=row["gear_stats"]["slots"]
    assert slots and all(v.get("item_id") is not None for v in slots.values())


def test_druid_stat_probe_stays_on_converged_gear():
    t=Talents()
    row=dm.experimental_level_score(20,t,"feral")
    weights=dm.marginal_stat_weights(20,t,"feral",row)
    assert weights["baseline_s_per_100"] == row["total_s"]
    assert weights["stats"]["weapon_dps"]["seconds_saved_per_100_per_point"] > 0

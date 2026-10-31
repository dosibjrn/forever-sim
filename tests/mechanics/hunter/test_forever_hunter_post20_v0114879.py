from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm


def _hunter():
    game_context.configure("forever", "hunter")
    reset_engine_cache()
    return get_engine()


def test_rapid_fire_unlocks_at_26_and_costs_mana():
    e=_hunter()
    r25=hm._ranged_profile(25,e.Talents(),no_pet=False,pet_family="cat")
    r26=hm._ranged_profile(26,e.Talents(),no_pet=False,pet_family="cat")
    assert not r25["rapid_fire_available"]
    assert r26["rapid_fire_available"]
    assert r26["rapid_fire_effective_cooldown_s"] == 300.0
    assert abs(r26["rapid_fire_uptime_ev"] - 0.05) < 1e-12
    assert r26["rapid_fire_mana_per_s"] > 0


def test_rapid_killing_reduces_rapid_fire_cooldown_rank_by_rank():
    e=_hunter()
    rows=[hm._ranged_profile(40,e.Talents(rapid_killing=r),no_pet=False,pet_family="cat") for r in (0,1,2)]
    assert [r["rapid_fire_effective_cooldown_s"] for r in rows] == [300.0,240.0,180.0]
    assert rows[0]["rapid_fire_uptime_ev"] < rows[1]["rapid_fire_uptime_ev"] < rows[2]["rapid_fire_uptime_ev"]
    assert rows[2]["rapid_killing_bonus_per_mob"] > rows[1]["rapid_killing_bonus_per_mob"] > 0


def test_rapid_fire_is_not_credited_to_instant_shot_cooldowns():
    e=_hunter()
    t=e.Talents(rapid_killing=2)
    r=hm._ranged_profile(40,t,no_pet=False,pet_family="cat")
    assert r["rapid_fire_attack_speed_bonus"] == 0.40
    assert "Rapid Fire" not in r["rotation"] or r["rapid_fire_available"]


def test_verified_cap_stays_l20_after_cooldown_fidelity_increment():
    assert _hunter().VERIFIED_LEVEL_CAP == 20

from src.rulesets.forever.classes.druid import mechanics as m
from src.rulesets.forever.classes.druid.talents import Talents


def test_shared_chain_continues_until_next_pull_would_be_unsafe():
    t=Talents()
    gear={"stamina":20.0,"armor":150.0,"bonus_armor":0.0,"defense":0.0,"spirit":0.0,"mp5":0.0,"healing":0.0}
    row=m._amortize_feral_recovery(20,t,gear,5.0,bear=False)
    assert row["feasible"]
    assert row["pulls_per_recovery"] >= 2
    assert row["continue_without_recovery"] is True
    assert row["recovery_trigger"] == "before_next_pull_would_be_unsafe"
    assert row["recovery_event_s"] >= row["recovery_s"]
    assert abs(row["recovery_event_s"] / row["pulls_per_recovery"] - row["recovery_s"]) < 1e-9


def test_cat_carries_energy_between_mobs_instead_of_resetting_full():
    row=m._cat_single(20,Talents(ferocity=5,feral_swiftness=2))
    assert row["cat_chain_model"] == "stateful_energy_between_mobs_v1"
    assert row["cat_chain_pulls"] >= 2
    assert row["cat_chain_first_start_energy"] == 100.0
    assert row["cat_chain_second_start_energy"] is not None
    assert 0.0 <= row["cat_chain_second_start_energy"] < 100.0


def test_bear_recovery_is_amortized_over_safe_pack_chain():
    row=m._bear_pack(20,Talents(),1)
    assert row["feasible"]
    assert row["pulls_per_recovery"] >= 2
    assert row["continue_without_recovery"] is True
    assert row["recovery_event_s"] >= row["recovery_s_per_pack"]
    assert abs(row["recovery_event_s"] / row["pulls_per_recovery"] - row["recovery_s_per_pack"]) < 1e-9


def test_combo_points_do_not_carry_target_to_target():
    # The chain carries Energy only. Each finite-target simulation starts CP at 0.
    spec=dict(hp=900.0,white_dps=15.0,energy_regen_per_s=10.0,builder_cost=40.0,
              builder_damage=80.0,cp_per_builder=1.0,rake=None,use_rake=False,
              finisher='none',rip=None,bite=None,t=Talents(),builder_crit_ev=0.0)
    chain=m._simulate_cat_chain(pulls=3,travel_s=.7,sim_kwargs=spec)
    assert len(chain["rows"]) == 3
    assert all(0.0 <= r["ending_cp"] <= 5.0 for r in chain["rows"])
    # A reset is observable because each row needs builders again rather than
    # inheriting the prior target's CP state.
    assert all(r["casts"] and r["casts"][0] == "Claw" for r in chain["rows"])


def test_listener_explains_shared_recovery_cycle():
    from src import listener
    html=listener.DECISIONS_HTML
    assert "function recoveryCycleSummary(row)" in html
    assert "pulls_per_recovery" in html
    assert "recovery_event_s" in html
    assert "recovery_trigger" in html
    assert "Cat Energy carries between mobs + travel regen; combo points reset per target" in html
    assert "Recovery cycle" in html

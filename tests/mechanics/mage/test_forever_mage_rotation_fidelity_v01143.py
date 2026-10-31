from __future__ import annotations

from src.rulesets.forever.classes.mage import engine as m


def test_structural_policy_legality_is_talent_gated():
    no_unlock = m.Talents()
    assert all(p.primary != "arcane_blast" for p in m.candidate_policies_for_build(40, no_unlock, focused=True, school="arcane"))
    assert all(not p.use_proc_ice_lance for p in m.candidate_policies_for_build(40, no_unlock, focused=True, school="frost"))
    assert all(p.hot_streak_pyro_stacks == 0 for p in m.candidate_policies_for_build(40, no_unlock, focused=True, school="fire"))

    assert any(p.arcane_blast_to_stacks for p in m.candidate_policies_for_build(40, m.Talents(arcane_blast=1), focused=True, school="arcane"))
    assert any(p.use_proc_ice_lance for p in m.candidate_policies_for_build(40, m.Talents(ice_lance=1), focused=True, school="frost"))
    assert any(p.hot_streak_pyro_stacks for p in m.candidate_policies_for_build(40, m.Talents(pyroblast=1, hot_streak=1), focused=True, school="fire"))


def test_arcane_stack_policy_switches_to_missiles_at_threshold():
    t = m.Talents(arcane_blast=1)
    p = m.Policy("AB2→AM", primary="arcane_blast", arcane_blast_to_stacks=2)
    stats = m.player_stats_for_config(40, t, m.SimConfig())
    mob = m.Mob(41, 1000.0, 7.0, 2.0, 5.0)
    s = m.State(t=0.0, hp=1000.0, mana=stats.max_mana, max_mana=stats.max_mana, distance=30.0,
                arcane_blast_stacks=2, arcane_blast_until=10.0)
    action, rank = m.choose_action(s, 40, t, stats, m.SimConfig(), mob, p, 1000.0)
    assert action == "am"
    assert rank.spell == "arcane_missiles"


def test_hot_streak_policy_reacts_with_pyroblast():
    t = m.Talents(pyroblast=1, hot_streak=1)
    p = m.Policy("HS2→Pyro", primary="fireball", hot_streak_pyro_stacks=2)
    stats = m.player_stats_for_config(40, t, m.SimConfig())
    mob = m.Mob(41, 1000.0, 7.0, 2.0, 5.0)
    s = m.State(t=0.0, hp=1000.0, mana=stats.max_mana, max_mana=stats.max_mana, distance=30.0,
                hot_streak_stacks=2, hot_streak_until=10.0)
    action, rank = m.choose_action(s, 40, t, stats, m.SimConfig(), mob, p, 1000.0)
    assert action == "direct"
    assert rank.spell == "pyroblast"


def test_ice_lance_meta_executes_and_improves_control_in_paired_mc():
    # Under the sustained same-level resource baseline, "uses Ice Lance" and
    # "wins total leveling time" are deliberately separate questions.  This
    # test protects Ice Lance reachability/control value without freezing the
    # old +1/+2, per-mob-full-reset winner assumption.
    t = m.Talents(ice_lance=1, fingers_of_frost=2)
    report = m.policy_ab(40, t, m.SimConfig(), "frost", n=16, seed=7)
    baseline = report["baseline"]
    meta = report["meta"]
    assert meta["casts"].get("ice_lance", 0) > 0
    assert meta["melee_contact_seconds_per_mob"] < baseline["melee_contact_seconds_per_mob"]
    assert meta["pushback_seconds_per_mob"] < baseline["pushback_seconds_per_mob"]


def test_policy_ab_and_policy_search_answer_distinct_questions():
    t = m.Talents(arcane_blast=1)
    cfg = m.SimConfig()
    ab = m.policy_ab(40, t, cfg, "arcane", n=8, seed=11)
    search = m.policy_search(40, t, cfg, "arcane", n=8, seed=11)
    assert ab["question"] == "policy_ab"
    assert search["question"] == "policy_search"
    assert search["best_found"]["policy"].startswith("Arcane")
    assert "meta_regret_seconds_per_mob" in search


def test_structural_frontier_survives_speed_beam_pruning():
    fast = m.PathState(m.Talents(imp_frostbolt=1), 1.0, [])
    frost_progress = m.PathState(m.Talents(imp_frostbolt=1, elemental_precision=1), 2.0, [])
    arcane_progress = m.PathState(m.Talents(arcane_focus=2), 3.0, [])
    fire_progress = m.PathState(m.Talents(imp_fireball=2), 4.0, [])
    kept = m._retain_structural_frontiers([fast, frost_progress, arcane_progress, fire_progress], 1)
    keys = {m.talent_key(x.talents) for x in kept}
    assert m.talent_key(fast.talents) in keys
    assert m.talent_key(arcane_progress.talents) in keys
    assert m.talent_key(fire_progress.talents) in keys


def test_talent_value_reoptimizes_policy_on_both_sides():
    cfg = m.SimConfig()
    report = m.talent_value(
        40,
        m.Talents(),
        m.Talents(ice_lance=1, fingers_of_frost=2),
        cfg,
        school="frost",
        n=12,
        seed=7,
    )
    assert report["question"] == "talent_value"
    assert "ice" not in report["without"]["policy"].lower()
    assert report["with"]["casts"].get("ice_lance", 0) > 0


def test_l20_same_level_resource_baseline_does_not_force_ice_lance_to_win():
    # L20 same-level mobs are short enough that the optimizer can rationally
    # prefer Frostbolt/control even though Ice Lance is a legal end-to-end
    # action.  The old test incorrectly encoded a guide rotation as a required
    # winner under every workload.
    t = m.Talents(imp_frostbolt=5, elemental_precision=5, ice_lance=1)
    same = m.policy_ab(20, t, m.SimConfig(), "frost", n=64, seed=7)
    plus_one = m.policy_ab(20, t, m.SimConfig(target_level_offset=1), "frost", n=64, seed=7)
    assert same["baseline"]["seconds_per_mob"] <= same["meta"]["seconds_per_mob"]
    assert plus_one["meta"]["casts"].get("ice_lance", 0) > 0
    assert "IL" in plus_one["meta"]["rotation"]


def test_published_rotation_tracks_actual_same_level_event_winner_and_il_remains_publishable():
    from src.v2.mature_decision_artifacts import _score_fields
    from src.v2.path_dp import LevelNode

    legacy = m.Policy("legacy", "frostbolt", use_fireblast=False, use_nova=False, use_blink=False)

    # L20 same-level baseline: do not lie to the listener by forcing IL when
    # event adjudication actually prefers Frostbolt/control.
    t20 = m.Talents(imp_frostbolt=5, elemental_precision=5, ice_lance=1)
    row20 = _score_fields(LevelNode(20, t20, 2500.0, legacy, "smooth", {"kill_s": 1500.0, "recovery_s": 1000.0}), m, m.SimConfig())
    assert row20["rotation_adjudication"]["best_found"]["casts"].get("ice_lance", 0) == 0
    assert "IL" not in row20["rotation"]

    # With FoF and a longer L40 fight, the same publication path does select
    # and expose Ice Lance, proving the feature remains end-to-end reachable.
    t40 = m.Talents(ice_lance=1, fingers_of_frost=2)
    row40 = _score_fields(LevelNode(40, t40, 2500.0, legacy, "smooth", {"kill_s": 1500.0, "recovery_s": 1000.0}), m, m.SimConfig())
    assert row40["rotation_adjudication"]["best_found"]["casts"].get("ice_lance", 0) > 0
    assert "IL" in row40["rotation"]


def test_published_arcane_rotation_uses_event_policy_search():
    from src.v2.mature_decision_artifacts import _score_fields
    from src.v2.path_dp import LevelNode
    t = m.Talents(arcane_focus=5, arcane_concentration=5, arcane_blast=1)
    legacy = m.Policy("legacy", "arcane_missiles", use_fireblast=False, use_nova=False, use_blink=False)
    node = LevelNode(30, t, 2500.0, legacy, "smooth", {"kill_s": 1500.0, "recovery_s": 1000.0})
    row = _score_fields(node, m, m.SimConfig())
    assert row["rotation_adjudication"]["school"] == "arcane"
    assert row["rotation_adjudication"]["best_found"]["policy"].startswith("Arcane")
    assert "AB" in row["rotation"] or "AM" in row["rotation"]


def test_published_fire_hot_streak_rotation_uses_event_policy_search():
    from src.v2.mature_decision_artifacts import _score_fields
    from src.v2.path_dp import LevelNode
    t = m.Talents(imp_fireball=5, ignite=5, pyroblast=1, hot_streak=1)
    legacy = m.Policy("legacy", "fireball", use_fireblast=False, use_nova=False, use_blink=False)
    node = LevelNode(40, t, 2500.0, legacy, "smooth", {"kill_s": 1500.0, "recovery_s": 1000.0})
    row = _score_fields(node, m, m.SimConfig())
    assert row["rotation_adjudication"]["school"] == "fire"
    assert row["rotation_adjudication"]["best_found"]["policy"].startswith("Fire")
    assert "FBa" in row["rotation"] or "Pyro" in row["rotation"]

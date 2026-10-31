from dataclasses import replace

from src import game_context
from src.rulesets.forever.classes.mage import engine as mage
from src.v2 import expected_engine
from tools.report_backend_reconciliation import _mage_structural_build


def _fire(level=40):
    game_context.configure("forever", "mage")
    t = _mage_structural_build(level, "fire")
    assert t.pyroblast
    return t


def test_i13_fire_expected_state_reports_hot_streak_and_single_target_scope():
    t = _fire(40)
    assert t.hot_streak
    cfg = mage.SimConfig(seed=7, use_best_water=True)
    p = next(x for x in mage.candidate_policies_for_build(40,t,focused=True,school="fire") if x.hot_streak_pyro_stacks > 0)
    row = expected_engine.score_policy(40,t,p,cfg,cycle_pulls=3)
    meta = row["fire_state_model"]
    assert meta["id"] == "fire_hot_streak_expected_state_v1"
    assert meta["hot_streak_modeled"] is True
    assert meta["hot_streak_stack_cap"] == 3
    assert meta["aoe_assumptions"] == "none_single_target_only"


def test_i13_hot_streak_can_reactively_cast_pyro_in_structural_scorer():
    t = _fire(40)
    cfg = mage.SimConfig(seed=7, use_best_water=True)
    candidates = [x for x in mage.candidate_policies_for_build(40,t,focused=True,school="fire") if x.hot_streak_pyro_stacks > 0]
    assert candidates
    # Threshold 1 is a controlled structural fixture: expected crit occupancy
    # must eventually trigger a reactive Pyro rather than leaving HS cosmetic.
    p = replace(candidates[0], hot_streak_pyro_stacks=1)
    row = expected_engine.score_policy(40,t,p,cfg,cycle_pulls=5)
    assert row.get("casts_pyroblast", 0.0) > 0.0


def test_i13_hot_streak_legality_requires_pyro_and_talent():
    t = _fire(40)
    cfg = mage.SimConfig(seed=7, use_best_water=True)
    p = next(x for x in mage.candidate_policies_for_build(40,t,focused=True,school="fire") if x.hot_streak_pyro_stacks > 0)
    no_hs = expected_engine.score_policy(40,replace(t,hot_streak=0),replace(p,hot_streak_pyro_stacks=0),cfg,cycle_pulls=2)
    assert no_hs["fire_state_model"]["hot_streak_modeled"] is False


def test_i13_fire_candidate_can_win_controlled_fixture():
    t = _fire(40)
    cfg = mage.SimConfig(seed=7, use_best_water=True)
    rows=[]
    for p in mage.candidate_policies_for_build(40,t,focused=True,school="fire"):
        rows.append((expected_engine.score_policy(40,t,p,cfg,cycle_pulls=3)["total_s"],p))
    winner=min(rows,key=lambda x:x[0])[1]
    assert mage.policy_primary_school(winner) == "fire"

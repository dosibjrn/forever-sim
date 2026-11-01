from __future__ import annotations

import random
import pytest

from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage import analytic as mage_analytic
from src.v2 import expected_engine as expected
from src import game_context
from src.engine_registry import reset_engine_cache


def _state():
    return mage.State(t=0.0,hp=10000.0,mana=10000.0,max_mana=10000.0,distance=35.0)


def test_fireball_attached_periodic_ticks_can_crit_without_creating_proc_semantics(monkeypatch):
    rank=mage.FIREBALL[2]
    state=_state()
    stats=mage.Stats(0.0,0.0,10000.0,10000.0,0.99,0.0)
    mob=mage.Mob(level=12,hp=10000.0,run_speed=0.0)
    monkeypatch.setattr(mage,'resistance_damage_multiplier',lambda *a,**k:1.0)
    mage.resolve_direct_impact(state,rank,True,False,0.0,12,mage.Talents(),stats,mage.SimConfig(),mob,random.Random(1))
    dot=next(d for d in state.dots if d.kind=='fireball')
    assert dot.crit_chance == pytest.approx(.99)
    hp0=state.hp
    mage.advance_events(state,rank.dot_interval,12,mage.Talents(),stats,mage.SimConfig(),mob,random.Random(1),mage.FightMetrics())
    expected_tick=(rank.dot_total/(rank.dot_duration/rank.dot_interval))*1.5
    assert hp0-state.hp == pytest.approx(expected_tick)


def test_pyroblast_periodic_crit_keeps_audited_dot_spell_power_coefficient(monkeypatch):
    rank=mage.PYROBLAST[0]
    state=_state()
    stats=mage.Stats(0.0,0.0,10000.0,10000.0,0.99,100.0)
    mob=mage.Mob(level=20,hp=10000.0,run_speed=0.0)
    monkeypatch.setattr(mage,'resistance_damage_multiplier',lambda *a,**k:1.0)
    mage.resolve_direct_impact(state,rank,True,False,0.0,20,mage.Talents(),stats,mage.SimConfig(),mob,random.Random(1))
    dot=next(d for d in state.dots if d.kind=='pyroblast')
    assert dot.damage*dot.remaining_ticks == pytest.approx(rank.dot_total+60.0)
    assert dot.crit_chance == pytest.approx(.99)


def test_analytic_fireball_periodic_damage_values_base_spell_crit():
    rank=mage.FIREBALL[2]
    cfg=mage.SimConfig()
    t=mage.Talents()
    no_crit=mage.Stats(0.0,0.0,1000.0,1000.0,0.0,0.0)
    high_crit=mage.Stats(0.0,0.0,1000.0,1000.0,0.50,0.0)
    d0,_,_=mage_analytic._analytic_gradient_spell_terms(12,t,no_crit,cfg,rank)
    d1,_,_=mage_analytic._analytic_gradient_spell_terms(12,t,high_crit,cfg,rank)
    # Both direct and attached periodic Fireball damage gain expected crit value.
    assert d1 > d0


def test_expected_engine_periodic_dot_includes_expected_crit_multiplier(monkeypatch):
    prior=game_context.current()
    try:
        game_context.configure('forever','mage'); reset_engine_cache()
        rank=mage.FIREBALL[2]
        t=mage.Talents()
        cfg=mage.SimConfig()
        mob=mage.Mob(level=12,hp=10000.0,run_speed=0.0)
        monkeypatch.setattr(mage,'resistance_damage_multiplier',lambda *a,**k:1.0)
        comp={'damage':0.0,'hit':1.0,'expected_crit_damage':0.0}
        def dot_per_tick(crit):
            st=expected.ExpectedState(t=0.0,hp=10000.0,mana=1000.0,max_mana=1000.0,distance=35.0)
            stats=mage.Stats(0.0,0.0,1000.0,1000.0,crit,0.0)
            expected._apply_expected_direct_impact(st,rank,comp,12,t,stats,cfg,mob,{})
            return next(d for d in st.dots if d.kind=='fireball').damage
        base=dot_per_tick(0.0)
        half=dot_per_tick(0.5)
        assert half == pytest.approx(base*1.25)
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()

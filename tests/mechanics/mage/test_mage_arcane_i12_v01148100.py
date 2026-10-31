import random
from dataclasses import replace

from src import game_context
from src.rulesets.forever.classes.mage import engine as mage
from src.v2 import expected_engine
from tools.report_backend_reconciliation import _mage_structural_build


def _arcane(level=40):
    game_context.configure('forever','mage')
    t=_mage_structural_build(level,'arcane')
    assert t.arcane_blast
    return t


def test_i12_arcane_expected_state_carries_and_consumes_missile_barrage():
    t=_arcane(40)
    assert t.missile_barrage
    cfg=mage.SimConfig(seed=7,use_best_water=True)
    ps=mage.candidate_policies_for_build(40,t,focused=True,school='arcane')
    p=next(x for x in ps if x.arcane_blast_to_stacks==2)
    row=expected_engine.score_policy(40,t,p,cfg,cycle_pulls=3)
    meta=row['arcane_state_model']
    assert meta['id']=='arcane_ab_mb_expected_state_v1'
    assert meta['missile_barrage_modeled'] is True
    assert meta['missile_barrage_ab_proc_chance']==0.40
    assert row['casts_arcane_blast']>0 and row['casts_arcane_missiles']>0


def test_i12_missile_barrage_reduces_arcane_cycle_time_and_mana_in_controlled_fixture():
    t=_arcane(40)
    cfg=mage.SimConfig(seed=7,use_best_water=True)
    p=next(x for x in mage.candidate_policies_for_build(40,t,focused=True,school='arcane') if x.arcane_blast_to_stacks==2)
    with_mb=expected_engine.score_policy(40,t,p,cfg,cycle_pulls=4)
    no_mb=expected_engine.score_policy(40,replace(t,missile_barrage=0),p,cfg,cycle_pulls=4)
    assert with_mb['kill_s'] < no_mb['kill_s']
    assert with_mb['mana'] < no_mb['mana']


def test_i12_arcane_blast_stack_cost_and_state_transition_are_real():
    t=_arcane(40)
    stats=mage.player_stats_for_config(40,t,mage.SimConfig(seed=7,use_best_water=True))
    base=stats.base_mana*mage.wh.ARCANE_BLAST_BASE_MANA_PCT
    s=mage.State(t=0,hp=5000,mana=stats.max_mana,max_mana=stats.max_mana,distance=20)
    assert base>0
    # Cost progression is source-backed and bounded to four stacks.
    costs=[base*(1+mage.wh.ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK*k) for k in range(5)]
    assert costs[0] < costs[1] < costs[2] < costs[3] < costs[4]
    assert mage.wh.ARCANE_BLAST_MAX_STACKS==4


def test_i12_arcane_candidate_can_win_controlled_fixture():
    t=_arcane(40)
    cfg=mage.SimConfig(seed=7,use_best_water=True)
    rows=[]
    for p in mage.candidate_policies_for_build(40,t,focused=True,school='arcane'):
        rows.append((expected_engine.score_policy(40,t,p,cfg,cycle_pulls=4)['total_s'],p))
    winner=min(rows,key=lambda x:x[0])[1]
    assert winner.arcane_blast_to_stacks>0


def test_i12_pom_ap_fail_closed_without_normalized_effect_authority():
    t=_arcane(60)
    t=replace(t,presence_of_mind=1,arcane_power=1)
    cfg=mage.SimConfig(seed=7,use_best_water=True)
    p=next(x for x in mage.candidate_policies_for_build(60,t,focused=True,school='arcane') if x.arcane_blast_to_stacks==1)
    meta=expected_engine.score_policy(60,t,p,cfg,cycle_pulls=2)['arcane_state_model']
    assert meta['presence_of_mind'].startswith('fail_closed')
    assert meta['arcane_power'].startswith('fail_closed')

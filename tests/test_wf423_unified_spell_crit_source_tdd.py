"""WF423: source-pinned unified critical chance through canonical GameIR and 100 mobs.

Blizzard Forever Deep Dive says spell/melee/ranged critical chance is combined.
Crit item display 14 raw = 1% remains independently pinned by item facts.
"""
import sqlite3
from dataclasses import replace

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p3_ratings import (
    source_item_stat_to_combat, apply_source_item_stat_delta,
)
from src.game.model import ActorDefinition, ResourceDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity
from tools.wf420_druid20_independent_full_replay import rebuild_result_winner


BLIZZARD_SOURCE = 'https://news.blizzard.com/en-us/article/24303313/world-of-warcraft-forever-deep-dive-panel-recap'


def test_canonical_sqlite_attests_unified_spell_melee_ranged_crit():
    with sqlite3.connect(DEFAULT_DB) as db:
        row = db.execute('SELECT scope,source_url FROM unified_combat_chance_scope_facts '
                         "WHERE stat_key='crit'").fetchone()
    assert row == ('spell_melee_ranged', BLIZZARD_SOURCE)


def test_14_raw_crit_item_adds_same_one_percent_to_melee_and_spell():
    result = source_item_stat_to_combat('crit', 14, level=20)
    assert result['channel_deltas']['melee_crit_chance'] == pytest.approx(.01)
    assert result['channel_deltas']['spell_crit_chance'] == pytest.approx(.01)
    assert 'spell_crit_scope_in_executor' not in result['unmodeled_channels']
    assert BLIZZARD_SOURCE in result['source_urls']


def _cast_damage(*, school='nature', spell_crit=0.2, explicit=None, multiplier=2.):
    actor = ActorState.from_ir(
        ActorDefinition('player','player',base_stats={
            'spell_crit_chance': spell_crit, 'melee_crit_chance':0., 'other_crit':.05,
        },metadata={'level':20}),
        (ResourceDefinition('health','Health','player',initial_amount=500,capacity=500),), ())
    target=TargetState.with_health('target',500)
    rt=CombatRuntime(actor=actor,target=target)
    action=ActionDefinition('direct:fixture','direct','Direct','player',requirements=(),costs=(),
        cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,effects=(DamageEffect('damage',school,'enemy',100,100,
        crit_chance_stat_id=explicit,crit_multiplier=multiplier),),provenance=())
    rt.schedule_action(action)
    return 500-target.health


def test_direct_magic_uses_unified_spell_crit_but_physical_and_explicit_override_do_not():
    assert _cast_damage(school='nature') == pytest.approx(120.)
    assert _cast_damage(school='physical') == pytest.approx(100.)
    assert _cast_damage(school='nature',explicit='other_crit') == pytest.approx(105.)
    assert _cast_damage(school='nature',multiplier=1.) == pytest.approx(100.)


def test_source_druid_wrath_100mob_crit_weight_is_real_and_positive():
    _,candidate,recovery=rebuild_result_winner()
    wrath=next(a for a in candidate.ir.actions if a.id=='wrath:5178')
    assert any(isinstance(e,DamageEffect) and e.school=='nature' and e.crit_multiplier>1
               for e in wrath.effects)
    result=reoptimized_stat_sensitivity(candidate=candidate,stat='crit',delta=14.,level=20,
        recovery_policies=(recovery,),pack_sizes=(1,),mobs=100,max_wall_s_per_eval=18.)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['source_item_chance_mapping']['channel_deltas']['spell_crit_chance']==pytest.approx(.01)
    assert result['weight_s_saved_per_mob_per_unit']>0.
    assert all(r['status']=='COMPLETE' and r['mob_completed']==100 for r in result['rows'])
    assert sum(r['events'] for r in result['rows'])>1000

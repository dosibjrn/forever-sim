"""WF424: unified Forever hit chance, pinned source and paid 100-mob proof.

Existing 0.96 spell hit in the target profile is a Classic proxy, not
an assertion that Forever has that baseline. The source-backed claim here
is only the unified scope of the Hit item stat.
"""
import sqlite3

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p3_ratings import (
    source_item_stat_to_combat, apply_source_item_stat_delta,
)
from src.game.data.forever.target_combat_source import load_target_combat_profile
from src.game.model import ActorDefinition, ResourceDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity
from tools.wf420_druid20_independent_full_replay import rebuild_result_winner

BLIZZARD_SOURCE = 'https://news.blizzard.com/en-us/article/24303313/world-of-warcraft-forever-deep-dive-panel-recap'


def test_canonical_sqlite_pins_unified_hit_scope_without_claiming_forever_miss_baseline():
    with sqlite3.connect(DEFAULT_DB) as db:
        row = db.execute('SELECT scope,source_url FROM unified_combat_chance_scope_facts '
                         "WHERE stat_key='hit'").fetchone()
    assert row == ('spell_melee_ranged', BLIZZARD_SOURCE)
    profile = load_target_combat_profile(20)
    assert profile['spell_hit'] == pytest.approx(.96)
    assert profile['source_status'] == 'classic_proxy_not_forever_server_verified'


def test_10_raw_hit_item_adds_one_percent_to_both_melee_and_spell():
    result = source_item_stat_to_combat('hit', 10, level=20)
    assert result['channel_deltas']['melee_hit_bonus'] == pytest.approx(.01)
    assert result['channel_deltas']['spell_hit_bonus'] == pytest.approx(.01)
    assert BLIZZARD_SOURCE in result['source_urls']
    assert result['unmodeled_channels'] == ()


def test_source_hit_affects_direct_magic_in_existing_combat_runtime():
    def one_cast(raw_hit):
        base=ActorDefinition('player','player',base_stats={},metadata={'level':20})
        from dataclasses import dataclass, replace
        # Same IR-shaped actor transformation used by the real gear adapter.
        @dataclass(frozen=True)
        class IR:
            actor: object
            provenance: dict
        changed=apply_source_item_stat_delta(IR(base,{}),'hit',raw_hit,level=20)
        actor=ActorState.from_ir(changed.actor,
            (ResourceDefinition('health','Health','player',initial_amount=500,capacity=500),),())
        target=TargetState.with_health('target',500)
        target.metadata.update({'combat_capture_id':'wf247_outgoing_defense_20261011',
                                'spell_hit':.96,'melee_hit':.95,'armor':0.,
                                'armor_constant':2100.,'armor_reduction_cap':.75})
        rt=CombatRuntime(actor=actor,target=target)
        action=ActionDefinition('source:fixture','fixture','Fixture','player',requirements=(),costs=(),
            cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,
            effects=(DamageEffect('damage','nature','enemy',100,100,crit_multiplier=1.),),
            provenance=())
        rt.schedule_action(action)
        return 500-target.health
    assert one_cast(0) == pytest.approx(96.)
    assert one_cast(10) == pytest.approx(97.)
    assert one_cast(40) == pytest.approx(100.)


def test_druid20_100mob_source_hit_probe_executes_both_sides_without_fabricated_weight():
    _,candidate,recovery=rebuild_result_winner()
    result=reoptimized_stat_sensitivity(candidate=candidate,stat='hit',delta=40.,level=20,
        recovery_policies=(recovery,),pack_sizes=(1,),mobs=100,max_wall_s_per_eval=18.)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['source_item_chance_mapping']['channel_deltas']['spell_hit_bonus']==pytest.approx(.04)
    assert all(r['status']=='COMPLETE' and r['mob_completed']==100 for r in result['rows'])
    assert sum(r['events'] for r in result['rows'])>1000
    assert result['best']['after']['mean_s_per_mob'] <= result['best']['before']['mean_s_per_mob']


def test_defense_and_dodge_remain_independent_of_unified_hit_and_crit():
    defense=source_item_stat_to_combat('defense',4,level=20)
    dodge=source_item_stat_to_combat('dodge',12,level=20)
    assert defense['channel_deltas']=={'incoming_miss_chance_bonus':.0016,'dodge_chance':.0016}
    assert dodge['channel_deltas']=={'dodge_chance':pytest.approx(.01)}
    assert 'spell_hit_bonus' not in defense['channel_deltas']
    assert 'spell_crit_chance' not in dodge['channel_deltas']


def test_source_druid_faerie_fire_debuff_uses_equipped_unified_spell_hit():
    """Existing expected-value debuff semantics must see the item spell channel."""
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.target_combat_source import target_combat_metadata

    def paid_cast(raw_hit):
        ir=build_game_ir_slice(class_key='druid',level=20)
        if raw_hit:
            ir=apply_source_item_stat_delta(ir,'hit',raw_hit,level=20)
        action=next(a for a in ir.actions if a.family_key=='faerie_fire')
        actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        target=TargetState.with_health('source-target',100000.,**target_combat_metadata(ir))
        runtime=CombatRuntime(actor=actor,target=target)
        runtime.schedule_action(action)
        runtime.run_until_idle()
        applied=[e for e in runtime.result().events if e.kind=='TargetStatDebuffApplied']
        assert len(applied)==1
        assert applied[0].payload['applied'] is True
        assert sum(e.kind=='ActionStarted' for e in runtime.result().events)==1
        assert any(e.kind=='TargetStatDebuffExpired' for e in runtime.result().events)
        return applied[0].payload,action

    base,action=paid_cast(0)
    boosted,_=paid_cast(10)
    assert base['expected_hit_chance']==pytest.approx(.96)
    assert boosted['expected_hit_chance']==pytest.approx(.97)
    assert boosted['effective_delta']/base['effective_delta']==pytest.approx(.97/.96)
    assert boosted['effective_delta']==pytest.approx(action.effects[0].delta*.97)

"""WF429 source-typed cast pushback: causal RED→GREEN, no fake Forever coefficient."""
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model import ActorDefinition, ResourceDefinition, IncomingAttackDefinition, ActionDefinition, DamageEffect
from src.game.runtime import ActorState, TargetState, CombatRuntime

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'


def test_five_source_rank_fractions_apply_only_arcane_nature_casts():
    ir,cov=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))
    assert cov['rank_missing_executor']==sum(
        not rank.modifiers for talent in ir.talents for rank in talent.ranks)
    assert cov['rank_missing_executor']>0
    t=next(t for t in ir.talents if t.id=='natures_focus')
    assert [r.modifiers[0].value for r in t.ranks]==pytest.approx([.14,.28,.42,.56,.70])
    allocation={'natures_focus':5}
    selected,_=apply_talent_selection(ir,allocation,level=30,bonus_talent_points=5)
    for fam in ('wrath','starfire'):
        action=next(a for a in selected.actions if a.family_key==fam)
        assert action.metadata['cast_pushback_avoidance_chance']==pytest.approx(.70)
    for fam in ('claw','rake'):
        action=next(a for a in selected.actions if a.family_key==fam)
        assert 'cast_pushback_avoidance_chance' not in action.metadata


def _run(*, avoidance=0, pushback_s=0.5, attack_time=1., school='nature', attack_raw=10., cast_time=2., hit_chance=1., source_url='https://warcraft.wiki.gg/wiki/Pushback'):
    actor=ActorState.from_ir(ActorDefinition('hero','player',base_stats={}),
        (ResourceDefinition('health','Health','hero',initial_amount=300,capacity=300),),())
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('mob',1000))
    action=ActionDefinition('cast','cast','cast','hero',requirements=(),costs=(),cast_time_s=cast_time,
        gcd_s=1.5,cooldown_s=0.,effects=(DamageEffect('damage',school,'enemy',50.,50.),),
        metadata={'cast_pushback_avoidance_chance':avoidance} if avoidance else {},
        provenance=({'fixture':'wf429'},))
    attack=IncomingAttackDefinition('melee','Melee','mob','hero','physical',attack_raw,hit_chance,'health',
        metadata={'representative_swing_s':2., 'cast_pushback_on_hit_s':pushback_s,
                  'cast_pushback_source_url':source_url},
        provenance=({'source':'Classic proxy pushback baseline'},))
    rt.enqueue_action(action)
    rt.advance_to(attack_time)
    rt.resolve_incoming_attack(attack,at_time_s=attack_time)
    rt.run_until_idle()
    ends=[e.time_s for e in rt.result().events if e.kind=='ActionCompleted']
    pushbacks=[e for e in rt.result().events if e.kind=='CastPushbackApplied']
    return rt,ends,pushbacks


def test_real_incoming_hit_delays_cast_and_source_resistance_reduces_delay():
    raw,raw_ends,raw_events=_run(avoidance=0)
    guarded,guard_ends,guard_events=_run(avoidance=.7)
    assert raw_ends==pytest.approx([2.5])
    assert guard_ends==pytest.approx([2.15])
    assert raw_events[0].payload['delay_s']==pytest.approx(.5)
    assert guard_events[0].payload['delay_s']==pytest.approx(.15)
    assert sum(x.kind=='Damage' and x.action_id=='cast' for x in guarded.result().events)==1


def test_without_source_pushback_coefficient_no_change_and_no_fictional_delays():
    rt,ends,events=_run(avoidance=.7,pushback_s=0.)
    assert ends==pytest.approx([2.])
    assert events==[]


def test_cast_pushback_requires_positive_damage_and_active_cast():
    _,ends,events=_run(avoidance=.7,attack_raw=0.)
    assert ends==pytest.approx([2.]);assert not events
    _,ends,events=_run(avoidance=.7,attack_time=3.)
    assert ends==pytest.approx([2.]);assert not events


def test_expected_incoming_hit_probability_scales_pushback_without_faking_full_hit():
    _,ends,events=_run(avoidance=0,hit_chance=.5)
    assert ends==pytest.approx([2.25])
    assert events[0].payload['delay_s']==pytest.approx(.25)


def test_unsourced_pushback_rejected_before_consuming_health():
    with pytest.raises(ValueError,match='CAST_PUSHBACK_REQUIRES_SOURCE_PROVENANCE'):
        _run(source_url='')

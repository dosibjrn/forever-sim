"""RED: source-pinned compound melee crit + healing and form-gated party crit."""
from dataclasses import replace
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.model.ir import DamageEffect, WeaponDamageEffect

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILLER={'ferocity':5,'heart_of_the_wild':5,'feral_swiftness':2,
        'feral_instinct':3,'thick_hide':3,'shredding_attacks':3,
        'savage_fury':2,'sharpened_claws':1}
NATURAL={**FILLER,'natural_instinct':2}
LEADER={**FILLER,'sharpened_claws':2,'leader_of_the_pack':1}
assert sum(NATURAL.values())==26 and sum(LEADER.values())==26


def _root():
    return build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)


def _compiled():
    return compile_talent_runtime(_root())[0]


def _selected(selection):
    return apply_talent_selection(_compiled(),selection,level=30,bonus_talent_points=5)[0]


def _action(ir,family):
    return next(a for a in ir.actions if a.family_key==family)


def test_source_compound_melee_crit_and_intellect_healing_both_ranks_atomic():
    ir=_compiled()
    natural=next(t for t in ir.talents if t.id=='natural_instinct')
    assert [len(r.modifiers) for r in natural.ranks]==[2,2]
    for rank in natural.ranks:
        assert {m.kind for m in rank.modifiers}=={'critical_damage_bonus_pct','healing_power_from_stat'}
        assert all(m.provenance['source_build']=='1.60.1.70338' for m in rank.modifiers)
        assert next(m.value for m in rank.modifiers if m.kind=='critical_damage_bonus_pct')==pytest.approx((.1,.2)[rank.rank-1])
        assert next(m.value for m in rank.modifiers if m.kind=='healing_power_from_stat')==pytest.approx((.12,.25)[rank.rank-1])


def test_source_mode_party_crit_compiles_and_only_acts_in_legal_forms():
    ir=_compiled()
    leader=next(t for t in ir.talents if t.id=='leader_of_the_pack')
    assert len(leader.ranks)==1 and leader.ranks[0].modifiers
    selected=_selected(LEADER)
    actor=ActorState.from_ir(selected.actor,selected.resources,selected.modes)
    base_ir=_selected({**FILLER,'sharpened_claws':2})
    baseline=ActorState.from_ir(base_ir.actor,base_ir.resources,base_ir.modes)
    for mode in ('cat','bear','caster'):
        actor.transition_mode(mode)
        baseline.transition_mode(mode)
        expected=.03 if mode in ('cat','bear') else 0.
        assert actor.stats.get('melee_crit_chance',0.)==pytest.approx(
            baseline.stats.get('melee_crit_chance',0.)+expected)
        assert actor.stats.get('spell_crit_chance',0.)==pytest.approx(
            baseline.stats.get('spell_crit_chance',0.)+expected)


def test_natural_instinct_changes_nonperiodic_melee_crit_only_and_applies_26pt():
    original=_compiled()
    selected=_selected(NATURAL)
    claw0=_action(original,'claw')
    claw1=_action(selected,'claw')
    assert next(e for e in claw1.effects if isinstance(e,WeaponDamageEffect)).crit_multiplier==pytest.approx(
        next(e for e in claw0.effects if isinstance(e,WeaponDamageEffect)).crit_multiplier+0.2)
    wrath0=_action(original,'wrath');wrath1=_action(selected,'wrath')
    assert wrath0.effects==wrath1.effects
    assert selected.actor.metadata['source_healing_power_from_stats']['intellect']==pytest.approx(.25)


def test_natural_instinct_healing_uses_equipped_intellect_at_runtime_not_pregear_snapshot():
    selected=_selected(NATURAL)
    healer=_action(selected,'healing_touch')
    def healed(intellect):
        actor_ir=replace(selected.actor,base_stats={**selected.actor.base_stats,'intellect':intellect})
        actor=ActorState.from_ir(actor_ir,selected.resources,selected.modes)
        actor.resource_capacity['mana']=100000.;actor.resources['mana']=100000.
        actor.resources['health']=max(1.,actor.resources['health']-1000.)
        rt=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',10000.),spell_power=0.)
        end=rt.schedule_action(healer);rt.advance_to(end)
        return sum(float(e.payload.get('amount',0.)) for e in rt.trace if e.kind=='Heal')
    assert healed(100.)-healed(80.)==pytest.approx(5.,abs=1e-7)


def test_source_compound_rejects_partial_second_clause_fail_closed():
    original=_root()
    changed=[]
    for talent in original.talents:
        if talent.id!='natural_instinct':
            changed.append(talent);continue
        ranks=[]
        for rank in talent.ranks:
            capture=dict(rank.provenance['checkpoint_source_l0'])
            capture['additional_target']='not_healing_spells'
            ranks.append(replace(rank,provenance={**rank.provenance,'checkpoint_source_l0':capture}))
        changed.append(replace(talent,ranks=tuple(ranks)))
    promoted,_=promote_atomic_source_talent_effects(replace(original,talents=tuple(changed)))
    natural=next(t for t in promoted.talents if t.id=='natural_instinct')
    assert all(not r.modifiers for r in natural.ranks)


def test_real_paid_100mob_cat_policy_runs_with_source_melee_crit_bonus():
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    ir=_selected(NATURAL)
    claw=_action(ir,'claw')
    enter=_action(ir,'cat_form')
    exit_action=next(a for a in ir.actions if a.family_key=='cancel_mode' and a.id.endswith(':cat'))
    policy=PolicyDefinition('source_feral_crit','source cat claw',rules=(PolicyRuleDefinition('claw',claw.id),))
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,target_health=180.,count=100,
        schedule_incoming_attacks=True,pre_combat_action_ids=(enter.id,),post_combat_action_ids=(exit_action.id,),
        recovery_mode='always',max_actions=128)
    assert len(result.pulls)==100
    assert all(p['pack_all_defeated'] for p in result.pulls)
    assert sum(p['combat_runtime_events'] for p in result.pulls)>1000
    assert result.seconds_per_mob>0


def test_stateful_source_mechanics_not_displaced_by_passive_rank_frontier():
    """P4: source charge talent must survive both tight and standard frontiers."""
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    ir=_compiled()
    stateful={t.id for t in ir.talents if any(
        m.kind=='cast_charge_exchange' for r in t.ranks for m in r.modifiers)}
    assert stateful
    for size in (16,32,64):
        allocations,_=bounded_full_point_talent_frontier(ir,level=30,
            bonus_talent_points=5,max_frontier=size)
        for tid in stateful:
            talent=next(t for t in ir.talents if t.id==tid)
            assert any(a.get(tid)==talent.max_rank for a in allocations),(size,tid)


def test_party_aura_partial_semantics_explicitly_blocks_p2_certification():
    from tests.test_wf430_p2_whole_gate_26point_tdd import audit
    report=audit()
    leader=next(row for row in report['structural_witnesses']
                if row['talent_id']=='leader_of_the_pack' and row['rank']==1)
    assert leader['status']=='SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS'
    assert 'SOURCE_PARTY_AURA_NOT_EXECUTED' in leader['partial_semantics']
    assert report['partial_runtime_semantics_count']>=1
    assert 'SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS' in report['remaining_gate_fail_reasons']
    assert not report['green']

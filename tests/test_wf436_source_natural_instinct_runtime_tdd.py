"""Druid L30 source-defined two-clause talent: melee crit bonus + live Int healing."""
from dataclasses import replace
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import CombatRuntime,ActorState,TargetState
from src.game.model.ir import (WeaponDamageEffect,PeriodicEffect,DamageEffect,HealEffect,PeriodicHealEffect)
from src.game.runtime.simulator import expected_weapon_damage

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILL={'ferocity':5,'heart_of_the_wild':5,'feral_swiftness':2,
    'feral_instinct':3,'thick_hide':3,'sharpened_claws':2}


def source_ir():
    return build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)


def compiled():
    return compile_talent_runtime(source_ir())[0]


def selected(rank):
    return apply_talent_selection(compiled(),{**FILL,'natural_instinct':rank},
        level=30,bonus_talent_points=5)[0]


def family(ir,key):
    return next(a for a in ir.actions if a.family_key==key)


def test_atomic_source_rank_fractions_and_provenance():
    t=next(t for t in compiled().talents if t.id=='natural_instinct')
    assert [len(r.modifiers) for r in t.ranks]==[2,2]
    for rank,crit,healing in ((1,.1,.12),(2,.2,.25)):
        m=t.ranks[rank-1].modifiers
        assert [x.kind for x in m]==['critical_damage_bonus_pct','healing_power_from_stat']
        assert [x.value for x in m]==pytest.approx((crit,healing))
        assert all(x.provenance['source_build']=='1.60.1.70338' for x in m)


def test_source_rank2_affects_weapon_and_melee_auto_not_spell_or_bleed():
    base=selected(1)
    upgraded=selected(2)
    for key in ('shred','claw'):
        before=next(e for e in family(base,key).effects if isinstance(e,WeaponDamageEffect))
        after=next(e for e in family(upgraded,key).effects if isinstance(e,WeaponDamageEffect))
        assert after.crit_multiplier>before.crit_multiplier
        assert after.crit_multiplier == pytest.approx(1+(before.crit_multiplier-1)*1.2/1.1)
    assert family(base,'wrath').effects==family(upgraded,'wrath').effects
    b=next(e for e in family(base,'rake').effects if isinstance(e,PeriodicEffect))
    a=next(e for e in family(upgraded,'rake').effects if isinstance(e,PeriodicEffect))
    assert b.crit_multiplier==a.crit_multiplier
    before={x.id:x for x in base.auto_attacks if x.attack_type=='melee'}
    after={x.id:x for x in upgraded.auto_attacks if x.attack_type=='melee'}
    assert before and before.keys()==after.keys()
    # Pinned source says 'melee abilities', not auto-attacks.
    assert all(after[k].crit_multiplier==before[k].crit_multiplier for k in before)


def test_live_intellect_scales_direct_healing_but_not_spell_damage():
    low=selected(1); high=selected(2)
    results=[]
    for ir in (low,high):
        actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
        rt=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',1e6),spell_power=0)
        heal=family(ir,'healing_touch')
        expected=next(e for e in heal.effects if isinstance(e,HealEffect))
        actor.resource_capacity['mana']=100000
        actor.resources['mana']=100000
        actor.resource_capacity['health']=100000
        actor.resources['health']=1000
        rt.schedule_action(heal)
        rt.advance_to(actor.current_time_s + heal.cast_time_s+0.1)
        amount=sum(e.payload['amount'] for e in rt.trace if e.kind=='Heal')
        assert amount>0
        results.append((amount,actor.stats['intellect'],expected.spell_power_coefficient,rt))
    # Rank delta uses the actor's live Intellect and sourced rank fractions.
    assert results[1][0]-results[0][0]==pytest.approx(
        results[1][1]*(.25-.12)*results[1][2])
    assert results[1][3].actor.effective_healing_power(results[1][3].spell_power)>results[0][3].actor.effective_healing_power(results[0][3].spell_power)


def test_broken_second_clause_stays_nonexecutable():
    original=source_ir();changed=[]
    for t in original.talents:
        if t.id!='natural_instinct':changed.append(t);continue
        ranks=[]
        for rank in t.ranks:
            capture=dict(rank.provenance['checkpoint_source_l0']);capture['additional_value']=None
            ranks.append(replace(rank,provenance={**rank.provenance,'checkpoint_source_l0':capture}))
        changed.append(replace(t,ranks=tuple(ranks)))
    poisoned=replace(original,talents=tuple(changed))
    final,_=compile_talent_runtime(poisoned)
    t=next(t for t in final.talents if t.id=='natural_instinct')
    assert not any(r.modifiers for r in t.ranks)


def test_gate_uses_real_executable_fillers_and_reports_only_actual_application_failures():
    from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
    from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
    audit=audit_checkpoint_p2_executor(source_ir(),db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),
        bonus_talent_points=5)
    for rank in (1,2):
        row=next(row for row in audit['structural_witnesses'] if
            row['talent_id']=='natural_instinct' and row['rank']==rank)
        assert row['application']['status']=='APPLIED_IN_GAME_IR'
        # Newly executable filler ranks may be used by the structural witness.
        # The gate requires an actual successful build, not a specific witness path.
        assert row['application']['target_modifier_applications']>=2
    assert audit['reachable_without_executor']==0
    assert audit['rank_application_failure_count']==0
    assert not audit['green']


def test_paid_100mob_real_combat_damage_changes_with_rank_ablation():
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    outcomes=[]
    for rank in (1,2):
        ir=selected(rank)
        # Controlled player Crit axis exposes actual sourced crit-damage
        # effect; both arms pay the exact same 100mob recovery scenario.
        ir=replace(ir,actor=replace(ir.actor,base_stats={
            **ir.actor.base_stats,'melee_crit_chance':.4}))
        claw=family(ir,'claw')
        policy=PolicyDefinition('cat_claw','Cat Claw',rules=(
            PolicyRuleDefinition('claw',claw.id),))
        r=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,
            target_health=370.,count=100,schedule_incoming_attacks=False,
            pre_combat_action_ids=('cat_form:768',),
            post_combat_action_ids=('cancel_mode:cat',),
            max_actions=120,recovery_mode='always')
        assert len(r.pulls)==100
        assert all(p['pack_all_defeated'] for p in r.pulls)
        outcomes.append((r.seconds_per_mob,
            sum(p['damage_by_role']['player'] for p in r.pulls)))
    assert outcomes[1][1]>outcomes[0][1]
    # Fixed GCDs can quantize kill time even though expected damage changes.
    assert outcomes[1][0]<=outcomes[0][0]

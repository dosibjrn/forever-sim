"""RED: a source-scoped critical-heal talent must change real heal runtime.

This is a generic engine contract, not a 70338 talent certification: the
source multiplier and talent rank curve still need pinned build evidence.
"""
from dataclasses import replace

import pytest

from src.game.data.forever.source_rank_promotion import _compile_clause
from src.game.model.ir import (ActorDefinition, ActionDefinition, GameIRSlice,
    HealEffect, PeriodicHealEffect, TalentDefinition, TalentRankDefinition)
from src.game.runtime import ActorState, TargetState, execute_action
from src.game.runtime.simulator import expected_direct_heal
from src.game.talents import apply_talent_selection

SOURCE = 'https://www.warcrafttavern.com/wow-classic/guides/mana-management-optimization/'


def _fixture():
    effect = HealEffect(effect_type='heal', target='self', resource_id='health',
        base_min=100., base_max=100., crit_multiplier=1.5,
        field_provenance={'crit_multiplier': ({'source_url': SOURCE, 'build': 'classic'},)})
    hot = PeriodicHealEffect(effect_type='periodic_heal', target='self', resource_id='health',
        aura_id='test_hot', total_base_heal=70., duration_s=7., tick_interval_s=1.)
    def action(family, effects):
        return ActionDefinition(id='test:'+family, family_key=family, name=family,
            owner_actor_id='player', requirements=(), costs=(), cast_time_s=0.,
            gcd_s=0., cooldown_s=0., effects=effects, provenance=())
    regrowth=action('regrowth',(effect,hot))
    other=action('healing_touch',(effect,))
    clause = _compile_clause({'domain':'critical_chance_bonus_pct',
        'target':'regrowth', 'sourced_value':10., 'source':SOURCE,
        'condition':'passive'}, actions={'regrowth','healing_touch'},
        schools={'nature'}, actor_stats={'health'}, build='1.60.1.70374')
    assert clause is not None
    talent=TalentDefinition(id='sourced_crit_heal',name='Source critical heal',
        tree_key='test',max_rank=1,ranks=(TalentRankDefinition(rank=1,modifiers=(clause,)),),
        metadata={'row':0})
    ir=GameIRSlice(id='heal-crit',ruleset='test',
        actor=ActorDefinition(id='player',actor_type='player',base_stats={}),
        resources=(),actions=(regrowth,other),talents=(talent,))
    return ir


def test_source_clause_targets_one_heal_family_without_a_spell_whitelist():
    ir=_fixture()
    modifier=ir.talents[0].ranks[0].modifiers[0]
    assert (modifier.kind,modifier.target_type,modifier.target_id,modifier.value)==(
        'crit_chance_pct','action_family','regrowth',pytest.approx(.10))


def test_heal_crit_modifier_changes_direct_heal_only_not_hot_or_other_family():
    ir=_fixture()
    changed,applied=apply_talent_selection(ir,{'sourced_crit_heal':1},level=30)
    original=ir.actions[0]
    new=changed.actions[0]
    assert new.effects[0].crit_chance_bonus==pytest.approx(.10)
    assert new.effects[1]==original.effects[1]
    assert changed.actions[1]==ir.actions[1]
    assert original.effects[0].crit_chance_bonus==0.
    assert applied.applied_modifiers


def test_crit_changes_real_heal_and_rejects_unsourced_multiplier():
    ir=_fixture()
    changed,_=apply_talent_selection(ir,{'sourced_crit_heal':1},level=30)
    base=ir.actions[0].effects[0]
    boosted=changed.actions[0].effects[0]
    assert expected_direct_heal(base)==pytest.approx(100.)
    assert expected_direct_heal(boosted)==pytest.approx(105.)
    for effect,expected in ((base,100.),(boosted,105.)):
        button=replace(ir.actions[0],effects=(effect,))
        actor=ActorState(id='player',stats={},resources={'health':100.},
            resource_capacity={'health':1000.})
        result=execute_action(action=button,actor=actor,
            target=TargetState.with_health('dummy',1000.))
        heals=[e for e in result.events if e.kind=='Heal']
        assert len(heals)==1 and heals[0].payload['amount']==pytest.approx(expected)
    with pytest.raises(ValueError,match='HEAL_CRIT_MULTIPLIER_UNSOURCED'):
        expected_direct_heal(replace(boosted,field_provenance={}))

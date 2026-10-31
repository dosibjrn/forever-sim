"""Executable sourced talent families across canonical IR, scorer and runtime."""
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import load_sqlite_talents, DEFAULT_DB
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.data.forever.target_combat_source import target_combat_metadata


def test_source_hit_bonus_changes_actual_outgoing_damage():
    ir=build_game_ir_slice(class_key='druid',level=20)
    allocation={'improved_wrath':5,'natures_reach':2}
    changed,application=apply_talent_selection(ir,allocation,level=20)
    wrath=next(a for a in changed.actions if a.family_key=='wrath')
    old=next(a for a in ir.actions if a.family_key=='wrath')
    assert wrath.metadata['outgoing_hit_bonus']==pytest.approx(0.04)
    assert any(m['kind']=='hit_chance_bonus' for m in application.applied_modifiers)

    def damage(game_ir,action):
        actor=ActorState.from_ir(game_ir.actor,game_ir.resources,game_ir.modes)
        target=TargetState.with_health('target',100000.,**target_combat_metadata(game_ir))
        runtime=CombatRuntime(actor=actor,target=target)
        runtime.schedule_action(action)
        runtime.advance_to(actor.current_time_s+action.cast_time_s)
        events=[e for e in runtime.result().events if e.kind=='Damage' and e.payload.get('applied')]
        assert events
        return events[0].payload
    base=damage(ir,old);new=damage(changed,wrath)
    assert new['source_hit_bonus']==pytest.approx(0.04)
    assert new['effective_hit_chance']==pytest.approx(min(1.,base['source_base_hit']+0.04))
    assert new['amount']>base['amount']
    assert new['amount']/base['amount']==pytest.approx(new['effective_hit_chance']/base['effective_hit_chance'])


def test_reflection_casting_regen_only_during_cast_and_no_double_recovery():
    ir=build_game_ir_slice(class_key='druid',level=24)
    allocation={'furor':5,'naturalist':5,'reflection':1}
    changed,_=apply_talent_selection(ir,allocation,level=24)
    actor=ActorState.from_ir(changed.actor,changed.resources,changed.modes)
    assert actor.stats['casting_mana_regen_fraction']==pytest.approx(.17)
    wrath=next(a for a in changed.actions if a.family_key=='wrath')
    actor.spend('mana',100.)
    before=actor.resource_amount('mana')
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('target',100000.))
    runtime.schedule_action(wrath)
    runtime.advance_to(actor.current_time_s+wrath.cast_time_s)
    after=actor.resource_amount('mana')
    assert after>before-sum(c.amount for c in wrath.costs)
    assert any(e.kind=='ResourceRegenerated' and e.payload.get('source')=='casting_mana_regeneration_talent'
               for e in runtime.result().events)
    # The same casting resource modifier must not leak into non-casting idle time.
    before_idle=actor.resource_amount('mana')
    runtime.advance_to(actor.current_time_s+5.)
    assert actor.resource_amount('mana')==pytest.approx(before_idle)
    # Recovery grants full ordinary passive mana, not another talent cast bonus.
    recovery_actor=ActorState.from_ir(changed.actor,changed.resources,changed.modes)
    recovery_actor.spend('mana',100.)
    recovery_runtime=CombatRuntime(actor=recovery_actor,target=TargetState.with_health('recovery',1.),
                                   enable_casting_regen=False)
    recovery_runtime.schedule_action(wrath)
    recovery_runtime.advance_to(recovery_actor.current_time_s+wrath.cast_time_s)
    assert not any(e.payload.get('source')=='casting_mana_regeneration_talent'
                   for e in recovery_runtime.result().events)


def test_unverified_offensive_spell_scope_fails_closed(tmp_path):
    path=tmp_path/'facts.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    with sqlite3.connect(path) as conn:
        conn.execute('DELETE FROM talent_effect_scope_source_facts WHERE spell_id=16819')
    ir=build_game_ir_slice(class_key='druid',level=20)
    result=load_sqlite_talents('druid',action_families=[a.family_key for a in ir.actions],db_path=path)
    talent=next(t for t in result.talents if t.name=="Nature's Reach")
    assert not any(rank.modifiers for rank in talent.ranks)
    assert any('offensive_spell_hit_scope_not_verified' in str(row) for row in talent.metadata['unsupported_rank_effects'])
    # No hidden legal no-op talent is allowed into the optimizer.
    from dataclasses import replace
    stripped=replace(ir,talents=tuple(result.talents))
    with pytest.raises(ValueError,match='unsupported talent effect'):
        validate_talent_selection(stripped,{'natures_reach':1},level=20)


def test_illegal_row_gate_still_rejected():
    ir=build_game_ir_slice(class_key='druid',level=20)
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(ir,{'natures_reach':1},level=20)


def test_reflection_changes_real_three_pull_recovery_objective():
    from src.v2.source_joint_discovery import _gear_envelope
    from src.v2.source_multi_pull_joint import _score_state
    from src.shared.leveling.objective import representative_hp
    ir=build_game_ir_slice(class_key='druid',level=24)
    gear=_gear_envelope('druid',24,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)[0]
    common={'furor':5,'naturalist':5}
    def score(a):
        result=_score_state(ir,level=24,gear=gear,allocation=a,pulls=3,
            policy_cap=8,target_health=representative_hp(24))
        assert result['best_policy'] and result['policy_evaluated']>0
        return result['seconds_per_mob']
    before=score(common)
    after=score({**common,'reflection':1})
    assert after < before
    assert before==pytest.approx(15.252100840336134)
    assert after==pytest.approx(14.992300075395839)

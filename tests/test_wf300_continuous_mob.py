"""WF300: state-correct persistent encounter validation on canonical CombatRuntime."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.policy import opening_for_persistent_actor
from src.game.runtime import ActorState
from tools.wf299_100_mob_continuity_probe import run

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json'
FROZEN = ROOT / 'fixtures/wf243_heldout_feral_l20.json'


def _scenario():
    ir = build_game_ir_slice(class_key='druid',level=20)
    form = next(a for a in ir.actions if a.id == 'cat_form:768')
    claw = next(a for a in ir.actions if a.id == 'claw:20')
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    return ir, form, claw, actor


def test_only_satisfied_leading_pure_mode_action_is_removed():
    ir, form, claw, actor = _scenario()
    seq = (form.id,claw.id)
    assert opening_for_persistent_actor(opening_action_ids=seq,actions=ir.actions,actor=actor)==(seq,())
    actor.transition_mode('cat')
    assert opening_for_persistent_actor(opening_action_ids=seq,actions=ir.actions,actor=actor)==((claw.id,), (form.id,))
    # Never drop a damaging/composite action, even when its mode effect is redundant.
    impure = replace(form, effects=(*form.effects,*claw.effects))
    augmented=tuple(impure if a.id==form.id else a for a in ir.actions)
    assert opening_for_persistent_actor(opening_action_ids=seq,actions=augmented,actor=actor)==(seq,())
    # Only leading already-satisfied transitions, never actions in the middle.
    assert opening_for_persistent_actor(opening_action_ids=(claw.id,form.id),actions=ir.actions,actor=actor)==((claw.id,form.id),())


def test_unknown_or_other_actor_action_blocks_instead_of_being_skipped():
    ir, form, claw, actor = _scenario()
    actor.transition_mode('cat')
    with pytest.raises(ValueError,match='BLOCKED_ILLEGAL_PREFIX'):
        opening_for_persistent_actor(opening_action_ids=('missing:spell',),actions=ir.actions,actor=actor)
    with pytest.raises(ValueError,match='wrong source action owner'):
        opening_for_persistent_actor(opening_action_ids=(form.id,),actions=(replace(form,owner_actor_id='someone_else'),),actor=actor)


def test_100_mobs_persistent_model_new_beats_old_same_runtime():
    new = run(EVIDENCE,mobs=100)
    old = run(FROZEN,mobs=100,historical=True)
    for result in (new,old):
        assert result['status']=='COMPLETE_100_MOBS'
        assert result['count']==100 and result['continuous_actor_state']
        assert result['same_combat_runtime_and_recovery']
        assert result['all_mobs_executed_at_least_one_action']
        assert result['all_mobs_ended_full_health']
        assert result['events']>=100
        assert abs(result['total_s']/100-result['mean_s_per_mob'])<1e-9
    assert new['first']['selected_actions'][0]=='cat_form:768'
    assert new['second']['selected_actions'][0]=='claw:20'
    assert new['second']['already_satisfied_mode_actions']==['cat_form:768'] or new['second']['already_satisfied_mode_actions']==('cat_form:768',)
    assert new['mean_s_per_mob']<old['mean_s_per_mob']
    assert abs(new['mean_s_per_mob']-15.220151660626406)<1e-8
    assert abs(old['mean_s_per_mob']-16.000725038494057)<1e-8

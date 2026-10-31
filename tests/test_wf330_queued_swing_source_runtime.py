"""WF330: real queued-swing timeline from stage-bound Maul source observations.

No class/spell name or damage constants are in the generic runtime.
"""
import copy
import json
import shutil
import sqlite3
from pathlib import Path
import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_queued_swing import ingest
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime, ActionNotEligibleError
from src.v2.source_budgeted_prefix import source_prefix_envelope

SOURCE = Path('evidence/wf330/druid_l20_maul_observations.json')

@pytest.fixture
def stage(tmp_path,monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    path=tmp_path/'stage.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    ingest(path,SOURCE)
    return path

def ir(stage,level=20):
    return build_game_ir_slice(class_key='druid',level=level,ability_db_path=stage)

def runtime(ir,rage=35,mode='bear'):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode(mode)
    actor.resources['rage']=rage
    return CombatRuntime(actor=actor,target=TargetState.with_health('enemy',1_000_000),auto_attacks=ir.auto_attacks)

def test_legal_ranks_and_source_bound_values(stage):
    assert not any(a.id.startswith('source_queued_swing:') for a in ir(stage,9).actions)
    assert [a.id for a in ir(stage,10).actions if a.id.startswith('source_queued_swing:')]==['source_queued_swing:6807']
    actions={a.id:a for a in ir(stage).actions if a.id.startswith('source_queued_swing:')}
    assert set(actions)=={'source_queued_swing:6807','source_queued_swing:6808'}
    assert [actions[k].effects[0].bonus_damage for k in sorted(actions)]==[18.,27.]
    assert all(a.costs[0].amount==15 and a.gcd_s==0 for a in actions.values())
    assert all(not a.provenance[0]['independent_detail_html_verified'] for a in actions.values())

def test_on_next_swing_cost_no_immediate_damage_one_replacement(stage):
    game=ir(stage)
    action=next(a for a in game.actions if a.id=='source_queued_swing:6808')
    with_queue=runtime(game);without=runtime(game)
    with_queue.schedule_action(action)
    assert with_queue.actor.resources['rage']==20
    assert with_queue.total_damage==0
    assert any(e.kind=='QueuedSwingArmed' for e in with_queue.trace)
    with_queue.advance_to(2.49); without.advance_to(2.49)
    assert with_queue.total_damage==without.total_damage==0
    with_queue.advance_to(2.5);without.advance_to(2.5)
    assert with_queue.total_damage>without.total_damage
    bonus_expected=27*(next(e for e in with_queue.trace if e.kind=='AutoAttackOutcome').payload['outcome_weights']['hit'] +
                       next(e for e in with_queue.trace if e.kind=='AutoAttackOutcome').payload['outcome_weights']['crit'] *
                       next(e for e in with_queue.trace if e.kind=='AutoAttackOutcome').payload['crit_multiplier'])
    assert with_queue.total_damage-without.total_damage==pytest.approx(bonus_expected)
    damage=[e for e in with_queue.trace if e.kind=='Damage']
    assert len(damage)==1 and damage[0].action_id==action.id
    assert damage[0].payload['queued_swing_replacement']
    assert not damage[0].payload['auto_attack']  # not a white rage-generating swing
    with_queue.advance_to(5)
    later=[e for e in with_queue.trace if e.kind=='Damage']
    assert later[-1].action_id=='auto_attack:bear'
    assert not with_queue.pending_queued_swing

def test_double_queue_fails_before_spending_and_older_rank_cannot_replace(stage):
    game=ir(stage);byid={a.id:a for a in game.actions}
    rt=runtime(game,rage=50)
    rt.schedule_action(byid['source_queued_swing:6808'])
    before=rt.actor.resources['rage']
    with pytest.raises(ActionNotEligibleError,match='already pending'):
        rt.schedule_action(byid['source_queued_swing:6807'])
    assert rt.actor.resources['rage']==before
    assert len([e for e in rt.trace if e.kind=='QueuedSwingArmed'])==1

def test_mode_transition_cancels_pending_without_fictitious_swing(stage):
    game=ir(stage); action=next(a for a in game.actions if a.id=='source_queued_swing:6808')
    rt=runtime(game);rt.schedule_action(action)
    rt.actor.transition_mode('cat')
    rt.advance_to(2.5)
    assert any(e.kind=='QueuedSwingCancelled' for e in rt.trace)
    assert not any(e.kind=='Damage' and e.action_id==action.id for e in rt.trace)
    assert not rt.pending_queued_swing

def test_invalid_source_mutations_fail_closed(stage,tmp_path):
    obj=json.loads(SOURCE.read_text())
    obj['observations'][0]['cast']='Instant'
    file=tmp_path/'invalid.json';file.write_text(json.dumps(obj))
    with pytest.raises(ValueError,match='UNPARSED_OBSERVATION'):
        ingest(stage,file)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE source_queued_swing_observations SET bonus_damage=9000 WHERE spell_id=6808")
    with pytest.raises(ValueError,match='STORED_FACT_DIFFERS'):
        ir(stage)
    ingest(stage,SOURCE)
    with sqlite3.connect(stage) as db:
        db.execute("UPDATE spell_index SET name='Maul forged' WHERE spell_id=6808 AND class_key='druid'")
    with pytest.raises(ValueError,match='INDEX_IDENTITY_DRIFT'):
        ir(stage)

def test_optimizer_sees_source_queued_melee_not_free_instant(stage):
    game=ir(stage)
    envelope=source_prefix_envelope(game,level=20)
    bear=next(p for p in envelope['mode_paths'] if p['mode_id']=='bear')
    assert 'source_queued_swing:6808' in bear['actions']
    assert 'source_queued_swing:6807' in bear['actions']
    assert 'source_queued_swing:6808' not in envelope['actions']  # cannot cast in humanoid
    front=action_frontier(game,class_key='druid',level=20,db_path=stage)
    row=next(r for r in front['records'] if r.get('spell_id')==6808)
    assert 'source_queued_swing:6808' in row['ir_action_ids']
    assert row['ir_proxies'][0]['effect_roles']==['direct_damage']

def test_real_paid_source_prefix_waits_for_rage_and_lands_maul(stage):
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    from src.v2.generic_backend import _policy_combat_evaluation
    game=ir(stage)
    fallback=PolicyDefinition(id='source:bear-swipe',label='Source L2 fallback',
        rules=(PolicyRuleDefinition(id='fallback',action_id='swipe:16'),),
        provenance={'authority':'sourced_l2_probe'})
    result,execution,details=_policy_combat_evaluation(game,level=20,
        policy_override=fallback,
        opening_action_ids=('bear_form:5487','enrage:5229','source_queued_swing:6808'))
    assert result is not None and execution.timeline.target_defeated
    assert [x['action_id'] for x in execution.selected_actions[:3]]==[
        'bear_form:5487','enrage:5229','source_queued_swing:6808']
    queued=[e for e in execution.timeline.events if e.kind=='QueuedSwingArmed']
    damaging=[e for e in execution.timeline.events if e.kind=='Damage' and e.action_id=='source_queued_swing:6808']
    assert len(queued)==1 and len(damaging)==1
    assert queued[0].time_s < damaging[0].time_s
    assert details['actor_survived']

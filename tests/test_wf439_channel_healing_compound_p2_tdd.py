"""Actual channeled healing and atomic two-clause talent validation at P2."""
from dataclasses import replace
from pathlib import Path
import json,sqlite3,shutil
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf439_ingest_channel_heal import ingest

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf439/SOURCE_CHANNEL_HEAL_INDEX.json'
FILL={'furor':5,'natural_shapeshifter':3,'naturalist':5,
      'natures_focus':5,'subtlety':2}

def compiled(db=DB):
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=db))[0]

def selected(rank):
    ir=compiled()
    if rank:ir=apply_talent_selection(ir,{**FILL,'improved_tranquility':rank},
                                     level=30,bonus_talent_points=5)[0]
    return ir

def tranquility(ir):
    return next(a for a in ir.actions if a.family_key=='tranquility')


def test_source_index_action_is_solo_healing_channel_with_explicit_party_scope_gap():
    action=tranquility(compiled())
    assert action.id=='source_spell:740'
    assert action.cooldown_s==pytest.approx(300)
    assert action.cast_time_s==pytest.approx(10)
    assert action.costs[0].amount==pytest.approx(375)
    assert action.effects[0].total_base_heal==pytest.approx(455)
    assert action.effects[0].tick_interval_s==pytest.approx(2)
    assert action.metadata['channel'] is True
    assert action.metadata['unsupported_party_scope'] is True
    assert action.metadata['source_build_bridge_verified'] is False


def test_both_ranks_modify_cooldown_and_threat_with_no_discarded_clause():
    expected=((0,300.,1.),(1,210.,.5),(2,120.,0.))
    for rank,seconds,threat in expected:
        action=tranquility(selected(rank))
        assert action.cooldown_s==pytest.approx(seconds)
        assert action.metadata.get('threat_multiplier',1.)==pytest.approx(threat)
    talent=next(t for t in compiled().talents if t.id=='improved_tranquility')
    assert [[m.kind for m in rank.modifiers] for rank in talent.ranks]==[
        ['cooldown_factor_pct','threat_factor_pct']]*2


def test_real_channel_is_paid_and_blocks_casts_until_last_periodic_heal_tick():
    ir=selected(2);action=tranquility(ir)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['health']=100.
    actor.resources['mana']=800.
    actor.resource_capacity['mana']=max(800.,actor.resource_capacity['mana'])
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',2000))
    rt.schedule_action(action)
    ticks=[e for e in rt.trace if e.kind=='Heal' and e.action_id==action.id]
    assert len(ticks)==5
    assert [e.time_s for e in ticks]==pytest.approx([2.,4.,6.,8.,10.])
    assert actor.current_time_s==pytest.approx(10.)
    assert actor.resources['mana']==pytest.approx(425.)
    assert 100. <actor.resources['health']<=actor.resource_capacity['health']
    assert actor.cooldown_ready_s[action.id]==pytest.approx(120.)


def test_source_index_tamper_is_rejected_and_untrained_action_cannot_fake_modifier(tmp_path):
    db=tmp_path/'staged.sqlite';shutil.copy2(DB,db)
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=740')
    ir=compiled(db)
    assert not any(a.family_key=='tranquility' for a in ir.actions)
    talent=next(t for t in ir.talents if t.id=='improved_tranquility')
    assert all(not rank.modifiers for rank in talent.ranks)
    with pytest.raises(ValueError,match='unsupported talent effect'):
        apply_talent_selection(ir,{**FILL,'improved_tranquility':1},level=30,bonus_talent_points=5)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=740',('{}',))
    with pytest.raises(ValueError,match='SOURCE_CHANNEL_OBSERVATION_MISMATCH'):
        ingest(db,OBS)


def test_source_ingest_idempotent_and_cannot_self_certify_bridge(tmp_path):
    db=tmp_path/'stage.sqlite';shutil.copy2(DB,db)
    assert ingest(db,OBS)==1
    assert ingest(db,OBS)==1
    obj=json.loads(OBS.read_text());obj['records'][0]['source_build_verified']=True
    invalid=tmp_path/'invalid.json';invalid.write_text(json.dumps(obj))
    with pytest.raises(ValueError,match='SOURCE_CHANNEL_OBSERVATION_MISMATCH'):
        ingest(db,invalid)


def test_p2_rank_witness_proved_but_party_threat_source_still_red():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    report=audit_checkpoint_p2_executor(ir,db_path=DB,
         checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    for rank in (1,2):
        row=next(r for r in report['structural_witnesses']
                 if r['talent_id']=='improved_tranquility' and r['rank']==rank)
        assert row['application']['status']=='APPLIED_IN_GAME_IR'
        assert row['status']=='SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS'
        assert 'SOURCE_CHANNEL_PARTY_HEAL_OR_THREAT_NOT_EXECUTED' in row['partial_semantics']
        assert 'SOURCE_CHANNEL_ABILITY_BUILD_BRIDGE_UNVERIFIED' in row['partial_semantics']
    assert not report['green']
    # Later P2 implementations can reduce this count; this test protects the
    # Tranquility partial-semantics blocker, not a stale exact deficit snapshot.
    assert report['reachable_without_executor']<=7

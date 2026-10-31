"""WF440: Bash source control ingestion and sourced 2-clause Brutal Impact."""
from pathlib import Path
from dataclasses import replace
import json,sqlite3,shutil
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from tools.wf440_ingest_direct_control import ingest
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf440/SOURCE_DIRECT_CONTROL_INDEX.json'

def base(db=DB):
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=db))[0]

def choice(rank,db=DB):
    return apply_talent_selection(base(db),{'ferocity':5,'brutal_impact':rank},
                                  level=30,bonus_talent_points=5)[0]

def bash(ir,spell_id=6798):
    return next(a for a in ir.actions if a.family_key=='bash' and a.id.endswith(str(spell_id)))

@pytest.mark.parametrize('rank,cd,duration',[(0,60.,3.),(1,45.,3.5),(2,30.,4.)])
def test_source_bash_and_both_talent_ranks_real_control_cooldown(rank,cd,duration):
    ir=base() if not rank else choice(rank)
    assert {a.id for a in ir.actions if a.family_key=='bash'}=={'source_spell:5211','source_spell:6798'}
    a=bash(ir)
    assert a.cooldown_s==pytest.approx(cd)
    assert a.effects[0].duration_s==pytest.approx(duration)
    assert a.costs[0].resource_id=='rage' and a.costs[0].amount==pytest.approx(10.)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear');actor.resources['rage']=20.;actor.resource_regeneration_per_s['rage']=0.
    rt=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',1000.))
    rt.schedule_action(a)
    assert actor.resources['rage']==pytest.approx(10.)
    assert rt.target.active_controls['stun']==pytest.approx(duration)
    assert actor.cooldown_ready_s[a.id]==pytest.approx(cd)
    assert actor.gcd_ready_s==pytest.approx(1.5)
    rt.advance_to(duration+.1)
    assert 'stun' not in rt.target.active_controls
    # Opposing ability is not allowed until cooldown expires.
    from src.game.runtime.simulator import action_eligibility
    assert not action_eligibility(action=a,actor=actor,target=rt.target).eligible


def test_lower_rank_preserved_and_duration_buff_not_confused_with_cooldown():
    a= bash(choice(2),5211)
    assert a.effects[0].duration_s==pytest.approx(3.)
    assert a.cooldown_s==pytest.approx(30.)


def test_source_modifiers_require_both_effect_clauses_not_partial():
    ir=base();t=next(t for t in ir.talents if t.id=='brutal_impact')
    for rank in t.ranks:
        assert [m.kind for m in rank.modifiers]==['control_duration_delta_s','cooldown_delta_s']
        assert all(m.provenance['unsupported_build_bridge'] for m in rank.modifiers)


def test_source_ingestion_idempotent_and_tampering_fails_closed(tmp_path):
    db=tmp_path/'copy.sqlite';shutil.copy2(DB,db)
    assert ingest(db,OBS)==2 and ingest(db,OBS)==2
    with sqlite3.connect(db) as conn:
        count=conn.execute('select count(*) from ability_semantic_source_facts where semantic_type=?',('direct_control',)).fetchone()[0]
    assert count>=2
    doc=json.loads(OBS.read_text());doc['records'][0]['indexed_payload_sha256']='f'*64
    file=tmp_path/'bad.json';file.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='INVALID_SOURCE_DIRECT_CONTROL_OBSERVATION'):ingest(db,file)


def test_checkpoint_rank_enters_real_application_but_crossbuild_blocks_green():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    report=audit_checkpoint_p2_executor(ir,db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    for rank in (1,2):
        row=next(r for r in report['structural_witnesses'] if r['talent_id']=='brutal_impact' and r['rank']==rank)
        assert row['application']['status']=='APPLIED_IN_GAME_IR'
        assert 'SOURCE_BUILD_BRIDGE_UNVERIFIED' in row['partial_semantics']
    assert report['reachable_without_executor']==2
    assert not report['green']

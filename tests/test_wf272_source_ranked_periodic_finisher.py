"""WF272: every sourced CP ladder is executable, no class damage constants."""
from dataclasses import replace
import json
import sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_ability_semantics import source_ability_actions,parse_resource_scaled_periodic_ladder
from src.game.multi_pull import evaluate_repeated_pulls
from tools.ingest_source_resource_scaled_periodic import ingest

RANKS=((20,1079,150),(28,9492,240),(36,9493,291),(44,9752,429),(52,9894,612),(60,9896,855))

def copy_db(tmp_path):
    p=tmp_path/'source.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(p) as dest:source.backup(dest)
    return p

def stripped(ir):
    ids={a.id for a in ir.actions if a.family_key=='rip'}
    return replace(ir,actions=tuple(a for a in ir.actions if a.id not in ids),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else
            tuple(i for i in m.enabled_action_ids if i not in ids))) for m in ir.modes))

def test_all_six_source_rank_ladders_and_exact_policy_refs():
    assert not [a for a in build_game_ir_slice(class_key='druid',level=19).actions if a.family_key=='rip']
    for level,sid,total in RANKS:
        ir=build_game_ir_slice(class_key='druid',level=level)
        actions=[a for a in ir.actions if a.family_key=='rip']
        assert len(actions)==next(i for i,(train,_,_) in enumerate(RANKS,1) if train==level)
        action=next(a for a in actions if a.id==f'rip:{level}')
        assert action.id==f'rip:{level}'
        assert action.metadata['source_semantic_type']=='resource_scaled_periodic'
        assert action.effects[0].total_base_damage_by_resource_amount[5]==total
        assert action.effects[1].resource_id=='combo_points'
        assert action.effects[1].operation=='set' and action.effects[1].amount==0
        assert all(a.id in next(m for m in ir.modes if m.id=='cat').enabled_action_ids for a in actions)
        policy=next(p for p in ir.policies if 'cat-builder-finisher' in p.id)
        assert policy.rules[0].action_id==action.id
        assert any(f.get('fact_kind')=='required_source_action' and f.get('spell_id')==sid
                   for f in ir.source_facts)
        assert any(c.get('semantic')=='attack_power_scaling' and c.get('status')=='explicit_gap'
                   for c in action.effects[0].unsupported_semantics)

def test_data_only_ladder_mutation_compiles_without_provider_edits(tmp_path):
    db=copy_db(tmp_path)
    before=build_game_ir_slice(class_key='druid',level=28)
    with sqlite3.connect(db) as conn:
        obj=json.loads(conn.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=9492').fetchone()[0])
        obj['envChange']['after']['text']=obj['envChange']['after']['text'].replace('5 points: 240 damage','5 points: 340 damage')
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=9492',(json.dumps(obj),))
    newer=source_ability_actions(stripped(before),class_key='druid',level=28,db_path=db)
    rip=next(a for a in newer.actions if a.family_key=='rip')
    assert rip.effects[0].total_base_damage_by_resource_amount[5]==340

def test_malformed_source_rank_and_missing_semantics_fail_closed(tmp_path):
    db=copy_db(tmp_path)
    ir=build_game_ir_slice(class_key='druid',level=28)
    with sqlite3.connect(db) as conn:
        raw=json.loads(conn.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=9492').fetchone()[0])
        raw['envChange']['after']['text']=raw['envChange']['after']['text'].replace('5 points: 240 damage over 12 sec.','')
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=9492',(json.dumps(raw),))
    with pytest.raises(ValueError,match='invalid sourced resource-scaled periodic rank'):
        source_ability_actions(stripped(ir),class_key='druid',level=28,db_path=db)
    with pytest.raises(ValueError,match='unparsed resource-scaled periodic'):
        parse_resource_scaled_periodic_ladder('1 point: 40 damage')
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE spell_id=9492')
    with pytest.raises(ValueError,match='required source action not executable'):
        source_ability_actions(stripped(ir),class_key='druid',level=28,db_path=db)

def test_atomic_ingest_rejects_partial_family(tmp_path):
    db=copy_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM ability_semantic_source_facts WHERE class_key="druid" AND semantic_type="resource_scaled_periodic"')
        obj=json.loads(conn.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=9896').fetchone()[0])
        obj['envChange']['after']['text']='BAD'
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=9896',(json.dumps(obj),))
    with pytest.raises(ValueError,match='unparsed resource-scaled periodic'):
        ingest(db,class_key='druid',family='Rip',required_mode='cat',resource_id='combo_points',
               tick_interval_s=2,mechanics_url='https://www.wowhead.com/forever/spell=1079',
               mechanics_evidence='legacy transcription')
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ability_semantic_source_facts WHERE semantic_type="resource_scaled_periodic"').fetchone()[0]==0

def test_real_executor_three_pulls_across_rank_boundary():
    for level,hp in ((20,360),(28,500),(36,800)):
        ir=build_game_ir_slice(class_key='druid',level=level)
        policy=next(p for p in ir.policies if 'cat-builder-finisher' in p.id)
        def run():return evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=level,
            target_health=hp,count=3,pre_combat_action_ids=('cat_form:768',),
            post_combat_action_ids=('cancel_mode:cat',),
            prepared_first_pull_resources={'energy':100,'rage':0},
            recovery_mode='threshold',retain_mode_between_pulls=True,
            travel_time_s=2.2,apply_target_defense=True)
        a,b=run(),run()
        assert a.seconds_per_mob==b.seconds_per_mob
        assert a.seconds_per_mob>0

def test_all_source_rank_ids_survive_in_ir_and_coverage_ledger():
    from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
    ir=build_game_ir_slice(class_key='druid',level=60)
    records=indexed_ability_coverage(ir,class_key='druid',level=60)['records']
    by_id={x['spell_id']:x for x in records}
    for level,sid,_ in RANKS:
        assert by_id[sid]['matched_action_ids']==[f'rip:{level}']
        assert by_id[sid]['status']=='SOURCE_ID_MATCHES_IR_ACTION_ACQUISITION_UNVERIFIED'
    assert not ir.provenance['complete_source_action_coverage']

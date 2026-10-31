"""Paladin sourced rank families through the actual native generic score path."""
import json,sqlite3
from dataclasses import replace
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_talent_overlay import source_enrich_indexed_talents
from src.game.talents import apply_talent_selection,validate_talent_selection
from src.game.talent_search import executable_talent_definitions
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.shared.leveling.objective import representative_hp
from tools.wf254_ingest_paladin_talents import ingest

def ir():return build_game_ir_slice(class_key='paladin',level=20)

def test_rank_coverage_and_generic_loader():
    x=ir();d={t.id:t for t in executable_talent_definitions(x)}
    assert len(x.talents)==49 and len(d)==6
    assert {k:d[k].max_rank for k in d}=={'benediction':5,'conviction':5,
        'improved_judgement':2,'improved_seals':3,'divine_strength':5,
        'seal_of_command':1}
    assert x.provenance['talent_tree_rules']['verified_current'] is False
    assert all(not d[k].metadata['tree_row_verified'] for k in d if k!='seal_of_command')
    assert d['seal_of_command'].metadata['row']==2
    assert len(list(sqlite3.connect(DEFAULT_DB).execute(
        "SELECT * FROM talent_rank_source_facts WHERE class_key='paladin'")))==20

def test_instant_cost_and_judgement_cooldown():
    x=ir();y,a=apply_talent_selection(x,{'benediction':5,'improved_judgement':2},level=20)
    before={z.family_key:z for z in x.actions};after={z.family_key:z for z in y.actions}
    assert after['judgement'].cooldown_s==pytest.approx(8.)
    for family in ('judgement','holy_strike','seal_of_righteousness'):
        assert after[family].costs[0].amount==pytest.approx(before[family].costs[0].amount*.9)
    assert after['holy_light'].costs[0].amount==before['holy_light'].costs[0].amount

def test_melee_crit_and_seal_trigger_damage():
    x=ir();y,a=apply_talent_selection(x,{'divine_strength':5,'improved_seals':3},level=20)
    for old,new in zip(x.triggers,y.triggers):
        if old.metadata.get('effect_category')=='seal_damage':
            assert new.effects[0].base_min==pytest.approx(old.effects[0].base_min*1.15)
        else:
            assert new.effects==old.effects
    z,_=apply_talent_selection(x,{'benediction':5,'conviction':3},level=20)
    assert z.actor.base_stats['melee_crit_chance']==pytest.approx(.03)
    assert y.actor.base_stats['strength']==pytest.approx(x.actor.base_stats['strength']*1.1)

def test_negative_tier_gate_and_rank_limits():
    x=ir()
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(x,{'improved_seals':1},level=20)
    with pytest.raises(ValueError,match='illegal rank'):
        validate_talent_selection(x,{'benediction':6},level=20)
    with pytest.raises(ValueError,match='point'):
        validate_talent_selection(x,{'benediction':5,'divine_strength':5,'conviction':5},level=20)
    with pytest.raises(ValueError,match='unknown'):
        validate_talent_selection(x,{'imaginary':1},level=20)

def test_real_three_pull_score_differs_with_seal_talent():
    x=ir()
    base,_=apply_talent_selection(x,{'divine_strength':5},level=20)
    buffed,_=apply_talent_selection(x,{'divine_strength':5,'improved_seals':3},level=20)
    seal=next(a for a in x.actions if a.family_key=='seal_of_righteousness')
    judge=next(a for a in x.actions if a.family_key=='judgement')
    policy=PolicyDefinition(id='source_three_pull_seal',label='Source seal then judge',rules=(
        PolicyRuleDefinition('s',seal.id,conditions=(PolicyCondition('aura_missing',scope='actor',aura_id='seal:righteousness'),)),
        PolicyRuleDefinition('j',judge.id,conditions=(PolicyCondition('aura_present',scope='actor',aura_id='seal:righteousness'),))),)
    a=evaluate_repeated_pulls(ir_slice=base,policy=policy,level=20,target_health=450,count=3,apply_target_defense=True)
    b=evaluate_repeated_pulls(ir_slice=buffed,policy=policy,level=20,target_health=450,count=3,apply_target_defense=True)
    assert b.seconds_per_mob<a.seconds_per_mob
    assert any(e['action_id'].startswith('judgement') for pull in b.pulls for e in pull['selected_actions'])

def test_ingest_idempotent_and_cross_class_unmodified():
    assert ingest()['rank_rows']==20
    assert ingest()['rank_rows']==20
    for cls in ('hunter','mage','druid'):
        x=build_game_ir_slice(class_key=cls,level=20)
        assert x is not None and all(t.id!='benediction' for t in x.talents)

def test_rejects_unindexed_or_incomplete_rank_capture(tmp_path):
    from tools.wf254_ingest_paladin_talents import CAPTURE
    original=json.loads(CAPTURE.read_text())
    bad=dict(original);bad['families']=[dict(x) for x in original['families']]
    bad['families'][0]['ranks']=bad['families'][0]['ranks'][:-1]
    p=tmp_path/'invalid.json';p.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='rank curve mismatch'):
        ingest(capture_path=p)
    bad['families'][0]=dict(original['families'][0],spell_id=999999)
    p.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='index identity'):
        ingest(capture_path=p)

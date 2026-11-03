"""P1 executable effects are independent of historical trainer spellbook proof."""
from pathlib import Path
from types import SimpleNamespace as N
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from wf_gate_p1_live import audit_inventory, _runtime_exercise
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.policy_evolution import from_source_rules,scratch_policies


def test_executable_ability_needs_no_acquisition_ledger_but_needs_effect():
    row=dict(spell_id=100,name='Example',rank_hint=1,level_hint=10,
             raw_listview_json='{}',source_url='https://example.invalid')
    action=N(id='source_spell:100',owner_actor_id='me',
             effects=(object(),),requirements=(),
             provenance=({'source_spell_id':100},),metadata={})
    ir=N(actor=N(id='me'),actions=(action,),modes=(),resources=())
    policy=lambda aid:N(rules=(N(action_id=aid),))
    args=dict(parser=lambda a:{100},
              source_classifier=lambda r,raw:{'role':'ABILITY'},
              policy_builder=lambda ir,rules:policy(rules[0][0]),
              scratch_builder=lambda ir,max_candidates:[policy('source_spell:100')],
              effect_checker=lambda e:'direct_damage')
    positive=audit_inventory([row],ir,executor=lambda ir,a:{
        'status':'executed','effect_observed':True},**args)
    assert positive['status']=='PASS',positive['problems']
    assert positive['production_runtime_exercises']==1
    assert not any('ACQUISITION' in x['code'] for x in positive['problems'])
    negative=audit_inventory([row],ir,executor=lambda ir,a:{
        'status':'blocked','effect_observed':False},**args)
    assert negative['status']=='FAIL'
    assert any(x['code']=='COMBAT_ACTION_NOT_EXECUTED' for x in negative['problems'])


def test_supported_imperfect_effects_are_not_silently_dropped_from_search():
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=DEFAULT_DB)
    p=scratch_policies(ir,max_candidates=256)
    offered={r.action_id for policy in p for r in policy.rules}
    for aid in ('source_spell:339','source_spell:1062','rip:20',
                'source_spell:8936','source_spell:8938'):
        assert aid in offered
        assert from_source_rules(ir,((aid,()),)).rules[0].action_id==aid


def test_real_target_stat_and_combo_point_scenarios_execute():
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=DEFAULT_DB)
    actions={a.id:a for a in ir.actions}
    for aid in ('source_spell:770','rip:20','source_spell:339','source_spell:8938'):
        result=_runtime_exercise(ir,actions[aid],20)
        assert result['status']=='executed', (aid,result)
        assert result['effect_observed'] is True

"""P1 alignment: source legality, typed executor admission, sourced test scenario."""
from pathlib import Path
from types import SimpleNamespace as N
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from wf_gate_p1_live import _source_legality, audit_inventory, _runtime_exercise
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.policy_evolution import from_source_rules,scratch_policies


def test_druid_20_book_makes_old_rune_and_nonlearned_rows_nonlegal():
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=DEFAULT_DB)
    statuses,metadata=_source_legality(ROOT,ir,'druid',20,DEFAULT_DB)
    assert metadata['spellbook_file'].endswith('druid_spellbook_70338_level1_20.json')
    assert statuses[408024][0]=='ILLEGAL' # ungranted rune; not free L1 action
    assert statuses[16864][0]=='PASSIVE'  # Omen of Clarity; not castable
    assert statuses[5176][0]=='LEGAL'  # Wrath Rank 1 learned at L1
    assert statuses[5188][0]=='LEGAL'  # Healing Touch Rank 4 learned at L20
    assert not metadata['spellbook_missing_learned_rows']


def test_generic_ledger_does_not_excuse_missing_legal_action():
    row=lambda sid:dict(spell_id=sid,name=f'Ability {sid}',rank_hint=1,level_hint=10,
                         raw_listview_json='{}',source_url='https://x')
    a=N(id='source_spell:100',owner_actor_id='me',effects=(object(),),requirements=(),
        provenance=({'source_spell_id':100},),metadata={})
    ir=N(actor=N(id='me'),actions=(a,),modes=(),resources=())
    p=lambda aid:N(rules=(N(action_id=aid),))
    result=audit_inventory([row(100),row(200),row(300),row(400)],ir,
        parser=lambda a:{100},source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:p(rules[0][0]),
        scratch_builder=lambda ir,max_candidates:[p('source_spell:100')],
        executor=lambda ir,a:{'status':'executed','effect_observed':True},
        effect_checker=lambda e:'direct_damage',
        source_statuses={100:('LEGAL','trainer'),200:('LEGAL','trainer'),
                         300:('ILLEGAL','rune off'),400:('PASSIVE','not button')})
    assert result['status']=='FAIL'
    problems=result['problems']
    assert [x['ability'] for x in problems if x['code']=='MISSING_GAME_IR_ACTION']==[
        '200:Ability 200:rank=1:level=10']
    assert {x['source_spell_id'] for x in result['excluded_nonaction_or_inactive_rows']}=={300,400}


def test_unknown_acquisition_remains_named_problem():
    ir=N(actor=N(id='me'),actions=(),modes=(),resources=())
    result=audit_inventory([dict(spell_id=100,name='Unknown',rank_hint=1,level_hint=10,
                                 source_url='https://x',raw_listview_json='{}')],ir,
        parser=lambda a:set(),source_classifier=lambda r,raw:{'role':'ABILITY'},
        policy_builder=lambda ir,rules:None,scratch_builder=lambda ir,max_candidates:[],
        executor=lambda ir,a:None,effect_checker=lambda e:'direct_damage',
        source_statuses={100:('UNRESOLVED','not verified trainer')})
    assert 'SOURCE_ACTION_LEGALITY_UNRESOLVED' in {x['code'] for x in result['problems']}


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


def test_spellbook_path_selection_is_class_neutral():
    for cls,level in [('druid',30),('mage',30),('warrior',30)]:
        ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=DEFAULT_DB)
        ledger,info=_source_legality(ROOT,ir,cls,level,DEFAULT_DB)
        assert info['spellbook_file'] and cls in info['spellbook_file']
        assert any(status=='LEGAL' for status,_ in ledger.values())

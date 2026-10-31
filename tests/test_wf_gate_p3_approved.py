import importlib.util
from pathlib import Path
script=Path(__file__).resolve().parents[1]/'tools/wf_gate.py'
spec=importlib.util.spec_from_file_location('gate_p3',script)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


def example():
    return {'legal_equipment_slots':1,'slots_with_valid_top5':1,
        'all_top5_items_source_legal':True,'per_item_stat_contributions_present':True,
        'contextual_weights_tested_against_objective':True,
        'missing_stat_axes':[],
        'context_stat_weights':{'stamina':0.5,'intellect':0.4,'spell_power':1.1,
                                'weapon_dps':0.0,'mean_weapon_hit_damage':0.0},
        'applicable_positive_stat_axes':['stamina','intellect','spell_power'],
        'applicable_weapon_dps_axes':[],
        'mean_weapon_hit_damage_applicable':False,
        'slot_tests':[{'slot':'main_hand','source_legal_item_count':2,
                       'selected_from_db_by_ilvl':True,
                       'items':[{'item_id':7,'ilvl':21,'source_legal':True,
                                 'score':12.6,'stat_contributions':{'intellect':8.0,'spell_power':4.6},
                                 'ordinary_stat_fields':['intellect','spell_power']},
                                {'item_id':9,'ilvl':18,'source_legal':True,
                                 'score':7.7,'stat_contributions':{'stamina':2.2,'spell_power':5.5},
                                 'ordinary_stat_fields':['stamina','spell_power']}]}]}


def test_caster_druid_zero_weapon_damage_weights_are_permitted():
    assert gate._validate_p3(example(),{})==[]


def test_negative_weights_are_never_accepted():
    e=example();e['context_stat_weights']['spell_power']=-0.2
    assert 'INVALID_NEGATIVE_OR_MISSING_CONTEXT_STAT_WEIGHTS' in gate._validate_p3(e,{})


def test_missing_applicable_stat_is_not_masked_by_zero():
    e=example();e['context_stat_weights']['intellect']=0.
    assert 'APPLICABLE_STAT_WEIGHT_NOT_POSITIVE:intellect' in gate._validate_p3(e,{})


def test_weapon_damage_causality_changes_required_weights():
    e=example();e['applicable_weapon_dps_axes']=['weapon_dps']
    assert 'NO_POSITIVE_CAUSAL_WEAPON_DPS_CHANNEL' in gate._validate_p3(e,{})
    e['context_stat_weights']['weapon_dps']=0.6
    e['mean_weapon_hit_damage_applicable']=True
    assert 'CAUSAL_EQUIPPED_MEAN_HIT_WEIGHT_NOT_POSITIVE' in gate._validate_p3(e,{})
    e['context_stat_weights']['mean_weapon_hit_damage']=0.2
    assert gate._validate_p3(e,{})==[]


def test_ilvl_test_set_and_item_scoring_are_checked():
    e=example();e['slot_tests'][0]['items'].reverse()
    assert 'NOT_TOP5_ILVL_DESCENDING:main_hand' in gate._validate_p3(e,{})
    e=example();e['slot_tests'][0]['items'][0]['stat_contributions']={}
    assert any(z.startswith('ITEM_ORDINARY_STATS_IGNORED') for z in gate._validate_p3(e,{}))

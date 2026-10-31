"""WF348: sourced Druid 30 P1 admission, never an L2 or global optimum claim."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
from tools.wf348_druid30_spellbook_p1 import run as run_l30
from tools.wf335_spellbook_p1 import run as run_l20

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'evidence/wf348/druid_spellbook_70338_level1_30.json'


def source(level=30,path=PATH):
    return SourceSpellbook(path,class_key='druid',level=level,use_runes=False)


def test_build_70338_learned_table_expands_47_to_86_not_90_classic_spells():
    d=source()
    assert len(d.learned)==86
    assert len(source(20).learned)==47
    assert len(d.grants)==6
    assert len(source(20).grants)==1
    assert d.coverage([])['missing_learned_action_rows']  # fails closed without indexed ranks
    assert ('Tiger\'s Fury',24) not in d.learned


def test_rank2_insect_swarm_is_not_a_free_spell_without_level25_talent():
    d=source()
    assert d.source_decision({'spell_id':24974,'name':'Insect Swarm','source_level_hint':30})[0]=='CONDITIONAL'
    assert d.source_decision({'spell_id':5217,'name':"Tiger's Fury",'source_level_hint':24})[0]=='ILLEGAL'
    assert d.source_decision({'spell_id':5570,'name':'Insect Swarm','source_level_hint':20})[0]=='ILLEGAL'
    # Grant is represented only through an explicit source-snapshot talent entry.
    grants={g['spell_id']:g for g in d.grants}
    assert grants[5570]['learned_level']==25
    assert grants[17116]['learned_level']==30
    assert all(any(v>0 for v in g['l0_domains'].values()) for g in grants.values())


def test_verified_rank_numeric_proxy_and_context_zero_are_not_unknown_zero():
    d=source()
    r={'spell_id':6809,'name':'Maul','source_level_hint':26}
    values,zero=d.contextual_proxy(r)
    assert values['queued_swing_bonus_damage']==37 and zero is None
    r={'spell_id':6798,'name':'Bash','source_level_hint':30}
    values,zero=d.contextual_proxy(r)
    assert values['target_control_seconds']==3 and zero is None
    r={'spell_id':780,'name':'Swipe','source_level_hint':24}
    values,zero=d.contextual_proxy(r)
    assert values['damage_per_activation']==25 and zero is None
    r={'spell_id':2782,'name':'Remove Curse','source_level_hint':24}
    values,zero=d.contextual_proxy(r)
    assert not values and zero=='NO_CURSE_DEBUFFS_IN_FIXED_SOLO_100MOB_SCENARIO'


def test_spoofed_grant_derived_rank_dependency_fails_closed(tmp_path):
    d=json.loads(PATH.read_text())
    d['conditional_rank_families'][0]['talent_spell_id']=999999
    changed=tmp_path/'tampered.json';changed.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='SPELLBOOK_CONDITIONAL_FAMILY_UNBOUND_TO_TALENT_GRANT'):
        source(path=changed)
    d['conditional_rank_families'][0]['talent_spell_id']=5570
    d['expected_learned_rows']=87;changed.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='SPELLBOOK_SOURCE_ROW_COUNT_MISMATCH'):
        source(path=changed)


def test_actual_l30_staged_canonical_source_p1_certifies_all_86():
    c=run_l30()
    assert c['checkpoint']=={'class_key':'druid','level':30,'profile':'unrestricted','use_runes':False}
    assert c['PASS1'] and not c['blockers']
    assert c['legal']==78 and c['conditional']==7 and c['learned_passive']==1
    assert not c['unresolved_ids'] and not c['legal_without_rankable_l0']
    assert c['scored_legal_or_conditional']==86
    assert c['l0_source_candidate_ranking']['ranked_count']==86
    assert len(set(c['l0_source_candidate_ranking']['ranked_spell_ids']))==86
    assert c['spellbook_evidence']['missing_learned_action_rows']==[]
    assert c['l2_actions_before_after_identical']
    assert c['l0_source_candidate_ranking']['is_L2_executable_coverage'] is False
    upgraded=next(r for r in c['records'] if r.get('spell_id')==24974)
    assert upgraded['status']=='CONDITIONAL'
    assert upgraded['conditional_talent_rank_requirement']['talent_spell_id']==5570
    assert upgraded['conditional_talent_rank_requirement']['source_url'].startswith('https://')


def test_l20_accepted_p1_still_passes_with_original_47_learned_ranks():
    c=run_l20()
    assert c['PASS1'] and c['spellbook_evidence']['learned_rows_through_level']==47
    assert c['scored_legal_or_conditional']==47

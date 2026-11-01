"""WF335: source-verified spellbook admission and negative correctness tests."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
from src.game.data.forever.source_checkpoint_p1_acceptance import l0_ranked_source_candidates
from tools.wf335_spellbook_p1 import run
ROOT=Path(__file__).resolve().parents[1]
SNAP=ROOT/'evidence/wf335/druid_spellbook_70338_level1_20.json'


def test_real_druid20_p1_complete():
    result=run()
    assert result['PASS1'] is True
    assert result['legal']==45 and result['conditional']==1 and result['learned_passive']==1
    assert result['unresolved']==0 and not result['legal_without_rankable_l0']
    assert result['scored_legal_or_conditional']==47
    assert result['spellbook_evidence']['missing_learned_action_rows']==[]
    ranked=l0_ranked_source_candidates(result)
    assert ranked['ranked_count']==47
    assert ranked['source_only_candidates']==[1238122]
    assert ranked['passive_modifier_candidates']==[16864]
    assert ranked['context_zero_candidates']==[1066,6795,8946,18960,20484,437138]
    assert result['l2_actions_before_after_identical']


def test_new_feral_charge_talent_is_not_obsolete_spell():
    r=run(); byid={x['spell_id']:x for x in r['records']}
    assert byid[16979]['status']=='ILLEGAL'
    assert byid[1238122]['status']=='CONDITIONAL'
    assert byid[1238122]['talent_requirement']['prior_tree_points']==10
    assert byid[1238122]['l0_utility']['value_domains']['target_control_seconds']==4
    assert byid[1238122]['l0_utility']['value_domains']['cat_leap_behind_opportunities']==1
    assert not byid[1238122]['paid_l2_action_ids']
    assert byid[16864]['status']=='PASSIVE'
    assert byid[408024]['status']=='ILLEGAL'
    assert byid[439753]['status']=='ILLEGAL'
    assert byid[411128]['status']=='ILLEGAL'


def test_rank1_rejuvenation_has_actual_sourced_healing():
    r=run();row=next(x for x in r['records'] if x['spell_id']==774)
    assert row['status']=='LEGAL'
    assert row['l0_utility']['value_domains']['heal_or_absorb_per_activation']==32
    assert row['l0_candidate']


def test_snapshot_missing_rank_rejected(tmp_path):
    data=json.loads(SNAP.read_text());data['learned_by_level']['4'].remove('Rejuvenation')
    p=tmp_path/'tampered.json';p.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='SPELLBOOK_SOURCE_ROW_COUNT_MISMATCH'):
        SourceSpellbook(p,class_key='druid',level=20)


def test_wrong_class_level_rune_policy_rejected():
    with pytest.raises(ValueError,match='SPELLBOOK_CLASS_OR_LEVEL_MISMATCH'):
        SourceSpellbook(SNAP,class_key='mage',level=20)
    with pytest.raises(ValueError,match='SPELLBOOK_CLASS_OR_LEVEL_MISMATCH'):
        SourceSpellbook(SNAP,class_key='druid',level=30)
    with pytest.raises(ValueError,match='SPELLBOOK_RUNE_POLICY_MISMATCH'):
        SourceSpellbook(SNAP,class_key='druid',level=20,use_runes=True)


def test_exact_rank_numeric_identity_rejected(tmp_path):
    data=json.loads(SNAP.read_text())
    data['observed_rank_numeric_by_id']['774']['learned_level']=10
    p=tmp_path/'bad-rank.json';p.write_text(json.dumps(data))
    book=SourceSpellbook(p,class_key='druid',level=20)
    with pytest.raises(ValueError,match='SOURCE_NUMERIC_RANK_IDENTITY_MISMATCH'):
        book.contextual_proxy({'spell_id':774,'name':'Rejuvenation','source_level_hint':4})


def test_zero_is_justified_not_missing_proxy():
    r=run(); byid={x['spell_id']:x for x in r['records']}
    for sid in (1066,6795,8946,18960,20484,437138):
        assert byid[sid]['l0_utility']['has_explicit_no_benefit_evidence']
        assert byid[sid]['l0_candidate']
    assert not byid[2637]['l0_utility']['has_explicit_no_benefit_evidence']
    assert byid[2637]['l0_utility']['value_domains']['conditional_target_control_opportunities']==1

"""WF361: sourced Warrior L30 P1; no Warrior L30 P2/P4 claim."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
from src.game.data.forever.registry import build_game_ir_slice,generic_source_level_bounds
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.wf361_warrior_l30_p1 import run, SPELLBOOK


def test_warrior_l30_source_index_matches_54_learned_rows():
    s=SourceSpellbook(SPELLBOOK,class_key='warrior',level=30,use_runes=False)
    assert len(s.learned)==54
    assert len(s.grants)==6
    assert s.learned[('Tactical Mastery',14)]=='PASSIVE'
    assert s.learned[('Slam',20)]=='LEARNED'
    assert s.learned[('Slam',30)]=='LEARNED'
    assert ('Whirlwind',36) not in s.learned
    assert ('Bloodthirst',40) not in s.learned
    assert ('Berserker Rage',30) in s.learned
    assert generic_source_level_bounds('warrior')==(10,30)


def test_talent_grants_remain_conditional_not_free_spells():
    s=SourceSpellbook(SPELLBOOK,class_key='warrior',level=30,use_runes=False)
    g={x['name']:x for x in s.grants}
    assert set(g)=={'Last Stand','Piercing Howl','Spearing Strike','Concussion Blow','Death Wish','Sweeping Strikes'}
    assert g['Spearing Strike']['talent_tree']=='Arms'
    assert g['Death Wish']['prior_tree_points']==20
    assert g['Concussion Blow']['prior_tree_points']==20
    assert all(x['does_not_prove_paid_L2'] for x in g.values())
    assert all(x['source_url'].startswith('https://www.wowhead.com/forever/') for x in g.values())


def test_warrior_l30_full_source_rank_l0_and_unchanged_paid_envelope():
    p=run()
    assert p['checkpoint']=={'class_key':'warrior','level':30,'profile':'unrestricted','use_runes':False}
    assert p['PASS1'] and not p['blockers']
    assert p['legal']==47 and p['conditional']==6 and p['learned_passive']==1
    assert p['scored_legal_or_conditional']==54
    assert not p['unresolved_ids'] and not p['legal_without_rankable_l0']
    assert p['spellbook_evidence']['learned_rows_through_level']==54
    assert not p['spellbook_evidence']['missing_learned_action_rows']
    assert p['l0_source_candidate_ranking']['ranked_count']==54
    assert p['l2_actions_before_after_identical']
    assert p['ir_action_count']==5 and p['ir_mode_count']==2
    assert p['uncertainty'].startswith('L0-only')
    b=next(x for x in p['records'] if x.get('name')=='Battle Shout' and x['legal_level_hint']==22)
    assert b['l0_utility']['value_domains']['caster_attack_power_increase']==33
    sweep=next(x for x in p['records'] if x.get('name')=='Sweeping Strikes')
    assert sweep['status']=='CONDITIONAL'
    assert sweep['l0_utility']['explicit_context_zero_reason']=='SOLO_SINGLE_MOB_NO_SECONDARY_TARGET'


def test_fail_closed_on_tampered_source_rank_and_source_index(tmp_path, monkeypatch):
    data=json.loads(SPELLBOOK.read_text())
    data['expected_learned_rows']=55
    path=tmp_path/'wrong_count.json';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='SPELLBOOK_SOURCE_ROW_COUNT_MISMATCH'):
        SourceSpellbook(path,class_key='warrior',level=30)
    data['expected_learned_rows']=54
    data['source_index_sha256']='0'*64
    path.write_text(json.dumps(data))
    # Generic checkpoint P1 checks the pinned index hash against live SQLite.
    import tools.wf361_warrior_l30_p1 as worker
    monkeypatch.setattr(worker,'SPELLBOOK',path)
    with pytest.raises(ValueError,match='SPELLBOOK_SOURCE_INDEX_SNAPSHOT_MISMATCH'):
        worker.run()
    data['source_index_sha256']=json.loads(SPELLBOOK.read_text())['source_index_sha256']
    data['contextual_proxy_source_urls_by_name'].pop('Battle Stance')
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='SOURCE_L0_CONTEXT_PROXY_MISSING_PROVENANCE'):
        SourceSpellbook(path,class_key='warrior',level=30)


def test_existing_warrior_l10_l20_source_provider_regression():
    for level in (10,20,30):
        ir=build_game_ir_slice(class_key='warrior',level=level,ability_db_path=DEFAULT_DB,use_runes=False)
        assert ir is not None and ir.actor.metadata['level']==level
        assert ir.actor.metadata['class_key']=='warrior'
        assert any(a.family_key=='bloodrage' for a in ir.actions)

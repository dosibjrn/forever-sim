"""Generic source spellbook reconciliation, exercised on Mage L30 source anomalies."""
from __future__ import annotations
import json
import pytest
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
from src.game.data.forever.source_checkpoint_p1_acceptance import CheckpointP1, evaluate_p1


def _evidence(tmp_path):
    d = {
        'schema': 'forever_spellbook_level_ranks_v1',
        'class_key': 'mage', 'level_range_covered': [1, 30], 'runes_enabled': False,
        'build': '1.60.1.70338', 'source_url': 'https://foreverdb.net/guide/leveling-mage',
        'source_kind': 'beta_client_spellbook', 'source_index_sha256': 'fixture-index',
        'learned_by_level': {'6': ['Study'], '25': ['Ice Block'], '30': ['Fire Blast']},
        'expected_learned_rows': 3, 'non_cast_passives': [],
        'conditional_talent_actions': [{
            'spell_id': 11958, 'name': 'Ice Block', 'learned_level': 25,
            'source_index_level_hint_override': 4,
            'talent_tree': 'Frost', 'prior_tree_points': 15, 'talent_rank': 1,
            'source_url': 'https://www.wowhead.com/forever/spell=11958/ice-block',
            'l0_domains': {'immunity_duration_seconds': 10.0}}],
        'conditional_rank_families': [],
        'obsolete_or_ungranted_exact_spell_ids': {},
        'contextual_numeric_proxies_by_name': {'Fire Blast': {'damage_per_activation': 163.0}},
        'contextual_zero_when_solo_land_mob_no_allies_or_debuffs': {},
        'learned_exact_spell_ids_by_level': {'30': {'Fire Blast': 8412}},
        'source_only_learned_actions': [{
            'spell_id': 1302508, 'name': 'Study', 'learned_level': 6,
            'source_url': 'https://www.wowhead.com/forever/spell=1302508/study',
            'contextual_zero': 'NO_LIBRARY_OR_SCROLL_RESEARCH_IN_100_MOB_COMBAT'}],
    }
    path=tmp_path/'spellbook.json';path.write_text(json.dumps(d))
    return path


def _row(spell_id,name,level):
    return {'spell_id': spell_id, 'name': name, 'source_level_hint': level,
        'source_row_sha256': f'row-{spell_id}', 'source_url': 'https://wowhead.com/forever',
        'eligibility': 'POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED',
        'source_acquisition_evidence_status': 'NO_EVIDENCE',
        'index_features': {}, 'source_text_context_evidence': {},
        'ir_proxies': [], 'paid_search_action_ids': [], 'ir_action_ids': []}


def test_source_spellbook_exact_rank_identity_blocks_same_name_level_alternate(tmp_path):
    book=SourceSpellbook(_evidence(tmp_path),class_key='mage',level=30)
    assert book.source_decision(_row(8412,'Fire Blast',30))[0]=='LEGAL'
    assert book.source_decision(_row(400620,'Fire Blast',30))[0]=='ILLEGAL'


def test_source_spellbook_talent_grant_is_conditional_despite_stale_index_level(tmp_path):
    book=SourceSpellbook(_evidence(tmp_path),class_key='mage',level=30)
    assert book.source_decision(_row(11958,'Ice Block',4))[0]=='CONDITIONAL'
    with pytest.raises(ValueError,match='TALENT_GRANT_EXACT_ID_NAME_MISMATCH'):
        book.source_decision(_row(11958,'Other Spell',4))
    earlier=SourceSpellbook(_evidence(tmp_path),class_key='mage',level=20)
    assert earlier.source_decision(_row(11958,'Ice Block',4))[0]=='ILLEGAL'


def test_p1_keeps_indexed_talent_grant_and_source_only_learned_action(tmp_path):
    path=_evidence(tmp_path)
    frontier={'checkpoint':{'class_key':'mage','level':30,'profile':'unrestricted'},
        'use_runes':False, 'source_index_sha256':'fixture-index',
        'profile_constraint_applied':True,
        'records':[_row(11958,'Ice Block',4),_row(8412,'Fire Blast',30)],
        'excluded_above_level':[]}
    p1=evaluate_p1(frontier,DEFAULT_DB,CheckpointP1('mage',30),spellbook_path=path)
    assert p1['PASS1'],p1['blockers']
    assert (p1['legal'],p1['conditional'],p1['unresolved'])==(2,1,0)
    assert p1['scored_legal_or_conditional']==3
    indexed=next(r for r in p1['records'] if r['spell_id']==11958)
    assert indexed['status']=='CONDITIONAL'
    assert indexed['talent_requirement']['prior_tree_points']==15
    assert indexed['l0_utility']['value_domains']['immunity_duration_seconds']==10
    source_only=next(r for r in p1['records'] if r['spell_id']==1302508)
    assert source_only['status']=='LEGAL' and source_only['source_only_not_yet_in_IR']
    assert source_only['l0_utility']['explicit_context_zero_reason']
    assert p1['spellbook_evidence']['missing_learned_action_rows']==[]


def test_talent_grant_rejects_unproven_stale_source_level(tmp_path):
    path=_evidence(tmp_path)
    d=json.loads(path.read_text())
    del d['conditional_talent_actions'][0]['source_index_level_hint_override']
    path.write_text(json.dumps(d))
    book=SourceSpellbook(path,class_key='mage',level=30)
    assert book.source_decision(_row(11958,'Ice Block',4))[0]=='ILLEGAL'


@pytest.mark.parametrize('kind', ['source_only','talent_grant'])
def test_source_spellbook_rejects_conflicting_exact_identity_tables(tmp_path,kind):
    path=_evidence(tmp_path)
    d=json.loads(path.read_text())
    if kind=='source_only':
        d['learned_exact_spell_ids_by_level']['6']={'Study':1302508}
        d['source_only_learned_actions'][0]['spell_id']=1302509
    else:
        d['learned_exact_spell_ids_by_level']['25']={'Ice Block':11958}
        d['conditional_talent_actions'][0]['spell_id']=11959
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='EXACT_SOURCE_ID_MISMATCH'):
        SourceSpellbook(path,class_key='mage',level=30)

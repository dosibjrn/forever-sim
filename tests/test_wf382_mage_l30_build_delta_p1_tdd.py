"""WF382: 70338 -> 70374 Mage P1 must be source-proven, never relabelled."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_spellbook import SourceSpellbook
from src.game.data.forever.source_checkpoint_p1_acceptance import CheckpointP1, evaluate_p1
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB

ROOT=Path(__file__).resolve().parents[1]
BOOK=ROOT/'evidence/wf377/mage_spellbook_70338_level1_30.json'
DELTA=ROOT/'evidence/wf382/mage_70338_to_70374_spell_delta.json'


def _frontier():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    return ir, action_frontier(ir,class_key='mage',level=30,db_path=DEFAULT_DB,use_runes=False)


def test_source_delta_proves_no_mage_action_or_talent_changes():
    book=SourceSpellbook(BOOK,class_key='mage',level=30)
    from src.game.data.forever.source_build_delta import validate_source_build_bridge
    bridge=validate_source_build_bridge(DELTA,book,class_key='mage',target_build='1.60.1.70374')
    assert bridge['source_build']=='1.60.1.70338'
    assert bridge['effective_build']=='1.60.1.70374'
    assert bridge['new_spells_other']==1
    assert bridge['new_spells_class']==0
    assert bridge['unchanged_source_sha256']==book.sha256


def test_p1_is_revalidated_on_70374_without_copying_source_or_adding_spells():
    ir,frontier=_frontier()
    p1=evaluate_p1(frontier,DEFAULT_DB,CheckpointP1('mage',30),ir=ir,
                   spellbook_path=BOOK,target_source_build='1.60.1.70374',
                   source_delta_path=DELTA)
    assert p1['PASS1'],p1['blockers']
    assert p1['source_build']=='1.60.1.70374'
    assert p1['source_spellbook_original_build']=='1.60.1.70338'
    assert p1['scored_legal_or_conditional']==p1['legal']+p1['conditional']+p1['learned_passive']==80
    assert not p1['unresolved_ids'] and not p1['legal_without_rankable_l0']
    assert p1['source_build_bridge']['effective_build']=='1.60.1.70374'


def test_p1_does_not_accept_newer_build_without_bridge():
    ir,frontier=_frontier()
    with pytest.raises(ValueError,match='SOURCE_BUILD_BRIDGE_REQUIRED'):
        evaluate_p1(frontier,DEFAULT_DB,CheckpointP1('mage',30),ir=ir,
                    spellbook_path=BOOK,target_source_build='1.60.1.70374')


@pytest.mark.parametrize('field,value,expected',[ 
    ('changed_spell_records',1,'SOURCE_DELTA_CLASS_SPELL_CHANGE'),
    ('removed_spell_records',1,'SOURCE_DELTA_CLASS_SPELL_CHANGE'),
    ('new_spells_by_category',{'mage':1},'SOURCE_DELTA_CLASS_SPELL_CHANGE'),
    ('changed_talent_records',1,'SOURCE_DELTA_TALENT_CHANGE'),
    ('unchanged_source_sha256','0'*64,'SOURCE_DELTA_SPELLBOOK_SHA_MISMATCH'),
    ('from_build','1.60.1.70334','SOURCE_DELTA_BUILD_MISMATCH'),
])
def test_delta_mutation_fails_closed(tmp_path,field,value,expected):
    data=json.loads(DELTA.read_text())
    data[field]=value
    path=tmp_path/'mutated.json'
    path.write_text(json.dumps(data))
    book=SourceSpellbook(BOOK,class_key='mage',level=30)
    from src.game.data.forever.source_build_delta import validate_source_build_bridge
    with pytest.raises(ValueError,match=expected):
        validate_source_build_bridge(path,book,class_key='mage',target_build='1.60.1.70374')


def test_p2_current_talents_and_source_scoped_spellbook_share_70374(tmp_path):
    from tools.wf381_stage_mage_talent_positions import stage
    from src.game.data.forever.source_checkpoint_p2 import evaluate_p2,P2Checkpoint
    db=tmp_path/'staged.sqlite'
    stage(target=db)
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=db,use_runes=False)
    p2=evaluate_p2(ir,P2Checkpoint('mage',30,source_build='1.60.1.70374'),
                   spellbook_path=BOOK,source_delta_path=DELTA)
    assert p2['p2_pass'],p2['blocked']
    assert p2['l0_scored_reachable_rank_count']==p2['known_reachable_rank_count']==121
    assert p2['spellbook_scoped_l0_completeness_checked']
    assert p2['source_build_bridge']['effective_build']=='1.60.1.70374'


def test_p2_does_not_silently_mix_spellbook_versions(tmp_path):
    from tools.wf381_stage_mage_talent_positions import stage
    from src.game.data.forever.source_checkpoint_p2 import evaluate_p2,P2Checkpoint
    db=tmp_path/'staged.sqlite'
    stage(target=db)
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=db,use_runes=False)
    with pytest.raises(ValueError,match='P2_SPELLBOOK_SOURCE_BUILD_MISMATCH'):
        evaluate_p2(ir,P2Checkpoint('mage',30,source_build='1.60.1.70374'),spellbook_path=BOOK)

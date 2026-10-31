"""Mage L30 source spellbook: the real 70338 client legal action denominator."""
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_checkpoint_p1_acceptance import CheckpointP1, evaluate_p1, l0_ranked_source_candidates

EVIDENCE=Path(__file__).resolve().parents[1]/'evidence/wf377/mage_spellbook_70338_level1_30.json'


def test_mage_l30_source_bound_p1_all_legal_actions_are_scored():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DEFAULT_DB,use_runes=False)
    frontier=action_frontier(ir,class_key='mage',level=30,db_path=DEFAULT_DB,use_runes=False)
    p1=evaluate_p1(frontier,DEFAULT_DB,CheckpointP1('mage',30),ir=ir,spellbook_path=EVIDENCE)
    assert p1['PASS1'],p1['blockers']
    assert not p1['unresolved_ids'] and not p1['legal_without_rankable_l0']
    assert p1['scored_legal_or_conditional']==p1['legal']+p1['conditional']+p1['learned_passive']
    ids={r['spell_id']:r for r in p1['records']}
    assert ids[400620]['status']=='ILLEGAL'  # same-level SoD alternate, not Forever Fire Blast R4
    for sid in (400574,1312002,11958,12472,12043,11113):
        assert ids[sid]['status']=='CONDITIONAL',(sid,ids[sid]['status'])
        assert ids[sid]['l0_candidate']
        assert ids[sid]['talent_requirement']['prior_tree_points']>=10
    for sid in (1296017,1302508):
        assert ids[sid]['status']=='LEGAL' and ids[sid]['source_only_not_yet_in_IR']
        assert ids[sid]['l0_candidate']
    assert len(l0_ranked_source_candidates(p1)['ranked_spell_ids'])==p1['scored_legal_or_conditional']

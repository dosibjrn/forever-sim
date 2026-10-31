import json,sqlite3,shutil
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2,evaluate_p2_allocation_l0
from src.game.data.forever.source_checkpoint_talent_stage import apply_staged_talent_catalogue
from tools.wf350_druid30_p2_acceptance import ROOT,DB,OBS,SPELL

def test_staged_druid30_source_complete():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    assert len(ir.talents)==52
    assert 'natural_instinct' in {t.id for t in ir.talents}
    assert 'predatory_instincts' not in {t.id for t in ir.talents}
    p=evaluate_p2(ir,P2Checkpoint('druid',30),source_observations_path=OBS,spellbook_path=SPELL)
    assert p['p2_pass'] and p['known_reachable_rank_count']==117
    assert p['l0_scored_reachable_rank_count']==117
    assert not p['blocked'] and not p['source_rank_mismatches'] and not p['unknown_position_families']
    for r in p['rank_rows']:
        assert evaluate_p2_allocation_l0(p,ir,r['witness'],P2Checkpoint('druid',30))['rankable']

def test_staged_source_ranks_are_not_fake_runtime_modifiers():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    lookup={t.id:t for t in ir.talents}
    for key,cap in [('improved_starfire',5),('vengeance',5),
                    ('blood_frenzy',2),('natural_instinct',2)]:
        t=lookup[key]
        assert t.max_rank==cap and len(t.ranks)==cap
        assert t.metadata['checkpoint_source_l2_gap']
        assert all(not rank.modifiers for rank in t.ranks)
        assert all('checkpoint_source_l0' in rank.provenance for rank in t.ranks)
    # Newly sourced conditional and form-AP effects now have executable ranks.
    # This is a deliberate data/engine advance, not synthetic fallback.
    for key,cap in [('predatory_strikes',3),('rend_and_tear',5)]:
        t=lookup[key]
        assert t.max_rank==cap and not t.metadata['checkpoint_source_l2_gap']
        assert all(r.modifiers and r.provenance['checkpoint_source_l0']['executable']
                   for r in t.ranks)

def test_default_canonical_unmodified_and_l20_not_regressed():
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    with sqlite3.connect(DEFAULT_DB) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_talent_source_catalogue'").fetchone()
    ir=build_game_ir_slice(class_key='druid',level=20)
    p=evaluate_p2(ir,P2Checkpoint('druid',20),
        source_observations_path=ROOT/'evidence/wf336/druid_l20_talent_rank_observations_70338.json',
        spellbook_path=ROOT/'evidence/wf335/druid_spellbook_70338_level1_20.json')
    assert p['p2_pass'] and p['known_reachable_rank_count']==69

def test_stage_source_tamper_fail_closed(tmp_path):
    target=tmp_path/'stage.sqlite';shutil.copyfile(DB,target)
    with sqlite3.connect(target) as db:
        db.execute("UPDATE checkpoint_talent_source_catalogue SET source_sha256='bad'")
    with pytest.raises(ValueError,match='STAGED_TALENT_SOURCE_HASH_MISMATCH'):
        build_game_ir_slice(class_key='druid',level=30,ability_db_path=target)

def test_stage_only_applies_to_eligible_level():
    ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=DB)
    assert 'predatory_instincts' in {t.id for t in ir.talents}
    assert 'natural_instinct' not in {t.id for t in ir.talents}


def test_l30_p3_non_equippable_empty_slot_not_in_denominator():
    from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
    certificate=checkpoint_item_l0(class_key='druid',level=30)
    assert certificate['legal_item_count']==1974
    assert certificate['l0_assessed_count']==1974
    assert len(certificate['slot_frontiers'])==18
    assert 5514 not in {r['item_id'] for r in certificate['source_items']}

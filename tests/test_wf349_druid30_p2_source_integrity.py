"""L30 source rank completeness, prerequisites and prior-L20 regression guard."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import (
    P2Checkpoint, evaluate_p2, evaluate_p2_allocation_l0,
    check_structural_allocation)
from src.game.data.forever.source_checkpoint_p2_optimizer import rank_opportunity_frontier

SOURCE=Path('evidence/wf349/druid_l30_talent_rank_observations_70338.json')
SPELLBOOK=Path('evidence/wf348/druid_spellbook_70338_level1_30.json')

@pytest.fixture(scope='module')
def audit():
    ir=build_game_ir_slice(class_key='druid',level=30)
    cp=P2Checkpoint('druid',30)
    result=evaluate_p2(ir,cp,source_observations_path=SOURCE,spellbook_path=SPELLBOOK)
    return ir,cp,result


def test_source_row_witnesses_unlock_new_tiers_and_score_nonzero(audit):
    ir,cp,cert=audit
    assert cert['point_budget']==21
    assert cert['known_reachable_rank_count']==105
    assert cert['l0_scored_reachable_rank_count']==105
    assert all(r['l0_effects'] for r in cert['rank_rows'])
    for row in cert['rank_rows']:
        assert check_structural_allocation(ir,row['witness'],cp,
            override_rows=cert['source_allocation_rules'])
    assert {r['talent_id'] for r in cert['rank_rows']} >= {
        'eclipse','natures_grace','insect_swarm','primal_bite','swiftmend',
        'blood_frenzy','improved_shifting_power','living_spirit'}


def test_correct_source_rank_gaps_block_acceptance(audit):
    ir,cp,cert=audit
    assert cert['p2_pass'] is False
    assert len(cert['source_rank_mismatches'])==8
    missing={(x['talent_id'],r) for x in cert['source_rank_mismatches']
             for r in x['possibly_missing_source_ranks_at_checkpoint']}
    assert len(missing)==11
    assert ('vengeance',5) in missing
    assert ('improved_starfire',5) in missing
    assert ('blood_frenzy',2) in missing
    assert ('predatory_strikes',3) in missing
    assert all(not x['possibly_missing_source_ranks_at_checkpoint']
               for x in cert['source_rank_mismatches']
               if x['talent_id'] in {'overgrowth','living_spirit','improved_tranquility','improved_shifting_power'})
    with pytest.raises(ValueError,match='UNVERIFIED_CHECKPOINT'):
        rank_opportunity_frontier(cert,class_key='druid',level=30)


def test_renamed_source_talent_not_assumed_stale_legacy_id(audit):
    _,_,cert=audit
    assert not any(x['talent_id']=='predatory_instincts' for x in cert['rank_rows'])
    assert any(x['talent_id']=='predatory_instincts' and
        x['reason']=='SOURCE_TALENT_IDENTITY_SUPERSEDED_REQUIRES_CANONICAL_REINGEST'
        for x in cert['unknown_position_families'])


def test_source_prerequisites_are_applied_to_allocations(audit):
    ir,cp,cert=audit
    for selection,missing in [
        ({'ferocity':5,'heart_of_the_wild':5,'savage_fury':1,'primal_bite':1},'primal_bite'),
        ({'ferocity':5,'heart_of_the_wild':5,'shredding_attacks':1,'shifting_power':1},'shifting_power'),
        ({'furor':5,'natures_focus':5,'naturalist':1,'natures_swiftness':1},'natures_swiftness')]:
        with pytest.raises(ValueError):
            check_structural_allocation(ir,selection,cp,
                override_rows=cert['source_allocation_rules'])
        with pytest.raises(ValueError):
            evaluate_p2_allocation_l0(cert,ir,selection,cp)
    by={r['talent_id']:r for r in cert['rank_rows']}
    for tid in ['primal_bite','shifting_power','blood_frenzy','natures_swiftness']:
        candidate=by[tid]['witness']
        prereq=cert['source_allocation_rules'][tid]['prerequisite']
        assert candidate[prereq['talent_id']]>=prereq['required_rank']
        assert evaluate_p2_allocation_l0(cert,ir,candidate,cp)['rankable']


def test_level20_existing_p2_still_accepted_and_69_ranks(audit):
    ir=build_game_ir_slice(class_key='druid',level=20)
    cp=P2Checkpoint('druid',20)
    result=evaluate_p2(ir,cp,
         source_observations_path='evidence/wf336/druid_l20_talent_rank_observations_70338.json',
         spellbook_path='evidence/wf335/druid_spellbook_70338_level1_20.json')
    assert result['p2_pass'] and result['known_reachable_rank_count']==69


def test_source_rank_values_cannot_be_truncated_or_fake_build(audit,tmp_path):
    ir,cp,_=audit
    for corruption in ['rank_truncated','wrong_build','wrong_tree','missing_prereq_rank']:
        raw=json.loads(SOURCE.read_text())
        target=next(x for x in raw['observations'] if x['talent_id']=='vengeance')
        if corruption=='rank_truncated':target['rank_values'].pop()
        elif corruption=='wrong_build':raw['source_build']='1.60.1.00000'
        elif corruption=='wrong_tree':target['tree_key']='feral'
        else:target['prerequisite']['required_rank']=None
        path=tmp_path/f'{corruption}.json'
        path.write_text(json.dumps(raw))
        if corruption=='missing_prereq_rank':
            with pytest.raises((TypeError,ValueError)):
                evaluate_p2(ir,cp,source_observations_path=path)
        else:
            with pytest.raises(ValueError):
                evaluate_p2(ir,cp,source_observations_path=path)

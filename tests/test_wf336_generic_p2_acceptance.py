"""Rank-level P2 audit for Druid L20 and fail-closed generic edge cases."""
from pathlib import Path
import json
from copy import deepcopy

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import (
    P2Checkpoint, evaluate_p2, evaluate_p2_allocation_l0,
    check_structural_allocation)

SOURCE=Path('evidence/wf336/druid_l20_talent_rank_observations_70338.json')

@pytest.fixture(scope='module')
def sample():
    cp=P2Checkpoint('druid',20)
    ir=build_game_ir_slice(class_key='druid',level=20)
    audit=evaluate_p2(ir,cp,source_observations_path=SOURCE)
    return cp,ir,audit


def test_all_ranks_covered_current_build_no_out_of_level_family_included(sample):
    cp,ir,x=sample
    assert x['p2_pass']
    assert x['point_budget']==11
    assert x['known_reachable_rank_count']==69
    assert x['l0_scored_reachable_rank_count']==69
    assert x['source_only_l0_rank_count']==12
    assert not x['unknown_position_families'] and not x['blocked']
    assert len({r['talent_id'] for r in x['rank_rows']})==26
    for row in x['rank_rows']:
        assert sum(row['witness'].values())<=11
        assert row['l0_effects']
        assert check_structural_allocation(ir,row['witness'],cp)
        assert evaluate_p2_allocation_l0(x,ir,row['witness'],cp)['rankable']


def test_new_l0_coverage_includes_bear_charge_and_passive_cast_pushback(sample):
    cp,ir,x=sample
    by={(r['talent_id'],r['rank']):r for r in x['rank_rows']}
    assert by['natures_focus',5]['l0_effects'][0]['sourced_value']==0.70
    assert by['brutal_impact',2]['l0_effects'][0]['sourced_value']==1.
    assert by['subtlety',3]['l0_effects'][0]['sourced_value']==0.3
    assert by['shredding_attacks',1]['l0_effects'][0]['sourced_value']==6.
    assert by['feral_charge',1]['l0_effects'][0]['sourced_value']==4.
    # A source-scored talent is not falsely marked executable at L2.
    assert all(not by[tid,rank]['l2_supported'] for tid,rank in
        [('natures_focus',5),('brutal_impact',2),('subtlety',3),('shredding_attacks',1),('feral_charge',1)])
    assert by['feral_charge',1]['witness']['feral_charge']==1
    assert sum(by['feral_charge',1]['witness'].values())==11


def test_joint_l0_composition_cross_tree_and_tier_gates(sample):
    cp,ir,x=sample
    for selection in [
        {'ferocity':5,'heart_of_the_wild':5,'feral_charge':1},
        {'natures_focus':5,'naturalist':5,'subtlety':1},
        {'improved_wrath':5,'genesis':5,'natures_splendor':1},
        {'ferocity':5,'heart_of_the_wild':5,'shredding_attacks':1},
        {'furor':5,'natures_focus':5,'improved_rejuvenation':1}]:
        # Last selection is *not* legal: the final talent is in row 4.
        try:check_structural_allocation(ir,selection,cp)
        except ValueError:
            assert selection.get('improved_rejuvenation')==1
            continue
        r=evaluate_p2_allocation_l0(x,ir,selection,cp)
        assert r['point_spend']==11 and not r['scalar_s_per_mob_predicted']
        assert len(r['effects'])==3
    for bad in [{'feral_charge':1},{'ferocity':5,'feral_charge':1},
                {'ferocity':5,'heart_of_the_wild':5,'feral_charge':2},
                {'ferocity':5,'heart_of_the_wild':5,'feral_charge':1,'brutal_impact':1}]:
        with pytest.raises(ValueError):check_structural_allocation(ir,bad,cp)


def test_unknown_row_does_not_turn_into_illegal_or_legal(sample):
    cp,ir,x=sample
    no_source=evaluate_p2(ir,cp)
    assert not no_source['p2_pass']
    assert len(no_source['unknown_position_families'])==sum(t.metadata.get('row') is None for t in ir.talents)
    assert len(no_source['blocked'])==12


def test_tampered_source_rejected_and_wrong_build_rejected(sample,tmp_path):
    cp,ir,_=sample
    src=json.loads(SOURCE.read_text())
    for change in ['missing_rank','bad_tier','wrong_tree','duplicate','bad_build','wrong_source_build']:
        trial=deepcopy(src)
        if change=='missing_rank':trial['observations'][0]['rank_values'].pop()
        elif change=='bad_tier':trial['observations'][0]['row']=1
        elif change=='wrong_tree':trial['observations'][0]['tree_key']='feral'
        elif change=='duplicate':trial['observations'].append(deepcopy(trial['observations'][0]))
        elif change=='bad_build':trial['source_build']='1.60.1.70000'
        elif change=='wrong_source_build':trial['observed_unreachable_talent_positions'][0]['client_build']='1.60.1.70000'
        file=tmp_path/f'{change}.json';file.write_text(json.dumps(trial))
        with pytest.raises(ValueError):evaluate_p2(ir,cp,source_observations_path=file)


def test_higher_tier_alias_is_not_assumed_l20_legal(sample):
    cp,ir,x=sample
    assert not any(r['talent_id']=='predatory_instincts' for r in x['rank_rows'])
    positions=json.loads(SOURCE.read_text())['observed_unreachable_talent_positions']
    alias=next(p for p in positions if p['indexed_talent_id']=='predatory_instincts')
    assert alias['identity_status']=='STALE_OLD_TALENT_NAME_REPLACED_WITH_NATURAL_INSTINCT'
    assert alias['min_level_without_legacy']>20


def test_generic_checkpoint_mismatch_and_profile_fails_closed(sample):
    cp,ir,x=sample
    with pytest.raises(ValueError,match='P2_CHECKPOINT_IR_MISMATCH'):
        evaluate_p2(ir,P2Checkpoint('shaman',20))
    restricted=P2Checkpoint('druid',20,'balance')
    audit=evaluate_p2(ir,restricted,source_observations_path=SOURCE)
    assert not audit['p2_pass']

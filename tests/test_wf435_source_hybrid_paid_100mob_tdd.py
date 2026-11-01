"""WF435: source-legal mixed-stat full gear builds must be paid, not imagined."""
from functools import lru_cache
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.v2.source_bounded_joint_frontier import source_cold_start_stage
from src.v2.source_persistent_slot_search import _source_stat_package_proposals
from src.rulesets.forever.items.runtime_selection import available_items, item_scoring_vector
from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids

DB = Path(__file__).resolve().parents[1] / 'data/forever/staged_druid_l30_talents_70338.sqlite'
TALENTS = {'genesis':5,'improved_wrath':5,'improved_moonfire':2,'natures_majesty':2,
           'moonglow':3,'natures_reach':2,'improved_entangling_roots':1,
           'eclipse':3,'ferocity':3}

@lru_cache(maxsize=1)
def _fixture():
    ir = compile_talent_runtime(build_game_ir_slice(
        class_key='druid', level=30, ability_db_path=DB))[0]
    stage = source_cold_start_stage(class_key='druid', level=30,
        source_ir=ir, gear_role='druid_feral')
    by_id = {int(item.item_id):item for item in available_items(
        'druid',30,required_level_policy='observed')}
    return ir,stage,by_id


def _stat_total(base, swaps, by_id, axis):
    return sum(float(item_scoring_vector(by_id[int(swaps.get(slot, entry['item_id']))]).get(axis,0.) or 0.)
               for slot,entry in base['slots'].items())


def _packages():
    _,stage,by_id=_fixture()
    base=stage['gear_policy_result']['winner']['gear']
    packages,ledger=_source_stat_package_proposals(class_key='druid',level=30,
        base=base,max_packages=4)
    return base,packages,ledger,by_id


def test_source_mixed_package_is_real_and_not_a_pure_axis_label():
    base,packages,ledger,by_id=_packages()
    d=dict(packages)
    assert 'spell_power' in d and 'crit' in d
    hybrids={name:swaps for name,swaps in packages if '+' in name}
    assert 'spell_power+crit' in hybrids, packages
    assert ledger['mixed_stat_candidates']>=1
    for name,swaps in hybrids.items():
        assert len(swaps)>1
        ids=[int(swaps.get(slot,entry['item_id'])) for slot,entry in base['slots'].items()]
        validate_equipped_item_ids(ids)
        assert len(ids)==len(base['slots'])
        left,right=name.split('+')
        for axis in (left,right):
            assert _stat_total(base,swaps,by_id,axis)>_stat_total(base,{},by_id,axis)
        assert tuple(sorted(swaps.items())) not in {
            tuple(sorted(d[axis].items())) for axis in ('spell_power','crit')}


def test_tight_budget_still_contains_a_paid_mixed_source_candidate():
    base,packages,ledger,by_id=_packages()
    assert len(packages)==4
    assert len({tuple(sorted(swaps.items())) for _,swaps in packages})==4
    assert sum('+' in name for name,_ in packages)>=1
    assert ledger['historical_winner_as_seed'] is False
    empty,_=_source_stat_package_proposals(class_key='druid',level=30,
        base=base,max_packages=0)
    assert empty==[]


def test_real_source_mixed_gear_reaches_100mob_with_paid_recovery():
    from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    from src.v2.source_bounded_joint_frontier import _recovery_variants
    ir,stage,_=_fixture()
    base,packages,_,_=_packages()
    hybrids=[(name,swaps) for name,swaps in packages if name=='spell_power+crit']
    assert hybrids, 'NO_SOURCE_HYBRID_IN_COLD_GEAR_FRONTIER'
    name,swaps=hybrids[0]
    variant=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=swaps)
    candidate=prepare_candidate(class_key='druid',level=30,stage=variant,
        source_ir=ir,allocation_override=TALENTS,bonus_talent_points=5,
        allow_partial_gear_stats=True)
    rec=dict(_recovery_variants(ir,stage,2))['always']
    r=evaluate_persistent_candidate(candidate,level=30,mobs=100,
        max_total_events=200000,max_wall_s=30,max_cpu_s=30,recovery_policy=rec)
    assert r['status']=='COMPLETE',r
    assert r['count']==100
    assert r['events']>100
    assert r['mean_s_per_mob']>0


def test_hybrid_gets_reserved_early_paid_coordinate_after_source_unlocks():
    from src.v2.source_bounded_joint_frontier import (
        _source_witness_first_coordinates,_source_priority_witness_probes,
        _source_talent_policy_variants,source_joint_policy_frontier,
        bounded_full_point_talent_frontier)
    ir,stage,_=_fixture()
    base,packages,_,_=_packages()
    talents,_=bounded_full_point_talent_frontier(ir,level=30,
        bonus_talent_points=5,max_frontier=64)
    policies=source_joint_policy_frontier(ir,stage,max_policies=4,include_mode_cycles=True)
    variants,_,_=_source_talent_policy_variants(ir,talents,stage,policies,
        level=30,bonus_talent_points=5)
    gear_stages=[('incumbent',stage)] + [('source_stat_package:'+name,None)
        for name,_ in packages]
    priority=_source_priority_witness_probes(variants)
    coords=_source_witness_first_coordinates(
        (len(talents),len(gear_stages),len(policies),2),variants,
        'diagonal',(),gear_stages=gear_stages)
    first=[next(coords) for _ in range(len(priority)+3)]
    # Source-unlock and modified-action probes must retain their original order.
    assert first[:len(priority)]==list(dict.fromkeys(priority))
    hybrid_i=next(i for i,(name,_) in enumerate(gear_stages) if '+' in name)
    assert (0,hybrid_i,0,0) in first
    assert len(first)==len(set(first))


def test_full_eight_move_quota_preserves_melee_axes_plus_hybrid():
    from src.v2.source_bounded_joint_frontier import _joint_gear_move_quotas
    stat,weapon,slot=_joint_gear_move_quotas(8)
    assert (stat,weapon,slot)==(5,1,2)
    assert stat+weapon+slot==8
    base,_,_,_=_packages()
    packages,_=_source_stat_package_proposals(class_key='druid',level=30,
        base=base,max_packages=stat)
    names=[name for name,_ in packages]
    assert names[:4]==['spell_power','crit','strength','agility'],names
    assert 'spell_power+crit' in names,names

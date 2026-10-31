"""RED: executable, version-bound L0 talent fractions must not be discarded.

The staged source is canonical SQLite, not a fabricated tooltip or talent ID
lookup in production. Compound or unsupported effects must remain fail-closed.
"""
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model.ir import DamageEffect
from src.v2.source_bounded_joint_frontier import source_cold_start_stage,_recovery_variants
from src.v2.source_persistent_slot_search import _source_stat_package_proposals
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'

def _source():
    return build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)

def _rank(ir,slug,n):
    return next(r for t in ir.talents if t.id==slug for r in t.ranks if r.rank==n)

def test_11_source_fractions_and_5_sourced_control_compounds_without_promoting_unsupported():
    ir,coverage=compile_talent_runtime(_source())
    assert coverage['rank_count']==148
    assert coverage['rank_missing_executor']==sum(
        not rank.modifiers for talent in ir.talents for rank in talent.ranks)
    assert coverage['rank_missing_executor']>0
    for slug,cap,kind,values in (
        ('vengeance',5,'critical_damage_bonus_pct',[.2,.4,.6,.8,1.]),
        ('subtlety',3,'threat_factor_pct',[.1,.2,.3]),
        ('living_spirit',3,'actor_stat_pct',[.05,.10,.15]),
    ):
        for n,value in enumerate(values,1):
            rank=_rank(ir,slug,n)
            assert len(rank.modifiers)==1
            modifier=rank.modifiers[0]
            assert modifier.kind==kind
            assert abs(modifier.value-(-value if kind=='threat_factor_pct' else value))<1e-12
            assert modifier.provenance['url'].startswith('https://')
            assert modifier.provenance['source_build']=='1.60.1.70338'
    assert all(len(r.modifiers)==2 for r in next(t for t in ir.talents if t.id=='improved_starfire').ranks)
    for slug in ('brutal_impact','natures_grace','blood_frenzy'):
        assert all(not rank.modifiers for rank in next(t for t in ir.talents if t.id==slug).ranks)
    assert coverage['full_talent_execution_certified'] is False

def test_vengeance_affects_nature_arcane_crit_bonus_but_not_physical_damage():
    original=_source();compiled,_=compile_talent_runtime(original)
    allocation={'improved_wrath':5,'genesis':5,'improved_moonfire':2,
                'natures_majesty':2,'natures_reach':2,'vengeance':5}
    baseline,_=apply_talent_selection(compiled,{k:v for k,v in allocation.items()
        if k!='vengeance'},level=30,bonus_talent_points=5)
    selected,applied=apply_talent_selection(compiled,allocation,level=30,bonus_talent_points=5)
    assert applied.spent_points==21
    for family in ('wrath','moonfire'):
        a=next(a for a in selected.actions if a.family_key==family)
        b=next(a for a in baseline.actions if a.family_key==family)
        for before,after in zip(b.effects,a.effects):
            if isinstance(before,DamageEffect) and before.school.lower() in ('nature','arcane'):
                assert after.crit_multiplier==pytest.approx(1+2*(before.crit_multiplier-1))
    before=next(a for a in baseline.actions if a.family_key=='claw')
    after=next(a for a in selected.actions if a.family_key=='claw')
    assert before.effects==after.effects

def test_living_spirit_and_subtlety_execute_their_sourced_scopes():
    compiled,_=compile_talent_runtime(_source())
    spirit_selection={'furor':5,'naturalist':5,'natural_shapeshifter':3,
                      'reflection':3,'gift_of_nature':4,'living_spirit':3}
    spirit_ir,applied=apply_talent_selection(compiled,spirit_selection,level=30,bonus_talent_points=5)
    assert applied.spent_points==23
    assert spirit_ir.actor.base_stats['spirit']==pytest.approx(compiled.actor.base_stats['spirit']*1.15)
    threat_ir,applied=apply_talent_selection(compiled,{'furor':5,'subtlety':3},level=30,bonus_talent_points=5)
    wrath=next(a for a in threat_ir.actions if a.family_key=='wrath')
    assert wrath.metadata['threat_multiplier']==pytest.approx(.7)
    assert wrath.metadata['threat_execution_scope']=='solo_only_no_competing_actor'
    claw=next(a for a in threat_ir.actions if a.family_key=='claw')
    assert 'threat_multiplier' not in claw.metadata

def test_vengeance_source_crit_build_completes_paid_100mob_in_canonical_runtime():
    compiled,_=compile_talent_runtime(_source())
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=compiled,gear_role='druid_feral')
    proposals=dict(_source_stat_package_proposals(class_key='druid',level=30,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=4)[0])
    assert {'spell_power','crit'} <= proposals.keys()
    # The test's item IDs come exclusively from source selectors. Keep the
    # spell-power set but include one genuine source Crit slot.
    mixed=dict(proposals['spell_power'])
    mixed[next(iter(proposals['crit']))]=next(iter(proposals['crit'].values()))
    stage=substituted_multi_stage(stage=stage,class_key='druid',level=30,swaps=mixed)
    common={'improved_wrath':5,'genesis':5,'improved_moonfire':2,
            'natures_majesty':2,'natures_reach':2}
    outcomes=[]
    for selection in (common,{**common,'vengeance':5}):
        candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
            allocation_override=selection,source_ir=compiled,bonus_talent_points=5,
            allow_partial_gear_stats=True)
        rec=dict(_recovery_variants(candidate.ir,stage,2))['always']
        result=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            recovery_policy=rec,max_wall_s=20)
        assert result['status']=='COMPLETE' and result['count']==100
        assert result['events']>100
        assert result['source_action_counts'].get('wrath:5180',0)>0
        outcomes.append((result,candidate))
    assert outcomes[1][1].ir.actions!=outcomes[0][1].ir.actions

@pytest.mark.parametrize('slug',('vengeance','subtlety','living_spirit'))
def test_zero_sourced_fraction_is_not_an_executable_rank(slug):
    from dataclasses import replace
    original=_source()
    changed=[]
    for talent in original.talents:
        if talent.id!=slug:
            changed.append(talent)
            continue
        ranks=[]
        for rank in talent.ranks:
            if rank.rank!=1:
                ranks.append(rank)
                continue
            source=dict(rank.provenance['checkpoint_source_l0'])
            source['value']=0.0
            ranks.append(replace(rank,provenance={**rank.provenance,
                'checkpoint_source_l0':source}))
        changed.append(replace(talent,ranks=tuple(ranks)))
    tampered=replace(original,talents=tuple(changed))
    compiled,coverage=compile_talent_runtime(tampered)
    assert not _rank(compiled,slug,1).modifiers
    assert any(row['talent_id']==slug and row['rank']==1 for row in coverage['missing'])

"""Sourced multi-effect talent semantics on the shared executor, not fixtures/no-ops."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import _parse_rank_tooltip
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp


def action(ir, family):
    return next(a for a in ir.actions if a.family_key == family)


def periodic(action):
    return next(e for e in action.effects if hasattr(e, 'tick_interval_s'))


def test_duration_source_rank_extends_ticks_not_dilutes_damage_and_heal():
    source = build_game_ir_slice(class_key='druid', level=20)
    chosen = {'genesis':5, 'improved_wrath':5, 'natures_splendor':1}
    baseline, _ = apply_talent_selection(source, {'genesis':5, 'improved_wrath':5}, level=20)
    improved, application = apply_talent_selection(source, chosen, level=20)
    for family, delta in (('moonfire',3),('rejuvenation',3),('regrowth',6)):
        old, new = periodic(action(baseline,family)),periodic(action(improved,family))
        assert new.duration_s == old.duration_s + delta
        assert new.tick_interval_s == old.tick_interval_s
        before = old.total_base_damage if hasattr(old,'total_base_damage') else old.total_base_heal
        after = new.total_base_damage if hasattr(new,'total_base_damage') else new.total_base_heal
        assert after == pytest.approx(before * (new.duration_s/old.duration_s))
    assert sum(m['kind']=='periodic_duration_delta_s' for m in application.applied_modifiers)==3
    talent = next(t for t in source.talents if t.id=='natures_splendor')
    assert 'insect_swarm' in talent.metadata['unavailable_action_targets']
    assert talent.metadata['unsupported_rank_effects']


def test_duration_changes_real_three_pull_scorer():
    source = build_game_ir_slice(class_key='druid',level=20)
    old,_ = apply_talent_selection(source, {'genesis':5,'improved_wrath':5},level=20)
    new,_ = apply_talent_selection(source, {'genesis':5,'improved_wrath':5,'natures_splendor':1},level=20)
    def score(ir):
        return evaluate_repeated_pulls(ir_slice=ir,policy=ir.policies[0],level=20,
            target_health=representative_hp(20),count=3).seconds_per_mob
    assert score(new) < score(old)


def test_source_gcd_reduction_is_real_and_tier_legal():
    source = build_game_ir_slice(class_key='druid',level=20)
    with pytest.raises(ValueError,match='tier gate'):
        validate_talent_selection(source,{'gift_of_the_earthmother':1},level=20)
    # Furor (row 0) + Naturalist (row 1) unlocks this source row-2
    # Restoration talent without inventing an interrupt-avoidance effect.
    allocation={'furor':5,'naturalist':5,'gift_of_the_earthmother':1}
    improved,app=apply_talent_selection(source,allocation,level=20)
    assert action(improved,'rejuvenation').gcd_s == pytest.approx(
        max(0,action(source,'rejuvenation').gcd_s-0.5))
    assert any(x['kind']=='gcd_delta_s' for x in app.applied_modifiers)
    talent=next(t for t in source.talents if t.id=='gift_of_the_earthmother')
    assert set(talent.metadata['unavailable_action_targets'])=={'swiftmend','wild_growth'}


def test_shred_cost_only_changes_sourced_energy_and_lacerate_is_not_faked():
    source=build_game_ir_slice(class_key='druid',level=24)
    improved,app=apply_talent_selection(source,{'ferocity':5,'heart_of_the_wild':5,'shredding_attacks':1},level=24)
    old=action(source,'shred')
    new=action(improved,'shred')
    assert old.costs[0].resource_id=='energy'
    assert new.costs[0].amount == pytest.approx(old.costs[0].amount-6)
    assert any(x['kind']=='resource_cost_flat' for x in app.applied_modifiers)
    talent=next(t for t in source.talents if t.id=='shredding_attacks')
    assert 'lacerate' in talent.metadata['unavailable_action_targets']


def test_root_damage_increase_keeps_secondary_break_semantics_explicit():
    source=build_game_ir_slice(class_key='druid',level=20)
    base=action(source,'entangling_roots')
    improved,_=apply_talent_selection(source,
        {'genesis':5,'improved_wrath':5,'improved_entangling_roots':1},level=20)
    new=action(improved,'entangling_roots')
    assert periodic(new).total_base_damage==pytest.approx(periodic(base).total_base_damage*1.05*1.25)
    talent=next(t for t in source.talents if t.id=='improved_entangling_roots')
    assert any('control_break_secondary_effect_not_executable' in str(x) for x in talent.metadata['unsupported_rank_effects'])


def test_bad_duration_interval_and_unverified_source_pattern_fail_closed():
    source=build_game_ir_slice(class_key='druid',level=20)
    actions=list(source.actions)
    i=next(i for i,a in enumerate(actions) if a.family_key=='moonfire')
    a=actions[i]
    effects=tuple(replace(e,tick_interval_s=5) if hasattr(e,'tick_interval_s') else e for e in a.effects)
    actions[i]=replace(a,effects=effects)
    malformed=replace(source,actions=tuple(actions))
    with pytest.raises(ValueError,match='does not align'):
        apply_talent_selection(malformed,
            {'genesis':5,'improved_wrath':5,'natures_splendor':1},level=20)
    mods,missing,reason=_parse_rank_tooltip('Increases all my powers by 100%.',
        action_families={'moonfire'},source={'authority':'test'})
    assert not mods and reason=='unparsed_effect_semantics'

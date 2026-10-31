"""Live canonical SQLite -> generic talent IR -> real combat and recovery effects."""
from dataclasses import replace
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, _parse_rank_tooltip
from src.game.talents import apply_talent_selection
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import expected_auto_attack_swing, expected_weapon_damage, expected_incoming_attack


def source():
    return build_game_ir_slice(class_key='druid', level=20)


def apply(ir, allocation):
    return apply_talent_selection(ir, allocation, level=20)[0]


def state(ir):
    return ActorState.from_ir(ir.actor, ir.resources, ir.modes)


def legal_feral_extra(extra):
    return {'ferocity':5, 'heart_of_the_wild':5, **extra}


def test_two_source_families_all_ranks_with_positions():
    with sqlite3.connect(DEFAULT_DB) as db:
        for sid, cap, row, col in ((16942,2,2,3),(17002,2,1,0)):
            ranks=db.execute('SELECT rank,raw_tooltip,tooltip_source_url FROM talent_rank_source_facts WHERE spell_id=? ORDER BY rank',(sid,)).fetchall()
            assert len(ranks)==cap
            assert [r[0] for r in ranks]==list(range(1,cap+1))
            assert all(r[1] and r[2]=='https://talentsforever.com/export/druid.json' for r in ranks)
            assert db.execute('SELECT tree_row,tree_col FROM talent_tree_row_facts WHERE spell_id=?',(sid,)).fetchone()==(row,col)


def test_mode_crit_affects_both_auto_and_weapon_actions_and_resets():
    ir=source()
    chosen=apply(ir,legal_feral_extra({'sharpened_claws':1}))
    base=state(ir)
    boosted=state(chosen)
    cat=next(x for x in ir.auto_attacks if x.required_mode_id=='cat')
    claw=next(x for x in ir.actions if x.family_key=='claw')
    weapon=next(e for e in claw.effects if e.effect_type=='weapon_damage')
    base.transition_mode('cat'); boosted.transition_mode('cat')
    assert boosted.stats['melee_crit_chance']-base.stats['melee_crit_chance']==pytest.approx(.03)
    assert expected_auto_attack_swing(cat,actor=boosted)['expected_damage'] > expected_auto_attack_swing(cat,actor=base)['expected_damage']
    assert expected_weapon_damage(weapon,actor=boosted)['expected_damage'] > expected_weapon_damage(weapon,actor=base)['expected_damage']
    boosted.transition_mode('caster')
    base.transition_mode('caster')
    assert boosted.stats.get('melee_crit_chance',0)==pytest.approx(base.stats.get('melee_crit_chance',0))
    assert expected_weapon_damage(weapon,actor=boosted)['expected_damage']==pytest.approx(expected_weapon_damage(weapon,actor=base)['expected_damage'])


def test_dodge_reduces_real_incoming_damage_and_cat_movement_is_mode_only():
    ir=source()
    changed=apply(ir,{'ferocity':5,'feral_swiftness':2})
    plain=state(ir); talented=state(changed)
    incoming=ir.incoming_attacks[0]
    old=expected_incoming_attack(incoming,actor=plain,mitigation_rules=ir.mitigation_rules)
    new=expected_incoming_attack(incoming,actor=talented,mitigation_rules=ir.mitigation_rules)
    assert talented.stats['dodge_chance']-plain.stats['dodge_chance']==pytest.approx(.04)
    assert new['hit_chance']==pytest.approx(old['hit_chance']-.04*incoming.hit_chance)
    assert new['post_mitigation_damage']==pytest.approx(old['post_mitigation_damage']*new['hit_chance']/old['hit_chance'])
    assert talented.stats.get('movement_speed_pct',0)==0
    talented.transition_mode('cat')
    assert talented.stats['movement_speed_pct']==pytest.approx(.30)
    talented.transition_mode('caster')
    assert talented.stats.get('movement_speed_pct',0)==0
    magic=replace(incoming,school='arcane',mitigation_rule_id=None)
    assert expected_incoming_attack(magic,actor=talented)['hit_chance']==pytest.approx(magic.hit_chance)
    already_avoided=replace(incoming,metadata={**incoming.metadata,'hit_chance_includes_actor_dodge':True})
    assert expected_incoming_attack(already_avoided,actor=talented,mitigation_rules=ir.mitigation_rules)['hit_chance']==pytest.approx(incoming.hit_chance)


def test_fail_closed_invalid_rank_and_unparsed_source():
    with pytest.raises(ValueError,match='talent tree tier gate'):
        apply(source(),{'sharpened_claws':1})
    mods,missing,reason=_parse_rank_tooltip('Increases your movement speed while in Unknown Form by 20%, and increases your chance to Dodge by 4%.',
        action_families=set(),source={'url':'source'},mode_labels={'cat_form':'cat'})
    assert not mods and missing==('unknown_form',) and reason=='movement_source_mode_missing'


def test_generic_mode_crit_has_no_class_switch():
    ir=source()
    ir=replace(ir,actor=replace(ir.actor,metadata={**ir.actor.metadata,'class_key':'synthetic'}))
    changed=apply(ir,legal_feral_extra({'sharpened_claws':1}))
    actor=state(changed)
    actor.transition_mode('bear')
    base=state(ir)
    base.transition_mode('bear')
    assert actor.stats['melee_crit_chance']-base.stats['melee_crit_chance']==pytest.approx(.03)

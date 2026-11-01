"""Source-to-SQLite-to-executor vertical regression for mode-entry and crit talents."""
from dataclasses import replace
import sqlite3
import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB, _parse_rank_tooltip
from src.game.model.ir import ModeEntryResourceModifier
from src.game.talents import apply_talent_selection
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import execute_action


def source(level=20):
    return build_source_slice(level)


def apply(ir,selection):
    return apply_talent_selection(ir,selection,level=20)[0]


def actor(ir):
    return ActorState.from_ir(ir.actor,ir.resources,ir.modes)


def action(ir,family):
    return next(a for a in ir.actions if a.family_key==family)


def test_source_rank_curves_and_provenance_are_canonical():
    with sqlite3.connect(DEFAULT_DB) as db:
        for sid,n in ((17056,5),(16821,2),(1223082,2)):
            rows=db.execute('SELECT rank,max_rank,raw_tooltip,source_url,source_authority '
                'FROM talent_rank_source_facts WHERE class_key=? AND spell_id=? ORDER BY rank',
                ('druid',sid)).fetchall()
            assert len(rows)==n and [r[0] for r in rows]==list(range(1,n+1))
            assert all(r[1]==n and r[2] and r[3].startswith('https://') and r[4] for r in rows)
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'


def test_furor_five_rank_curve_derived_from_tooltips():
    ir=source()
    talent=next(t for t in ir.talents if t.id=='furor')
    for rank,definition in enumerate(talent.ranks,1):
        assert len(definition.modifiers)==2
        gain,restore=definition.modifiers
        assert gain.kind=='mode_entry_expected_gain' and gain.value==pytest.approx(2*rank)
        assert restore.kind=='mode_entry_restore_last' and restore.value==pytest.approx(.2*rank)
        assert restore.provenance['outside_regen_per_s']==pytest.approx(2*rank)
        assert restore.provenance['max_restored']==pytest.approx(20*rank)


def test_cat_entry_zero_without_furor_and_source_rank5_restoration():
    base=actor(source())
    base.transition_mode('cat')
    assert base.resources['energy']==0
    base.resources['energy']=50
    base.current_time_s=5
    base.transition_mode('caster')
    base.current_time_s=8
    base.transition_mode('cat')
    assert base.resources['energy']==0
    ranked=actor(apply(source(),{'furor':5}))
    ranked.transition_mode('cat')
    ranked.resources['energy']=50
    ranked.current_time_s=5
    ranked.transition_mode('caster')
    ranked.current_time_s=8
    transition=ranked.transition_mode('cat')
    assert ranked.resources['energy']==pytest.approx(80)
    assert any(row['phase']=='talent_entry' and row['gained']==80 for row in transition['resource_changes'])


def test_bear_forfeits_bank_and_only_subsequent_caster_time_regenerates():
    a=actor(apply(source(),{'furor':5}))
    a.transition_mode('cat')
    a.resources['energy']=90
    a.current_time_s=5
    a.transition_mode('bear')
    a.current_time_s=7
    a.transition_mode('cat')
    assert a.resources['energy']==0
    a.resources['energy']=60
    a.current_time_s=10
    a.transition_mode('bear')
    a.current_time_s=12
    a.transition_mode('caster')
    a.current_time_s=15
    a.transition_mode('cat')
    assert a.resources['energy']==pytest.approx(30)


def test_bear_expected_rage_gain_in_real_action_runtime():
    ir=apply(source(),{'furor':5})
    a=actor(ir)
    bear=action(ir,'bear_form')
    result=execute_action(action=bear,actor=a,target=TargetState(id='mob',health=10000,max_health=10000))
    assert a.current_mode_id=='bear'
    assert a.resources['rage']==pytest.approx(10)
    assert any(e.kind=='ModeChanged' and any(x['phase']=='talent_entry' and x['gained']==10
               for x in e.payload['resource_changes']) for e in result.events)


def test_crit_talents_change_direct_periodic_and_autoattack_expected_values():
    ir=source()
    modified=apply(ir,{'improved_wrath':5,'improved_moonfire':2,'natures_majesty':2})
    moon=action(ir,'moonfire')
    changed=action(modified,'moonfire')
    direct0=next(e for e in moon.effects if e.effect_type=='damage')
    direct1=next(e for e in changed.effects if e.effect_type=='damage')
    dot0=next(e for e in moon.effects if e.effect_type=='periodic_damage')
    dot1=next(e for e in changed.effects if e.effect_type=='periodic_damage')
    assert direct1.base_min==pytest.approx(direct0.base_min*1.1)
    assert dot1.total_base_damage==pytest.approx(dot0.total_base_damage*1.1)
    assert direct1.crit_chance_bonus==pytest.approx(.14)
    assert dot1.crit_chance_bonus==pytest.approx(.14)
    cat0=next(a for a in ir.auto_attacks if a.id=='auto_attack:cat')
    cat1=next(a for a in modified.auto_attacks if a.id=='auto_attack:cat')
    assert cat1.crit_chance_on_landed_hit==pytest.approx(cat0.crit_chance_on_landed_hit+.04)
    original=execute_action(action=moon,actor=actor(ir),target=TargetState(id='mob',health=10000,max_health=10000))
    upgraded=execute_action(action=changed,actor=actor(modified),target=TargetState(id='mob',health=10000,max_health=10000))
    assert upgraded.total_damage>original.total_damage
    periodic_original=sum(e.payload.get('amount',0) for e in original.events if e.kind=='Damage' and e.payload.get('periodic'))
    periodic_upgraded=sum(e.payload.get('amount',0) for e in upgraded.events if e.kind=='Damage' and e.payload.get('periodic'))
    assert periodic_upgraded>periodic_original


def test_crit_generic_actor_does_not_depend_on_class_name():
    ir=source()
    modified=replace(ir,actor=replace(ir.actor,metadata={**ir.actor.metadata,'class_key':'synthetic'}))
    result=apply(modified,{'improved_wrath':5,'natures_majesty':2})
    assert action(result,'wrath').effects[0].crit_chance_bonus==pytest.approx(.04)


def test_invalid_resource_and_unrecognized_tooltip_fail_closed():
    ir=source()
    modified=replace(ir,resources=tuple(r for r in ir.resources if r.id!='energy'))
    with pytest.raises(ValueError,match='mode entry talent resource unavailable'):
        apply(modified,{'furor':1})
    mods,missing,reason=_parse_rank_tooltip('Furor: give me 100 Energy for free',
        action_families={'wrath'},source={'url':'fake'},mode_labels={'cat_form':'cat'})
    assert not mods and reason=='unparsed_effect_semantics'

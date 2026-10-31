"""WF239: source rank -> canonical SQLite -> shared actions -> real policy combat."""
from dataclasses import replace
import json
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_ability_semantics import source_ability_actions
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime
from src.game.talents import apply_talent_selection
from src.v2.source_policy_search import synthesize_source_policies


def _action(ir,family):
    return next(x for x in ir.actions if x.family_key==family)


def test_source_semantics_and_rank_inventory():
    with sqlite3.connect(DEFAULT_DB) as c:
        rows=c.execute('''SELECT s.spell_id,i.name,i.level_hint,s.source_url,s.mechanics_source_url
            FROM ability_semantic_source_facts s JOIN spell_index i
            ON i.spell_id=s.spell_id AND i.class_key=s.class_key AND i.kind='abilities'
            WHERE s.class_key='druid' ORDER BY i.name,i.level_hint''').fetchall()
        assert len(rows)==31
        assert len([x for x in rows if x[1]=='Starfire'])==7
        assert len([x for x in rows if x[1]=='Rake'])==4
        assert len([x for x in rows if x[1]=='Shred'])==5
        assert len([x for x in rows if x[1]=='Entangling Roots'])==6
        assert len([x for x in rows if x[1]=='Regrowth'])==9
        assert all(x[3].startswith('https://www.wowhead.com/forever/spell=') and
                   x[4].startswith('https://www.wowhead.com/forever/spell=') for x in rows)
        source=c.execute("SELECT COUNT(*),COUNT(DISTINCT spell_id) FROM talent_rank_source_facts WHERE class_key='druid'").fetchone()
        assert source[0]>=94 and source[1]>=29


def test_rank_selection_uses_source_level_and_never_future_rank():
    for level,expected in ((20,{'starfire':2912}),
                           (24,{'starfire':2912,'rake':1822}),
                           (30,{'starfire':8949,'rake':1822}),
                           (34,{'starfire':8950,'rake':1823}),
                           (60,{'starfire':25298,'rake':9904})):
        ir=build_game_ir_slice(class_key='druid',level=level)
        for family,sid in expected.items():
            action=_action(ir,family)
            assert action.id==f'source_spell:{sid}'
            mode=next(r['value'] for r in action.requirements if r['kind']=='mode_is')
            assert action.id in next(m for m in ir.modes if m.id==mode).enabled_action_ids
        assert len([x for x in ir.actions if x.family_key=='starfire'])==1
        assert len([x for x in ir.actions if x.family_key=='rake'])==(level>=24)


def test_real_starfire_cast_cost_damage_and_search_candidate():
    ir=build_game_ir_slice(class_key='druid',level=20)
    action=_action(ir,'starfire')
    assert action.cast_time_s==3.5 and action.costs[0].amount==95
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState(id='mob',health=2000,max_health=2000)
    runtime=CombatRuntime(actor=actor,target=target,spell_power=0)
    runtime.schedule_action(action)
    assert target.health==pytest.approx(2000-87.5)
    assert actor.resources['mana']==pytest.approx(ir.resources[0].initial_amount-95)
    assert any(e.kind=='Damage' and e.action_id==action.id for e in runtime.trace)
    envelope=synthesize_source_policies(ir,level=20,max_policies=128)
    assert action.id in envelope['eligible_buttons']
    assert any(action.id in [r.action_id for r in p.rules] for p in envelope['policies'])


def test_real_rake_direct_dot_combo_and_mode_rejection():
    ir=build_game_ir_slice(class_key='druid',level=24)
    action=_action(ir,'rake')
    assert action.costs[0].amount==40
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    target=TargetState(id='mob',health=2000,max_health=2000)
    runtime=CombatRuntime(actor=actor,target=target,spell_power=0)
    with pytest.raises(Exception):
        runtime.schedule_action(action) # caster cannot use Cat ability
    actor.transition_mode('cat')
    actor.resources['energy']=100
    runtime.schedule_action(action)
    runtime.advance_to(10)
    assert target.health==pytest.approx(2000-23-48)
    assert target.resources['combo_points']==pytest.approx(1)
    assert len([e for e in runtime.trace if e.kind=='Damage' and e.action_id==action.id])==4
    assert actor.resources['energy']<=100-40+100 # regen is separate from cost


def test_source_families_and_partial_stealth_effect_are_visible():
    ir=build_game_ir_slice(class_key='druid',level=20)
    talent=next(t for t in ir.talents if t.id=='feral_instinct')
    assert talent.max_rank==3
    assert len(talent.ranks)==3
    assert all(row.modifiers for row in talent.ranks)
    assert all('stealth_detection_secondary_effect_not_executable' in str(x)
               for x in talent.metadata['unsupported_rank_effects'])
    plain,_=apply_talent_selection(ir,{'ferocity':5},level=20)
    boosted,_=apply_talent_selection(ir,{'ferocity':5,'feral_instinct':3},level=20)
    assert _action(boosted,'swipe').effects[0].base_min==pytest.approx(
        _action(plain,'swipe').effects[0].base_min*1.3)
    with pytest.raises(ValueError,match='tier gate'):
        apply_talent_selection(ir,{'feral_instinct':1},level=20)
    with pytest.raises(ValueError,match='illegal rank'):
        apply_talent_selection(ir,{'ferocity':5,'feral_instinct':4},level=20)


def test_fail_closed_on_malformed_source_tooltip(tmp_path):
    import shutil
    db=tmp_path/'source.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as c:
        row=c.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822 AND kind="abilities"').fetchone()
        payload=json.loads(row[0]);payload['envChange']['after']['text']='Unknown source ability'
        c.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=1822 AND kind="abilities"',(json.dumps(payload),))
    ir=build_game_ir_slice(class_key='druid',level=24)
    # Remove the source spell from an IR before testing generic reingestion.
    ir=replace(ir,actions=tuple(a for a in ir.actions if a.family_key!='rake'),
               modes=tuple(replace(m,enabled_action_ids=tuple(x for x in m.enabled_action_ids if x!='source_spell:1822')) for m in ir.modes))
    updated=source_ability_actions(ir,class_key='druid',level=24,db_path=db)
    assert 'rake' not in [a.family_key for a in updated.actions]
    assert any(x['spell_id']==1822 for x in updated.provenance['source_ability_ingest']['unparsed_semantic_rows'])


def test_default_mode_search_includes_new_source_rake_policy():
    from src.v2.source_mode_search import evaluate_discovered_mode_search
    result=evaluate_discovered_mode_search(class_key='druid',level=24,schedule_incoming_attacks=True)
    assert result['candidate_count']==159
    assert result['evaluated_count']>100
    assert any(x['action_id']=='source_spell:1822' for x in result['winner']['selected_actions'])
    # WF241: HoT overlaps vendor recovery; combat action selection remains Rake.
    assert result['winner']['seconds_per_mob']==pytest.approx(24.58512931034483)
    assert result['winner']['recovery_s'] < 9.46703687975696

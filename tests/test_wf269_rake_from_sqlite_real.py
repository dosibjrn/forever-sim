"""WF269: Rake ranks must execute from actual Forever SQLite+event runtime."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from src.game.data.forever.sqlite_rake import load_rake_facts
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime
from src.game.multi_pull import evaluate_repeated_pulls


def test_ranks_source_current_after_patch_and_no_pre24_legal_action():
    assert load_rake_facts(23) is None
    for level, spell_id, direct, dot in (
        (24,1822,23,48),(27,1822,23,48),(34,1823,31,63),
        (44,1824,45,78),(54,9904,61,102)):
        fact=load_rake_facts(level)
        assert (fact['spell_id'],fact['direct'],fact['periodic']) == (spell_id,direct,dot)
        s=build_game_ir_slice(class_key='druid',level=level)
        act=next(a for a in s.actions if a.family_key=='rake')
        assert act.id==f'rake:{spell_id}'
        assert any(m.id=='cat' and act.id in m.enabled_action_ids for m in s.modes)
        assert len(act.effects)==3
        assert act.effects[1].crit_chance_stat_id=='melee_crit_chance'
    assert not any(a.family_key=='rake' for a in build_game_ir_slice(class_key='druid',level=23).actions)


def _one_action(melee_crit):
    s=build_game_ir_slice(class_key='druid',level=27)
    modified=replace(s.actor, base_stats={**s.actor.base_stats,'melee_crit_chance':melee_crit})
    actor=ActorState.from_ir(modified,s.resources,s.modes)
    actor.transition_mode('cat')
    actor.resources['energy']=100.
    target=TargetState.with_health('rake-target',9999.)
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=())
    action=next(a for a in s.actions if a.family_key=='rake')
    runtime.schedule_action(action);runtime.run_until_idle()
    events=[e for e in runtime.result().events if e.kind=='Damage' and e.payload.get('applied')]
    return actor,target,events


def test_real_executor_direct_and_three_bleed_ticks_crit_exactly_double():
    actor0,target0,events0=_one_action(0)
    assert actor0.resources["energy"]==pytest.approx(100.) # 40 spent, 9s regen at 10/s
    assert target0.resources['combo_points']==1
    assert [e.time_s for e in events0]==[0.,3.,6.,9.]
    assert [e.payload['amount'] for e in events0]==[23.,16.,16.,16.]
    _,_,events1=_one_action(1.0)
    assert [e.payload['amount'] for e in events1]==[46.,32.,32.,32.]
    _,_,observed=_one_action(.174)
    assert sum(e.payload['amount'] for e in observed)==pytest.approx(71*1.174)
    assert all(e.payload['periodic'] for e in observed[1:])


def test_real_27_multi_pull_executes_rake_and_claw_no_free_refill():
    s=build_game_ir_slice(class_key='druid',level=27)
    cat=next(p for p in s.policies if 'cat-builder-finisher' in p.id)
    result=evaluate_repeated_pulls(ir_slice=s,policy=cat,level=27,target_health=484,
        count=2,pre_combat_action_ids=('cat_form:768',),
        post_combat_action_ids=('cancel_mode:cat',),
        prepared_first_pull_resources={'energy':100,'rage':0},
        recovery_mode='threshold', retain_mode_between_pulls=True,
        travel_time_s=2.2,apply_target_defense=True)
    ids=[a['action_id'] for p in result.pulls for a in p['selected_actions']]
    assert 'rake:1822' in ids and 'claw:20' in ids
    assert result.seconds_per_mob>0
    assert result.pulls[0]['prepared_first_pull_resources']=={'energy':100,'rage':0}
    assert result.pulls[1]['prepared_first_pull_resources']=={}


def _copydb(tmp_path):
    dst=tmp_path/'copy.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(dst) as out:src.backup(out)
    return dst


def test_data_only_rank_change_reaches_loader(tmp_path):
    dst=_copydb(tmp_path)
    with sqlite3.connect(dst) as con:
        js=con.execute("select raw_listview_json from spell_index where spell_id=1822").fetchone()[0]
        obj=json.loads(js);obj['envChange']['after']['text']=obj['envChange']['after']['text'].replace('23 damage','25 damage')
        con.execute('update spell_index set raw_listview_json=? where spell_id=1822',(json.dumps(obj),))
    assert load_rake_facts(27,db_path=dst)['direct']==25


def test_source_missing_and_invalid_mechanics_fail_closed(tmp_path):
    dst=_copydb(tmp_path)
    with sqlite3.connect(dst) as con:
        con.execute('delete from sourced_direct_periodic_melee_semantics where spell_id=1822')
    with pytest.raises(ValueError,match='semantics coverage missing'):
        load_rake_facts(27,db_path=dst)
    dst=_copydb(tmp_path)
    with sqlite3.connect(dst) as con:
        con.execute('update sourced_direct_periodic_melee_semantics set tick_interval_s=4 where spell_id=1822')
    with pytest.raises(ValueError,match='invalid source'):
        load_rake_facts(27,db_path=dst)


def test_source_target_armor_applies_to_rake_direct_but_not_bleed():
    from src.game.data.forever.target_combat_source import target_combat_metadata
    s=build_game_ir_slice(class_key='druid',level=27)
    actor=ActorState.from_ir(s.actor,s.resources,s.modes)
    actor.transition_mode('cat');actor.resources['energy']=100.
    target=TargetState.with_health('armored',9999.,**target_combat_metadata(s))
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=())
    runtime.schedule_action(next(a for a in s.actions if a.family_key=='rake'))
    runtime.run_until_idle()
    events=[e for e in runtime.result().events if e.kind=='Damage' and e.payload.get('applied')]
    direct,*bleeds=events
    assert direct.payload['target_armor_reduction']>0
    assert direct.payload['amount']<23*(1+.014)
    assert all(e.payload['target_armor_reduction']==0 for e in bleeds)
    assert [e.payload['amount'] for e in bleeds]==pytest.approx([16*(1+.014)*.95]*3)

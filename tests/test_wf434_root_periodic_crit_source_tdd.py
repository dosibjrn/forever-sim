"""Patch-observed periodic crit through SQLite→IR→paid CombatRuntime.

Root break and heartbeat probabilities remain explicitly unknown.
"""
from dataclasses import replace
from pathlib import Path
import sqlite3
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.game.model.ir import PeriodicEffect
from src.game.multi_pull import evaluate_repeated_pulls
from tests.test_wf433_source_root_concurrency_tdd import DB,_selected,_root


def _dot(action):
    return next(e for e in action.effects if isinstance(e,PeriodicEffect))


def test_source_flag_canonical_sqlite_and_patch_only_uncertainty():
    with sqlite3.connect(DB) as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'sourced_periodic_spell_flags' in tables
        rows=c.execute('SELECT spell_id,source_patch,build_attested,periodic_can_crit,source_url '
                       'FROM sourced_periodic_spell_flags').fetchall()
    assert {339,1062,5195}.issubset({r[0] for r in rows})
    for sid,patch,attested,crit,url in rows:
        if sid in (339,1062,5195):
            assert patch=='1.60.1' and attested==0 and crit==1
            assert url.startswith('https://www.wowhead.com/forever/')


def test_source_all_root_ranks_have_periodic_crit_but_break_still_unknown():
    ir=_selected(2)
    roots=[a for a in ir.actions if a.family_key=='entangling_roots']
    assert len(roots)==3
    for a in roots:
        dot=_dot(a)
        assert dot.crit_chance_stat_id=='spell_crit_chance'
        assert dot.field_provenance['periodic_can_crit'][0]['build_attested'] is False
        assert not any(s['semantic']=='periodic_can_crit' for s in dot.unsupported_semantics)
        assert any(s['semantic']=='root_break_on_damage_or_heartbeat' for s in dot.unsupported_semantics)


def test_missing_source_flag_does_not_invent_periodic_crit(tmp_path):
    dst=tmp_path/'tampered.sqlite'
    with sqlite3.connect(DB) as source,sqlite3.connect(dst) as dest:
        source.backup(dest)
        dest.execute('DELETE FROM sourced_periodic_spell_flags WHERE spell_id=5195')
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=dst)
    dot=_dot(_root(ir))
    assert dot.crit_chance_stat_id is None
    assert any(s['semantic']=='periodic_can_crit' for s in dot.unsupported_semantics)


def test_paid_2d_100mob_periodic_crit_ablation_with_same_direct_spell_crit():
    ir=_selected(2)
    root=_root(ir)
    wrath=next(a for a in ir.actions if a.family_key=='wrath')
    policy=PolicyDefinition('root_crit','root_crit',rules=(
        PolicyRuleDefinition('root',root.id,conditions=(PolicyCondition(kind='target_control_missing',value='root'),)),
        PolicyRuleDefinition('wrath',wrath.id)))
    ir=replace(ir,actor=replace(ir.actor,base_stats={**ir.actor.base_stats,'spell_crit_chance':0.4}))
    without=replace(ir,actions=tuple(replace(a,effects=tuple(
        replace(e,crit_chance_stat_id=None) if isinstance(e,PeriodicEffect) else e for e in a.effects))
        if a.family_key=='entangling_roots' else a for a in ir.actions))
    results=[]
    for case in (without,ir):
        r=evaluate_repeated_pulls(ir_slice=case,policy=policy,level=30,target_health=200.,
            count=100,pack_size=2,schedule_incoming_attacks=True,recovery_mode='always',max_actions=256)
        assert len(r.pulls)==50 and all(p['pack_all_defeated'] for p in r.pulls)
        results.append(r)
    damage=lambda r:sum(p['damage_by_role']['player'] for p in r.pulls)
    assert damage(results[1])>damage(results[0])
    assert any(s['semantic']=='root_break_on_damage_or_heartbeat' for s in _dot(root).unsupported_semantics)

"""WF433 RED: source-pinned control concurrency, real 2D target state, paid 100mob."""
from dataclasses import replace
from pathlib import Path
import sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILLER={'genesis':5,'improved_wrath':5,'improved_moonfire':2,
        'natures_majesty':2,'moonglow':3,'natures_reach':2,
        'improved_entangling_roots':1}


def _ir():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))[0]


def _selected(rank):
    ir=_ir()
    if rank == 0:
        return ir
    return apply_talent_selection(ir,{**FILLER,'overgrowth':rank,'ferocity':4},
                                  level=30,bonus_talent_points=5)[0]


def _root(ir):
    return max((a for a in ir.actions if a.family_key=='entangling_roots'),
               key=lambda a:a.metadata['source_spell_rank'])


def _runtime(rank, *, incoming=False):
    ir=_selected(rank)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resource_capacity['mana']=100000.
    actor.resources['mana']=100000.
    targets=[TargetState.with_health(f'm{i}',10000.) for i in range(4)]
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
        spatial_positions_yards={f'm{i}':(i*6.,0.) for i in range(4)},
        enemy_move_speed_yards_s=5.,melee_radius_yards=5.)
    return rt,_root(ir)


def _cast(rt,action,target):
    rt.engage_target(target)
    rt.select_target(target)
    rt.advance_to(max(rt.actor.current_time_s,rt.actor.gcd_ready_s))
    end=rt.schedule_action(action)
    rt.advance_to(end)


def _rooted(rt):
    now=rt.actor.current_time_s
    return {key for key,t in rt.targets.items() if t.active_controls.get('root',0.)>now+1e-9}


def test_exact_build_source_baseline_and_two_ranks_compile_to_generic_action_metadata():
    ir=_ir()
    rows=next(t.ranks for t in ir.talents if t.id=='overgrowth')
    assert [r.modifiers[0].kind for r in rows]==['control_target_cap_bonus']*2
    assert [r.modifiers[0].value for r in rows]==[1.,2.]
    assert _root(_selected(0)).metadata['source_control_target_caps']['root']['max_targets']==1
    for rank,cap in ((1,2),(2,3)):
        a=_root(_selected(rank))
        spec=a.metadata['source_control_target_caps']['root']
        assert spec['max_targets']==cap
        assert spec['source_build']=='1.60.1.70338'
        assert spec['base_source_url'].startswith('https://')


@pytest.mark.parametrize('rank,expected',[(0,{'m3'}),(1,{'m2','m3'}),(2,{'m1','m2','m3'})])
def test_real_2d_casts_evict_oldest_root_and_keep_other_targets_independent(rank,expected):
    rt,root=_runtime(rank)
    for i in range(4):
        _cast(rt,root,f'm{i}')
    assert _rooted(rt)==expected
    assert len([e for e in rt.trace if e.kind=='ControlTargetCapEvicted'])==4-len(expected)
    assert len([e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==root.id])==4
    assert all(rt.targets[k].active_controls.get('root',0.)<=rt.actor.current_time_s+1e-9
               for k in {'m0','m1','m2','m3'}-expected)
    # A stale expiry for an evicted target must not clear the surviving controls.
    rt.advance_to(rt.actor.current_time_s+3.)
    assert _rooted(rt)==expected


def test_source_control_cap_fails_closed_without_matching_baseline(tmp_path):
    copy=tmp_path/'corrupt.sqlite'
    with sqlite3.connect(DB) as src, sqlite3.connect(copy) as dst:
        src.backup(dst)
        dst.execute("DELETE FROM sourced_control_target_cap_facts WHERE class_key='druid'")
    with pytest.raises(ValueError,match='SOURCE_CONTROL_TARGET_CAP_BASELINE_MISSING'):
        compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=copy))


def test_paid_100mob_simultaneous_2d_root_policy_survives_with_recovery():
    from src.game.multi_pull import evaluate_repeated_pulls
    ir=_selected(2)
    root=_root(ir)
    wrath=next(a for a in ir.actions if a.family_key=='wrath')
    policy=PolicyDefinition('sourced_root_control_100','Root then Wrath',rules=(
        PolicyRuleDefinition('root',root.id,conditions=(
            PolicyCondition(kind='target_control_missing',value='root'),)),
        PolicyRuleDefinition('wrath',wrath.id)))
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,
        target_health=200.,count=100,pack_size=2,
        schedule_incoming_attacks=True,recovery_mode='always',max_actions=256)
    assert len(result.pulls)==50
    assert all(p['pack_all_defeated'] for p in result.pulls)
    assert sum(p['mob_count'] for p in result.pulls)==100
    assert sum(p['event_transitions'] for p in result.pulls)>1000
    assert sum(sum(x['action_id']==root.id for x in p['selected_actions'])
               for p in result.pulls)>=50
    assert result.seconds_per_mob>0



def test_independent_source_root_expirations_in_real_2d_queue():
    rt,root=_runtime(2)
    for i in range(3):
        _cast(rt,root,f'm{i}')
    assert _rooted(rt)=={'m0','m1','m2'}
    rt.advance_to(19.6)
    assert _rooted(rt)=={'m1','m2'}
    rt.advance_to(21.1)
    assert _rooted(rt)=={'m2'}
    rt.advance_to(22.6)
    assert not _rooted(rt)
    assert len([e for e in rt.trace if e.kind=='ControlExpired'])>=3


def test_source_control_baseline_rejects_tampered_rank_text(tmp_path):
    copy=tmp_path/'corrupt_source.sqlite'
    with sqlite3.connect(DB) as src, sqlite3.connect(copy) as dst:
        src.backup(dst)
        dst.execute("UPDATE sourced_control_target_cap_facts SET base_max_targets=2")
    with pytest.raises(ValueError,match='SOURCE_CONTROL_TARGET_CAP_EVIDENCE_CONFLICT'):
        build_game_ir_slice(class_key='druid',level=30,ability_db_path=copy)

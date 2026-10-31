"""Functional source→IR→talent grant→combat/rank→legal route regressions."""
import json, sqlite3
from pathlib import Path
import pytest

from src.game.data.forever.registry import build_game_ir_slice, generic_source_level_bounds
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.source_legal_beam import legal_point_frontier
from src.game.talent_search import talent_candidate_id
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import _score_state
from src.shared.leveling.objective import representative_hp
from src.v2.generic_frontier import GenericTalentBuild, GenericTalentRouteModel
from src.v2.path_dp import LevelNode, solve_path_dp


def _action(ir,family):
    rows=[a for a in ir.actions if a.family_key==family]
    assert len(rows)==1
    return rows[0]


def test_verified_rank_gates_across_levels():
    assert generic_source_level_bounds('paladin')==(10,30)
    at={n:build_game_ir_slice(class_key='paladin',level=n) for n in (20,21,22,25,26,27,28,29,30)}
    assert _action(at[20],'holy_strike').id=='holy_strike:1866'
    assert _action(at[27],'holy_strike').id=='holy_strike:1866'
    assert _action(at[28],'holy_strike').id=='holy_strike:680'
    assert _action(at[25],'seal_of_righteousness').id=='seal_of_righteousness:20288'
    assert _action(at[26],'seal_of_righteousness').id=='seal_of_righteousness:20289'
    assert _action(at[21],'holy_light').id=='holy_light:647'
    assert _action(at[22],'holy_light').id=='holy_light:1026'
    assert _action(at[30],'holy_light').id=='holy_light:1042'
    assert build_game_ir_slice(class_key='paladin',level=31) is None


def test_talent_grant_rank_selected_by_source_and_illegal_missing_grant():
    allocation={'benediction':5,'conviction':5,'seal_of_command':1}
    for level,expected in ((20,20375),(29,20375),(30,20915)):
        ir=build_game_ir_slice(class_key='paladin',level=level)
        granted,_=apply_talent_selection(ir,allocation,level=level)
        assert _action(granted,'seal_of_command').id==f'seal_of_command:{expected}'
        assert len([t for t in granted.triggers if t.required_aura_id=='seal:command'])==2
    ir=build_game_ir_slice(class_key='paladin',level=30)
    with pytest.raises(ValueError,match='rank|unknown'):
        validate_talent_selection(ir,{'seal_of_command':2},level=30)
    no_grant,_=apply_talent_selection(ir,{'benediction':5,'conviction':5},level=30)
    assert not any(a.family_key=='seal_of_command' for a in no_grant.actions)


def test_real_l30_incoming_combat_and_recovery():
    ir=build_game_ir_slice(class_key='paladin',level=30)
    gears=_gear_envelope('paladin',30,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    row=_score_state(ir,level=30,gear=gears[0],allocation={
        'benediction':5,'conviction':5,'seal_of_command':1},pulls=3,
        policy_cap=8,target_health=representative_hp(30))
    assert row['seconds_per_mob']>0 and row['policy_evaluated']>=1
    assert len(row['best_policy']['pulls'])==3
    assert row['best_policy']['pulls'][0]['kill_s']>0
    assert row['best_policy']['pulls'][0]['recovery_s']>=0
    assert row['gear_slots']['weapon']['item_id']>0


def test_all_executable_full_budget_allocations_have_legal_transitions():
    states=[{}];pools={}
    for level in range(10,31):
        ir=build_game_ir_slice(class_key='paladin',level=level)
        next_states={talent_candidate_id(a):a for old in states
            for a in legal_point_frontier(ir,old,level=level,allow_transfers=False)}
        assert next_states
        for a in next_states.values():
            validate_talent_selection(ir,a,level=level)
            assert sum(a.values())==level-9
        pools[level]=[LevelNode(level=level,
            talents=GenericTalentBuild.from_candidate({'selection':a,
                'candidate_id':talent_candidate_id(a)},available_points=level-9,
                executable_talent_ids=(),talent_tree_by_id={t.id:t.tree_key for t in ir.talents}),
            score_s_per_100=100.0) for a in next_states.values()]
        states=list(next_states.values())
    assert len(pools[20])==22
    assert len(pools[30])==1
    route=solve_path_dp(pools,max_respecs=0,model=GenericTalentRouteModel())
    assert len(route.steps)==21 and route.respecs_used==0
    for step in route.steps[1:]:
        assert step.kind=='point' and step.talent_added
    with pytest.raises(ValueError,match='no legal path|node has|node level mismatch'):
        solve_path_dp({20:pools[20],21:pools[20]},max_respecs=0,model=GenericTalentRouteModel())


def test_cross_class_mage_and_hunter_unchanged():
    for key in ('mage','hunter','druid'):
        ir=build_game_ir_slice(class_key=key,level=20)
        assert ir is not None and ir.actor.metadata['class_key']==key
        assert ir.actions and ir.auto_attacks


def test_source_capture_rows_and_integrity():
    with sqlite3.connect(DEFAULT_DB) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM verified_native_class_actions WHERE class_key=? AND spell_id=?',('paladin',680)).fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM sourced_timed_aura_actions WHERE class_key=? AND spell_id=?',('paladin',20289)).fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM verified_talent_granted_action_facts WHERE class_key=? AND spell_id=?',('paladin',20915)).fetchone()[0]==1


def test_flash_of_light_source_rank_and_recovery_executes():
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.v2.source_policy_search import synthesize_source_policies
    for level,sid,cost in ((19,None,None),(20,19750,35),(25,19750,35),(26,19939,50),(30,19939,50)):
        ir=build_game_ir_slice(class_key='paladin',level=level)
        rows=[a for a in ir.actions if a.family_key=='flash_of_light']
        assert len(rows)==(1 if sid is not None else 0)
        if rows:
            assert rows[0].id==f'flash_of_light:{sid}'
            assert rows[0].costs[0].amount==cost
    ir=build_game_ir_slice(class_key='paladin',level=26)
    gears=_gear_envelope('paladin',26,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    from src.game.gear import apply_gear_selection
    geared,_=apply_gear_selection(ir,aggregate_stats=gears[0]['selection'].aggregate_stats,
        selected_items=tuple(gears[0]['selection'].slots.values()))
    from src.game.talents import apply_talent_selection
    talented,_=apply_talent_selection(geared,{'benediction':5,'conviction':5},level=26)
    policies=synthesize_source_policies(talented,level=26,max_policies=8,
        include_auto_resource_fallback=True,budget_mode='balanced_frontier')['policies']
    scored=[evaluate_repeated_pulls(ir_slice=talented,policy=p,level=26,
        target_health=representative_hp(26),count=3,schedule_incoming_attacks=True,
        apply_target_defense=True) for p in policies]
    assert scored and all(s.seconds_per_mob>0 for s in scored)
    assert any('flash_of_light:19939' in str(x) for s in scored for pull in s.pulls
        for x in pull['heal_actions'])


def test_flash_source_ingest_idempotent_and_conflict_fails_closed(tmp_path):
    from tools.wf257_ingest_flash_recovery import ingest,CAPTURE
    assert ingest()['already_installed'] is True
    bad=json.loads(CAPTURE.read_text());bad['ranks'][0]['min']=999
    path=tmp_path/'bad.json';path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='source rank tooltip|unparsed sourced'):
        ingest(capture_path=path)


def test_corridor_capture_idempotent_and_negative_source(tmp_path):
    from tools.wf257_ingest_paladin_corridor import ingest,CAPTURE
    assert ingest()['already_installed'] is True
    data=json.loads(CAPTURE.read_text())
    data['capture_id']='wrong_concurrent_capture'
    path=tmp_path/'wrong.json';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='conflicting rank capture'):
        ingest(capture_path=path)


def test_global_recovery_plan_search_can_reject_locally_fast_heal():
    from tools.wf257_run_corridor import _policy
    from src.game.gear import apply_gear_selection
    from src.game.multi_pull import evaluate_repeated_pulls
    old=json.loads((Path(__file__).resolve().parents[1]/'WF256_PALADIN_SEALS_REPLAY.json').read_text())
    ids=old['frozen_previous_native_winner']['gear_ids']
    ir=build_game_ir_slice(class_key='paladin',level=20)
    gear=next(g for g in _gear_envelope('paladin',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
        if {s:int(i['item_id']) for s,i in g['selection'].slots.items()}==ids)
    geared,_=apply_gear_selection(ir,aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()))
    talented,_=apply_talent_selection(geared,old['winner_exact_replay']['talent_allocation'],level=20)
    policy=_policy(old['winner_exact_replay']['policy'])
    def score(heals):
        return evaluate_repeated_pulls(ir_slice=talented,policy=policy,level=20,
            target_health=representative_hp(20),count=3,schedule_incoming_attacks=True,
            apply_target_defense=True,recovery_action_ids=heals)
    all_heals=score(None);old_only=score(('holy_light:647',))
    assert all_heals.seconds_per_mob!=pytest.approx(old_only.seconds_per_mob)
    assert min(all_heals.seconds_per_mob,old_only.seconds_per_mob)>0
    with pytest.raises(ValueError,match='non-healing or unknown'):
        score(('holy_strike:1866',))
    # A true candidate must specify recovery as well as combat policy.
    from src.v2.source_multi_pull_joint import replay_exact_challenger
    replay=replay_exact_challenger(class_key='paladin',level=20,gear=gear,
        allocation=old['winner_exact_replay']['talent_allocation'],policy=policy,
        recovery_action_ids=('holy_light:647',))
    assert replay['seconds_per_mob']==pytest.approx(old_only.seconds_per_mob)
    scored=_score_state(ir,level=20,gear=gear,
        allocation=old['winner_exact_replay']['talent_allocation'],pulls=3,
        policy_cap=8,target_health=representative_hp(20))
    assert scored['recovery_strategy_count']==4
    assert scored['recovery_strategy_coverage']['complete'] is True
    assert scored['seconds_per_mob']<=min(all_heals.seconds_per_mob,
        old_only.seconds_per_mob)+1e-8


def test_actual_short_end_to_end_corridor():
    from src.v2.source_legal_level_corridor import search_source_legal_level_corridor
    result=search_source_legal_level_corridor(class_key='paladin',
        start_level=10,end_level=12,gear_screen_count=1,policy_cap=4,pulls=3)
    assert result['status'].startswith('EVALUATED_BOUNDED')
    assert [s['level'] for s in result['route']]==[10,11,12]
    assert result['route_respecs']==0
    assert all(sum(s['talents'].values())==s['level']-9 for s in result['route'])
    assert result['gear_policy_screened_states']>0 and result['policy_evaluations']>0
    assert result['talent_allocations_pruned']==0
    assert result['source_coverage_complete'] is False


def test_l30_rank_values_flow_into_shared_executable_effects():
    from src.game.model import DamageEffect,WeaponDamageEffect,HealEffect
    ir=build_game_ir_slice(class_key='paladin',level=30)
    strike=_action(ir,'holy_strike')
    weapon=next(e for e in strike.effects if isinstance(e,WeaponDamageEffect))
    holy=next(e for e in strike.effects if isinstance(e,DamageEffect))
    assert weapon.weapon_damage_multiplier==pytest.approx(.36)
    assert (holy.base_min,holy.base_max)==(23,29)
    flash=_action(ir,'flash_of_light')
    assert isinstance(flash.effects[0],HealEffect)
    assert (flash.effects[0].base_min,flash.effects[0].base_max)==(68,77)
    seal=_action(ir,'seal_of_righteousness')
    swing=next(t.effects[0] for t in ir.triggers if t.id.startswith('seal_of_righteousness:swing'))
    judge=next(t.effects[0] for t in ir.triggers if t.id.startswith('seal_of_righteousness:judgement'))
    assert (swing.base_min,swing.base_max)==(8,29)
    assert (judge.base_min,judge.base_max)==(74,80)
    granted,_=apply_talent_selection(ir,{'benediction':5,'conviction':5,'seal_of_command':1},level=30)
    command=next(t.effects[0] for t in granted.triggers if t.id.startswith('seal_of_command:judgement'))
    assert (command.base_min,command.base_max)==(97,104)


def test_older_capture_reingest_cannot_downgrade_weapon_or_level():
    from tools.wf251_ingest_two_classes import ingest
    with sqlite3.connect(DEFAULT_DB) as db:
        before=db.execute('''SELECT weapon_speed_semantics FROM equipped_weapon_mode_source_facts
            WHERE class_key=?''',('paladin',)).fetchone()[0]
        level=db.execute('SELECT max_level FROM verified_native_class_scenarios WHERE class_key=?',('paladin',)).fetchone()[0]
    assert before=='equipped' and level==30
    ingest()
    with sqlite3.connect(DEFAULT_DB) as db:
        after=db.execute('''SELECT weapon_speed_semantics FROM equipped_weapon_mode_source_facts
            WHERE class_key=?''',('paladin',)).fetchone()[0]
        level_after=db.execute('SELECT max_level FROM verified_native_class_scenarios WHERE class_key=?',('paladin',)).fetchone()[0]
    assert (after,level_after)==(before,level)

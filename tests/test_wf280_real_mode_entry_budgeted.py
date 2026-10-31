"""WF280: sourced mode entry is an actually paid ordered-prefix candidate.

This is a bounded mode-family canary, not Feral completeness or a validated
Druid L20 optimum. No source spell/form name is used by the optimizer.
"""
from dataclasses import replace
from math import isfinite
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ModeChangeEffect, PolicyDefinition, PolicyRuleDefinition
from src.v2.source_budgeted_prefix import source_prefix_envelope
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.generic_backend import _policy_combat_evaluation


def search(*, enabled, ir=None, events=3200, attempts=24, cache=False):
    return run_source_stateful_budgeted(class_key='druid', level=20,
        ir_slice=ir, max_l2_attempts=attempts, max_event_transitions=events,
        use_l1=False, use_prefix_cache=cache,
        search_guarded_continuations=True, search_mode_paths=enabled)


def test_mode_entry_is_source_derived_not_free_start():
    ir = build_game_ir_slice(class_key='druid', level=20)
    env = source_prefix_envelope(ir, level=20)
    entries = {row['entry']:row for row in env['mode_paths']}
    assert 'cat_form:768' in entries
    cat = entries['cat_form:768']
    assert cat['mode_id'] == 'cat' and 'claw:20' in cat['fillers']
    assert 'claw:20' not in env['actions']  # cannot cast from initial caster mode
    entry = next(a for a in ir.actions if a.id == cat['entry'])
    assert any(isinstance(effect, ModeChangeEffect) and effect.target_mode_id == cat['mode_id']
               for effect in entry.effects)
    assert any(req['kind'] == 'mode_is' and req['value'] == 'caster'
               for req in entry.requirements)


def test_real_mode_l2_changes_search_and_scratch_replay_matches():
    base = search(enabled=False)
    actual = search(enabled=True)
    assert base['l2_attempts'] == actual['l2_attempts'] == 24
    assert base['mode_l2_attempts'] == 0
    assert actual['mode_l2_attempts'] >= 1
    assert actual['event_transitions'] <= 3200
    assert actual['winner']['score_s_per_mob'] < base['winner']['score_s_per_mob']
    entry_ids = {row['entry'] for row in actual['source_mode_paths']}
    observed = [x for x in actual['observations'] if x.get('tier') == 'L2'
                and x.get('prefix') and x['prefix'][0] in entry_ids]
    assert len(observed) == actual['mode_l2_attempts']
    valid = [x for x in observed if x['status'] == 'FULL_L2_VERIFIED']
    assert valid and all(isfinite(x['score_s_per_mob']) for x in valid)
    assert any(x['prefix'][0] == 'cat_form:768' for x in valid)
    assert actual['scratch_verification']
    assert all(x['matches_scratch'] for x in actual['scratch_verification'])
    assert actual['l0_cpu_ns'] > 0
    assert any(abs(x['l0_predicted_s']-x['score_s_per_mob']) > 1.0 for x in valid)


def test_mode_path_requires_real_transition_and_is_invalidated_by_source_change():
    ir = build_game_ir_slice(class_key='druid', level=20)
    no_entry = replace(ir, actions=tuple(a for a in ir.actions if a.id != 'cat_form:768'))
    assert not any(x['mode_id'] == 'cat' for x in source_prefix_envelope(no_entry,level=20)['mode_paths'])
    actual = search(enabled=True,ir=no_entry,attempts=12,events=1800)
    assert not any(x.get('tier')=='L2' and x.get('prefix') and x['prefix'][0]=='cat_form:768'
                   for x in actual['observations'])
    # The same claw policy without the paid entry action cannot execute.
    pol = PolicyDefinition(id='mode-test',label='Mode test',
        rules=(PolicyRuleDefinition(id='claw',action_id='claw:20'),),
        provenance={'search_performed':True})
    score, execution, details = _policy_combat_evaluation(
        ir,level=20,policy_override=pol,opening_action_ids=('claw:20',),
        schedule_incoming_attacks=True)
    assert score is None or execution is None or not execution.timeline.target_defeated


def test_mode_search_aborts_with_hard_event_cap_and_no_false_score():
    r = search(enabled=True,attempts=12,events=1)
    assert r['event_transitions'] <= 1
    assert r['l2_attempts'] <= 12
    assert r['winner'] is None


def test_cross_class_no_mode_paths_no_extra_candidates():
    ir = build_game_ir_slice(class_key='rogue',level=20)
    env = source_prefix_envelope(ir,level=20)
    assert env['mode_paths'] == ()
    from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
    r = run_source_stateful_budgeted(class_key='rogue',level=20,
        max_l2_attempts=6,max_event_transitions=300,use_l1=False,
        search_mode_paths=True)
    assert r['mode_l2_attempts'] == 0
    assert r['l2_attempts'] <= 6


def test_mode_cache_context_separates_talent_and_matches_scratch():
    from src.game.talents import apply_talent_selection
    base = build_game_ir_slice(class_key='druid',level=20)
    talented, _ = apply_talent_selection(base,{'ferocity':5},level=20)
    kwargs=dict(class_key='druid',level=20,max_l2_attempts=24,
        max_event_transitions=3200,use_l1=False,use_prefix_cache=True,
        search_guarded_continuations=True,search_mode_paths=True)
    first=run_source_stateful_budgeted(ir_slice=base,**kwargs)
    second=run_source_stateful_budgeted(ir_slice=talented,**kwargs)
    assert first['source_context'] != second['source_context']
    assert first['mode_l2_attempts'] and second['mode_l2_attempts']
    assert all(x['matches_scratch'] for x in first['scratch_verification'])
    assert all(x['matches_scratch'] for x in second['scratch_verification'])
    assert first['event_transitions']<=3200 and second['event_transitions']<=3200


def test_mode_l1_is_paid_real_partial_not_terminal_proxy():
    r = run_source_stateful_budgeted(class_key='druid',level=20,
        max_l2_attempts=48,max_event_transitions=6000,use_l1=True,
        use_prefix_cache=True,search_guarded_continuations=True,
        search_mode_paths=True)
    entries = {m['entry'] for m in r['source_mode_paths']}
    mode_l1 = [x for x in r['observations'] if x.get('tier')=='L1'
               and x['prefix'][0] in entries]
    assert mode_l1 and any(x['status']=='PARTIAL_REAL_EXECUTOR' for x in mode_l1)
    assert all(x['events']>0 and x['cpu_ns']>0 for x in mode_l1)
    assert any(x.get('tier')=='L2' and x['prefix'][0] in entries
               and x['status']=='FULL_L2_VERIFIED' for x in r['observations'])
    assert r['event_transitions']<=6000 and r['l2_attempts']<=48
    assert all(x['matches_scratch'] for x in r['scratch_verification'])


def test_mode_only_source_slice_still_gets_real_l2_without_caster_filler():
    ir=build_game_ir_slice(class_key='druid',level=20)
    # Synthetic *coverage gate* only: remove all initial caster damage buttons
    # to prove the optimizer has no hidden requirement for caster offense.
    keep = {'cat_form:768','claw:20','rip:20'}
    narrowed=replace(ir,actions=tuple(a for a in ir.actions if a.id in keep))
    env=source_prefix_envelope(narrowed,level=20)
    assert not env['actions'] and not env['fillers']
    assert env['mode_paths'] and env['mode_paths'][0]['entry']=='cat_form:768'
    r=search(enabled=True,ir=narrowed,attempts=8,events=1200)
    assert r['l2_attempts']>0 and r['mode_l2_attempts']>0
    assert r['winner'] is not None
    assert r['winner']['prefix'][0]=='cat_form:768'
    assert r['event_transitions']<=1200


def test_failed_ordered_prefix_cannot_claim_autoattack_kill_as_success():
    ir=build_game_ir_slice(class_key='druid',level=20)
    bear_only=replace(ir,actions=tuple(a for a in ir.actions
        if a.id in {'bear_form:5487','swipe:16'}))
    r=search(enabled=True,ir=bear_only,attempts=8,events=1200)
    attempts=[x for x in r['observations'] if x.get('tier')=='L2']
    failed=[x for x in attempts if x['prefix']==['bear_form:5487','swipe:16']]
    assert len(failed)==1
    assert failed[0]['status']=='BLOCKED_PREFIX_NOT_EXECUTED'
    assert 'insufficient rage' in failed[0]['reason']
    assert failed[0]['events']>0  # rejected result still pays real work
    assert not any(x['status']=='FULL_L2_VERIFIED' and
                   x['prefix']==['bear_form:5487','swipe:16'] for x in attempts)
    from src.v2.source_budgeted_gear import _fixed_opening_score
    invalid_record={'prefix':['bear_form:5487','swipe:16'],
                    'fallback':'swipe:16','guarded_action':None}
    assert _fixed_opening_score(bear_only,invalid_record,20,True) is None


def test_mode_family_reaches_real_named_gear_search_without_parallel_scorer():
    from src.v2.source_budgeted_gear import run_source_budgeted_gear
    r=run_source_budgeted_gear(class_key='druid',level=20,
        max_evaluations=70,initial_search=24,search_per_gear=24,
        max_gear_states=2,policy_search_backend='stateful',
        max_event_transitions=9000,stateful_use_l1=False,
        stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True)
    assert r['attempted']<=70 and r['event_transitions']<=9000
    naked, geared=r['stages'][:2]
    assert naked['mode_l2_attempts']>0 and geared['mode_l2_attempts']>0
    assert geared['gear']['slots']
    assert geared['winner']['prefix'][0]=='cat_form:768'
    assert geared['winner']['score_s_per_mob'] < naked['winner']['score_s_per_mob']
    assert geared['context_sha256'] != naked['context_sha256']

"""Source-qualified initial-mode auto continuation is a real executor policy.

No synthetic spell/action is added to IR; the existing auto event queue does
all damage. The adaptive search pays the real full-cycle evaluation budget.
"""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_prefix import (
    AUTO_ONLY_FALLBACK, source_prefix_envelope, run_source_budgeted_prefix,
    _verified_auto_fallback)
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_stateful_budgeted import _make_policy


@pytest.mark.parametrize('class_key', ['hunter','paladin','warrior'])
def test_initial_mode_auto_source_unblocks_real_l2_and_scratch(class_key):
    ir=build_game_ir_slice(class_key=class_key,level=20)
    before=run_source_stateful_budgeted(class_key=class_key,level=20,
        ir_slice=ir,max_l2_attempts=24,max_event_transitions=5000,use_l1=False)
    assert before['status']=='BLOCKED_NO_EXECUTABLE_ACTIONS'
    result=run_source_stateful_budgeted(class_key=class_key,level=20,
        ir_slice=ir,max_l2_attempts=50,max_event_transitions=8500,
        use_l1=True,search_auto_fallback=True)
    assert result['status']=='BEST_KNOWN_BOUNDED'
    assert result['winner'] and result['winner']['score_s_per_mob']>0
    assert result['winner']['fallback']==AUTO_ONLY_FALLBACK
    assert result['auto_fallback_ids']
    assert result['l2_attempts']<=50
    assert result['event_transitions']<=8500
    assert result['scratch_verification'] and all(x['matches_scratch'] for x in result['scratch_verification'])
    assert result['l1_attempts']>0
    assert result['winner']['survived']
    # Exact source actions in the opening, no fabricated fallback Action.
    ids={a.id for a in ir.actions}
    assert AUTO_ONLY_FALLBACK not in ids
    assert all(a in ids for a in result['winner']['prefix'])
    assert result['winner']['full_timeline_events']>0


def test_missing_auto_source_or_wrong_mode_is_not_legal_fallback():
    ir=build_game_ir_slice(class_key='hunter',level=20)
    assert _verified_auto_fallback(ir)
    attack=ir.auto_attacks[0]
    no_provenance=replace(ir,auto_attacks=(replace(attack,provenance=()),))
    assert not _verified_auto_fallback(no_provenance)
    assert AUTO_ONLY_FALLBACK not in source_prefix_envelope(no_provenance,
        level=20,include_auto_fallback=True)['fillers']
    wrong_mode=replace(ir,auto_attacks=(replace(attack,required_mode_id='not_the_initial_mode'),))
    assert not _verified_auto_fallback(wrong_mode)
    assert AUTO_ONLY_FALLBACK not in source_prefix_envelope(wrong_mode,
        level=20,include_auto_fallback=True)['fillers']
    # No source auto means the new search does not invent an attack.
    result=run_source_stateful_budgeted(class_key='hunter',level=20,
        ir_slice=no_provenance,max_l2_attempts=12,max_event_transitions=2500,
        use_l1=False,search_auto_fallback=True)
    assert result['status']=='BLOCKED_NO_EXECUTABLE_ACTIONS'


def test_strict_p3_auto_fallback_rejects_paladin_proxy_actor_and_weapon():
    ir=build_game_ir_slice(class_key='paladin',level=20)
    assert ir.actor.metadata['base_stats_are_zero_proxy'] is True

    # The generic exploratory path can see this captured auto, but its
    # provenance explicitly labels both actor/weapon values as proxies.
    exploratory=source_prefix_envelope(
        ir,level=20,include_auto_fallback=True)
    assert AUTO_ONLY_FALLBACK in exploratory['fillers']

    strict=source_prefix_envelope(
        ir,level=20,include_auto_fallback=True,
        require_source_verified_auto=True)
    assert AUTO_ONLY_FALLBACK not in strict['fillers']
    assert strict['auto_fallback_ids']==()
    assert len(strict['auto_fallback_rejections'])==1
    rejection=strict['auto_fallback_rejections'][0]
    assert rejection['id']==ir.auto_attacks[0].id
    assert {
        'actor_base_stats_are_zero_proxy',
        'actor_provenance_declares_proxy',
        'actor_source_identity_missing',
        'auto_provenance_declares_proxy',
    } <= set(rejection['reasons'])
    assert any(row['reason']=='auto_fallback_not_source_verified'
               for row in strict['blocked'])


def test_paladin_l20_p3_prefix_reports_exact_source_naked_fallback_block():
    from src.v2.source_budgeted_gear import run_source_budgeted_gear

    ir=build_game_ir_slice(class_key='paladin',level=20)
    prefix=run_source_budgeted_prefix(
        class_key='paladin',level=20,max_evaluations=12,ir_slice=ir,
        include_auto_fallback=True,require_source_verified_auto=True)
    assert prefix['status']=='BLOCKED_NO_EXECUTABLE_SOURCE_FALLBACK'
    assert prefix['attempted']==0 and prefix['evaluated']==0
    assert 'holy_strike:1866' in prefix['envelope']['actions']
    assert prefix['envelope']['fillers']==()
    assert prefix['envelope']['auto_fallback_ids']==()
    assert prefix['envelope']['auto_fallback_rejections']
    assert any(row['reason']=='auto_fallback_not_source_verified'
               for row in prefix['envelope']['blocked'])

    gear=run_source_budgeted_gear(
        class_key='paladin',level=20,max_evaluations=12,
        initial_search=12,search_per_gear=1,max_gear_states=1,
        probe_stats=('strength',),probe_deltas=(5.,),
        ir_slice=ir,policy_search_backend='prefix',
        prefix_search_auto_fallback=True,
        prefix_require_source_verified_auto=True)
    assert gear['status']=='BLOCKED_NO_NAKED_SUCCESS'
    assert gear['attempted']==0 and gear['evaluated']==0
    assert gear['source_naked_search_status']=='BLOCKED_NO_EXECUTABLE_SOURCE_FALLBACK'
    diagnostic=gear['source_naked_diagnostic']
    assert diagnostic['actions']==prefix['envelope']['actions']
    assert diagnostic['fillers']==()
    assert diagnostic['auto_fallback_rejections']


def test_auto_continuation_uses_real_existing_executor_not_fake_action():
    ir=build_game_ir_slice(class_key='hunter',level=20)
    policy=_make_policy(ir,AUTO_ONLY_FALLBACK)
    assert policy.rules==()
    result, execution, details=_policy_combat_evaluation(ir,level=20,
        policy_override=policy,opening_action_ids=('arcane_shot:14282',),
        schedule_incoming_attacks=True)
    assert result is not None and execution.timeline.target_defeated
    assert execution.timeline.auto_attack_damage>0
    assert details['actor_survived']
    assert any(e.kind=='AutoAttackSwing' for e in execution.timeline.events)

@pytest.mark.parametrize('class_key', ['hunter','paladin'])
def test_same_auto_continuation_reoptimizes_named_gear_and_talent_root(class_key):
    from src.v2.source_budgeted_gear import run_source_budgeted_gear
    from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
    opts=dict(class_key=class_key,level=20,max_evaluations=45,
        initial_search=22,search_per_gear=12,max_gear_states=2,
        probe_stats=('agility','strength','stamina'),probe_deltas=(5,),
        policy_search_backend='stateful',stateful_search_auto_fallback=True,
        stateful_use_l1=False,max_event_transitions=7000,
        required_level_policy='observed')
    gear=run_source_budgeted_gear(**opts)
    assert gear['status']=='EVALUATED_BOUNDED'
    assert gear['event_transitions']<=7000
    assert any(s['stage'].startswith('named_gear_') and s['winner']
               for s in gear['stages'])
    assert all(s['winner']['fallback']==AUTO_ONLY_FALLBACK
               for s in gear['stages'] if s['winner'])
    # The same source-legal auto continuation must also survive the talent
    # wrapper; the old code used to stop before its very first L2 call.
    joint=run_source_budgeted_joint_talents(**{
        **opts,'max_evaluations':48,'evaluations_per_talent':36,
        'initial_search':20,'search_per_gear':10})
    assert joint['status']=='EVALUATED_BOUNDED'
    assert joint['event_transitions']<=7000
    assert joint['winner']['score_s_per_mob']>0
    assert joint['winner']['gear_policy_result']['winner']['winner']['fallback']==AUTO_ONLY_FALLBACK

def test_data_only_source_auto_damage_changes_real_combat_score():
    ir=build_game_ir_slice(class_key='hunter',level=20)
    policy=_make_policy(ir,AUTO_ONLY_FALLBACK)
    baseline,_,_=_policy_combat_evaluation(ir,level=20,policy_override=policy,
        opening_action_ids=('arcane_shot:14282',),schedule_incoming_attacks=True)
    assert baseline is not None
    auto=ir.auto_attacks[0]
    changed_source=replace(auto.damage_source,flat_dps=auto.damage_source.flat_dps*1.5)
    changed_ir=replace(ir,auto_attacks=(replace(auto,damage_source=changed_source),*ir.auto_attacks[1:]))
    changed,execution,_=_policy_combat_evaluation(changed_ir,level=20,
        policy_override=policy,opening_action_ids=('arcane_shot:14282',),
        schedule_incoming_attacks=True)
    assert changed is not None and execution.timeline.target_defeated
    assert changed.seconds_per_mob < baseline.seconds_per_mob

@pytest.mark.parametrize('class_key', ['hunter','paladin','warrior'])
def test_auto_fallback_cached_prefix_matches_fresh_full_cycle(class_key):
    result=run_source_stateful_budgeted(class_key=class_key,level=20,
        max_l2_attempts=30,max_event_transitions=6000,use_l1=True,
        use_prefix_cache=True,search_auto_fallback=True)
    assert result['status']=='BEST_KNOWN_BOUNDED'
    assert result['cache_hits_l2']>0
    assert result['verification_complete']
    assert all(row['matches_scratch'] for row in result['scratch_verification'])
    assert result['event_transitions']<=6000

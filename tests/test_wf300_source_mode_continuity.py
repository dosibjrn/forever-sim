"""Cross-pull mode opening is a sourced state predicate, not a free recast."""
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp

@pytest.mark.parametrize('class_key,level,mode,entry', [
    ('druid',20,'cat','cat_form:768'),
    ('druid',20,'bear','bear_form:5487'),
    ('warrior',20,'defensive','stance:defensive:71'),
    ('shaman',20,'rockbiter','rockbiter:8019'),
])
def test_already_active_sourced_mode_entry_is_not_recast(class_key,level,mode,entry):
    ir=build_game_ir_slice(class_key=class_key,level=level)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode(mode)
    start_time=actor.current_time_s
    resources=dict(actor.resources)
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('canary',1.0))
    policy=PolicyDefinition(id='empty-fallback',label='empty',rules=())
    result=execute_priority_policy(policy=policy,actions=ir.actions,runtime=runtime,
                opening_action_ids=(entry,),skip_satisfied_mode_opening=True,max_actions=12)
    assert result.satisfied_mode_opening_ids == (entry,)
    assert all(x['action_id'] != entry for x in result.selected_actions)
    assert actor.current_mode_id == mode


def test_disabled_non_mode_opening_is_never_silently_skipped():
    ir=build_game_ir_slice(class_key='druid',level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('cat')
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('canary',500.0))
    result=execute_priority_policy(policy=PolicyDefinition(id='empty',label='empty',rules=()),
            actions=ir.actions,runtime=runtime,opening_action_ids=('wrath:5178',),
            skip_satisfied_mode_opening=True,max_actions=4)
    assert result.stopped_reason.startswith('BLOCKED_PREFIX_ELIGIBILITY')
    assert result.satisfied_mode_opening_ids == ()


def test_strict_default_preserved_and_checkpoint_incompatible_with_conditional_skip():
    ir=build_game_ir_slice(class_key='druid',level=20)
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('cat')
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('canary',500.0))
    policy=PolicyDefinition(id='empty',label='empty',rules=())
    result=execute_priority_policy(policy=policy,actions=ir.actions,runtime=runtime,
                opening_action_ids=('cat_form:768',),max_actions=4)
    assert result.stopped_reason.startswith('BLOCKED_PREFIX_ELIGIBILITY')
    with pytest.raises(ValueError,match='cannot resume'):
        execute_priority_policy(policy=policy,actions=ir.actions,runtime=runtime,
                opening_action_ids=('cat_form:768',),skip_satisfied_mode_opening=True,
                stop_after_opening_actions=1)


def test_source_druid_100_continuous_pulls_no_reset_or_mode_recast():
    ir=build_game_ir_slice(class_key='druid',level=20)
    result=evaluate_repeated_pulls(ir_slice=ir,policy=ir.policies[1],level=20,
        target_health=representative_hp(20),count=100,
        opening_action_ids=('cat_form:768',))
    assert len(result.pulls)==100
    assert result.pulls[0]['satisfied_mode_opening_ids']==[]
    assert all(p['satisfied_mode_opening_ids']==['cat_form:768'] for p in result.pulls[1:])
    assert all(p['event_transitions']>0 for p in result.pulls)


def test_auto_only_source_companions_are_legal_but_unbacked_pet_is_blocked():
    from dataclasses import replace
    from src.v2.source_companion_policy_search import companion_policy_envelope
    for cls in ('shaman','warlock'):
        ir=build_game_ir_slice(class_key=cls,level=20)
        options, coverage=companion_policy_envelope(ir)
        assert len(options)==1
        assert coverage['sourced_auto_attack_ids']
        assert list(options[0].values())[0].rules==()
        with pytest.raises(ValueError,match='neither sourced skill nor sourced auto attack'):
            companion_policy_envelope(replace(ir,auto_attacks=()))


def test_shaman_source_totem_is_executable_across_two_pulls():
    from src.v2.source_companion_policy_search import companion_policy_envelope
    ir=build_game_ir_slice(class_key='shaman',level=20)
    variants,_=companion_policy_envelope(ir)
    result=evaluate_repeated_pulls(ir_slice=ir,policy=ir.policies[0],level=20,
        target_health=representative_hp(20),count=2,
        companion_policy_override=variants[0],apply_target_defense=True)
    assert len(result.pulls)==2
    assert all(p['event_transitions']>0 for p in result.pulls)


def test_warlock_dies_fail_closed_instead_of_hanging_at_iteration_cap():
    from src.v2.source_companion_policy_search import companion_policy_envelope
    ir=build_game_ir_slice(class_key='warlock',level=20)
    variants,_=companion_policy_envelope(ir)
    with pytest.raises(ValueError,match='actor_died'):
        evaluate_repeated_pulls(ir_slice=ir,policy=ir.policies[0],level=20,
            target_health=representative_hp(20),count=2,
            companion_policy_override=variants[0],apply_target_defense=True)

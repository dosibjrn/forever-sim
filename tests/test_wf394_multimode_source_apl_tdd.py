"""WF394 RED: source-derived combat form cycle must reach canonical paid evaluator."""
from pathlib import Path
import json

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ModeChangeEffect, HealEffect, PeriodicHealEffect
from src.game.policy_evolution import _identity, _validated
from src.v2.source_bounded_joint_frontier import source_joint_policy_frontier

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
STAGE=ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json'


def _source():
    return (build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB),
            json.loads(STAGE.read_text()))


def _cycles(ir,stage):
    return [(label,p) for label,p in source_joint_policy_frontier(ir,stage,max_policies=16,include_mode_cycles=True)
            if label=='mode_cycle']


def test_form_cycle_is_discovered_from_source_without_legacy_seed():
    ir,stage=_source()
    cycles=_cycles(ir,stage)
    assert cycles, 'the joint frontier must consider a legal combat form-cycle APL'
    action_by_id={a.id:a for a in ir.actions}
    assert any(len(p.rules)>=4 for _,p in cycles)
    assert len({_identity(p) for _,p in cycles})==len(cycles)
    for _,policy in cycles:
        _validated(policy,ir.actions)
        ids=[r.action_id for r in policy.rules]
        assert all(action_by_id[x].owner_actor_id==ir.actor.id for x in ids)
        effects=[e for x in ids for e in action_by_id[x].effects]
        assert sum(isinstance(e,ModeChangeEffect) for e in effects)>=2
        assert any(isinstance(e,(HealEffect,PeriodicHealEffect)) for e in effects)
        assert any(any(c.kind=='mode_state' for c in rule.conditions) for rule in policy.rules)
        assert any(any(c.kind=='actor_state' and c.field=='health_pct'
                       for c in rule.conditions) for rule in policy.rules)


def test_form_cycle_has_hp_hysteresis_and_mode_guards_no_form_spam():
    ir,stage=_source()
    _,policy=_cycles(ir,stage)[0]
    by_id={a.id:a for a in ir.actions}
    exits=[r for r in policy.rules if any(isinstance(e,ModeChangeEffect)
            and e.target_mode_id=='caster' for e in by_id[r.action_id].effects)]
    reentries=[r for r in policy.rules if any(isinstance(e,ModeChangeEffect)
            and e.target_mode_id=='cat' for e in by_id[r.action_id].effects)]
    assert exits and reentries
    assert any(c.kind=='mode_state' and c.value=='cat' for c in exits[0].conditions)
    assert any(c.kind=='mode_state' and c.value=='caster' for c in reentries[0].conditions)
    low=[float(c.value) for c in exits[0].conditions
         if c.kind=='actor_state' and c.field=='health_pct' and c.operator=='lte']
    high=[float(c.value) for c in reentries[0].conditions
          if c.kind=='actor_state' and c.field=='health_pct' and c.operator=='gte']
    assert low and high and 0 < low[0] < high[0] < 1


def test_low_health_combat_executes_sourced_exit_heal_reentry_and_damage():
    """Actual CombatRuntime event/action path, not only structural APL proof."""
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.v2.source_persistent_joint_finalists import prepare_candidate
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.policy import execute_priority_policy
    from src.shared.leveling.objective import representative_hp

    ir,stage=_source()
    compiled,_=compile_talent_runtime(ir)
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        source_ir=compiled,allow_partial_gear_stats=True)
    _,policy=_cycles(compiled,stage)[0]
    actor=ActorState.from_ir(candidate.ir.actor,candidate.ir.resources,candidate.ir.modes)
    actor.resources['health']=actor.resource_capacity['health']*.25
    target=TargetState.with_health('source_diagnostic',representative_hp(30))
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=candidate.ir.auto_attacks,
        incoming_attacks=candidate.ir.incoming_attacks,
        mitigation_rules=candidate.ir.mitigation_rules,triggers=candidate.ir.triggers)
    result=execute_priority_policy(policy=policy,actions=candidate.ir.actions,
        runtime=runtime,opening_action_ids=candidate.opening,max_actions=100)
    ids=[row['action_id'] for row in result.selected_actions]
    by_id={a.id:a for a in candidate.ir.actions}
    exits=[i for i,x in enumerate(ids) if any(isinstance(e,ModeChangeEffect)
            and e.target_mode_id=='caster' for e in by_id[x].effects)]
    heals=[i for i,x in enumerate(ids) if any(isinstance(e,(HealEffect,PeriodicHealEffect))
            for e in by_id[x].effects)]
    reentries=[i for i,x in enumerate(ids) if any(isinstance(e,ModeChangeEffect)
            and e.target_mode_id=='cat' for e in by_id[x].effects)]
    assert result.timeline.target_defeated and not result.stopped_reason
    assert exits and heals and reentries
    assert min(exits)<min(heals)<max(reentries)
    assert actor.current_mode_id=='cat'
    assert actor.resources['health']>0


def test_form_cycle_paid_threshold_recovery_completes_100_mobs_with_safe_threshold():
    """The between-pull target mode comes from source policy, not last kill mode."""
    from dataclasses import replace
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
    from src.game.recovery_between_pulls import BetweenPullPolicy

    ir,stage=_source()
    compiled,_=compile_talent_runtime(ir)
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        source_ir=compiled,allow_partial_gear_stats=True)
    _,policy=_cycles(compiled,stage)[0]
    exits=[a.id for a in compiled.actions if any(isinstance(e,ModeChangeEffect)
             and e.target_mode_id=='caster' for e in a.effects)
             and any(req.get('kind')=='mode_is' and req.get('value')=='cat'
                     for req in a.requirements)]
    entries=[a.id for a in compiled.actions if any(isinstance(e,ModeChangeEffect)
             and e.target_mode_id=='cat' for e in a.effects)
             and any(req.get('kind')=='mode_is' and req.get('value')=='caster'
                     for req in a.requirements)]
    assert exits and entries
    recovery=BetweenPullPolicy(health_fraction=.50,mana_fraction=.10,
        exit_action_id=exits[0],reentry_action_id=entries[0])
    result=evaluate_persistent_candidate(replace(candidate,policy=policy),
        level=30,mobs=100,recovery_policy=recovery,max_cpu_s=12,max_wall_s=12)
    assert result['status']=='COMPLETE',result
    assert result['count']==100 and result['events']>0


def test_recovery_reenters_sourced_next_pull_mode_even_when_kill_ended_in_caster():
    from src.game.runtime import ActorState
    from src.game.recovery_between_pulls import BetweenPullPolicy, between_pull_recovery
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.v2.source_persistent_joint_finalists import prepare_candidate

    ir,stage=_source()
    compiled,_=compile_talent_runtime(ir)
    candidate=prepare_candidate(class_key='druid',level=30,stage=stage,
        source_ir=compiled,allow_partial_gear_stats=True)
    actor=ActorState.from_ir(candidate.ir.actor,candidate.ir.resources,candidate.ir.modes)
    assert actor.current_mode_id=='caster'
    actor.resources['health']=actor.resource_capacity['health']*.25
    policy=BetweenPullPolicy(health_fraction=.30,mana_fraction=.10,
        exit_action_id='cancel_mode:cat',reentry_action_id='cat_form:768')
    result=between_pull_recovery(ir=candidate.ir,actor=actor,level=30,
        mob_index=0,mob_count=2,policy=policy)
    assert result['full_recovery']
    assert result['actions']==['cat_form:768']
    assert actor.current_mode_id=='cat'
    assert result['elapsed_s']>0 and result['events']>0
    assert actor.resource_amount('mana')<actor.resource_capacity['mana']

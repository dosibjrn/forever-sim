from dataclasses import replace,dataclass
from types import SimpleNamespace
import pytest

from src.game.model import (PolicyCondition, PolicyRuleDefinition, PolicyDefinition,ActionDefinition,
                            ActorDefinition,ResourceCost)
from src.game.policy_evolution import (scratch_policies,mutations,from_source_rules,
                            search_evolved_policies,_identity)
from src.game.policy import condition_matches
from src.v2.source_persistent_policy_neighborhood import refine_source_policy_persistent


def action(aid, cost=0):
    # Effect only needs to be a source-executable stub for policy synthesis;
    # this test does NOT claim a simulated 100-mob result from dummy effect.
    return ActionDefinition(id=aid,family_key=aid,name=aid,
            owner_actor_id='player',requirements=(),
            costs=(ResourceCost(resource_id='rage',amount=cost),) if cost else (),
            cast_time_s=0.,gcd_s=1.5,cooldown_s=0.,effects=(SimpleNamespace(),),
            provenance=({'authority':'test_generated_source_action'},))


def fake_ir():
    return SimpleNamespace(id='fake:IR',actor=ActorDefinition('player','player'),
        actions=(action('primal_bite',20),action('swipe',10),action('maul',15),action('auto_filler')),
        auto_attacks=(SimpleNamespace(id='auto'),))


def test_scratch_no_seed_and_all_sourced_actions_admitted():
    ir=fake_ir();policies=scratch_policies(ir,max_candidates=32)
    ids={r.action_id for p in policies for r in p.rules}
    assert ids=={a.id for a in ir.actions}
    assert all(p.provenance['origin']=='scratch_generated' for p in policies)
    assert len({_identity(p) for p in policies})==len(policies)


def test_mutations_cover_multiple_structural_and_numeric_families_not_just_insert():
    ir=fake_ir();p=from_source_rules(ir,(
        ('primal_bite',(PolicyCondition(kind='resource_threshold',resource_id='rage',value=20.,operator='gte'),)),
        ('swipe',(PolicyCondition(kind='target_state',field='health_pct',operator='gte',value=.5),)),
        ('maul',()),))
    children=mutations(p,ir,max_candidates=18)
    reasons={c.provenance['mutation'] for c in children}
    assert {'insert_action','remove_action','swap_adjacent','replace_action','adjust_resource_gate','adjust_health_gate'} <= reasons
    assert len({_identity(c) for c in children})==len(children)
    assert all(all(r.action_id in {a.id for a in ir.actions} for r in c.rules) for c in children)


def test_illegal_action_rejected_and_non_source_import_fails_closed():
    ir=fake_ir()
    with pytest.raises(ValueError,match='NON_SOURCE_ACTION'):
        from_source_rules(ir,(('unknown_spell',()),))


def test_actor_health_conditions_have_actual_ratio_and_missing_capacity_fails_closed():
    class Actor:
        resource_capacity={'health':100.}
        def resource_amount(self,key):return {'health':24.}.get(key)
    runtime=SimpleNamespace(actor=Actor())
    cond=PolicyCondition(kind='actor_state',field='health_pct',operator='lt',value=.25)
    assert condition_matches(cond,action=action('heal'),runtime=runtime)
    cond=replace(cond,value=.2)
    assert not condition_matches(cond,action=action('heal'),runtime=runtime)
    runtime.actor.resource_capacity={}
    with pytest.raises(ValueError,match='capacity unavailable'):
        condition_matches(cond,action=action('heal'),runtime=runtime)


def test_spatial_predicate_no_faked_single_target_count():
    cond=PolicyCondition(kind='enemy_count',field='in_range',operator='gte',value=2)
    a=action('swipe');runtime=SimpleNamespace()
    with pytest.raises(ValueError,match='SIMULTANEOUS_2D'):
        condition_matches(cond,action=a,runtime=runtime)
    runtime.spatial_context={'simultaneous_2d':True,'enemy_count_in_range':3}
    assert condition_matches(cond,action=a,runtime=runtime)
    runtime.spatial_context['enemy_count_in_range']=1
    assert not condition_matches(cond,action=a,runtime=runtime)


def test_real_objective_only_complete_valid_100mob_trials_wins():
    ir=fake_ir()
    def evaluator(p):
        ids=[r.action_id for r in p.rules]
        if not ids:return {'status':'BLOCKED_NO_DAMAGE'}
        if ids[0]=='primal_bite':return {'status':'COMPLETE','mean_s_per_mob':12.,'mob_completed':100}
        if ids[0]=='swipe':return {'status':'COMPLETE','mean_s_per_mob':18.,'mob_completed':100}
        return {'status':'BLOCKED_100MOB_NOT_COMPLETE','mean_s_per_mob':1.}
    results=search_evolved_policies(ir,evaluate=evaluator,budget=14)
    assert results.winner is not None and results.winner.rules[0].action_id=='primal_bite'
    assert results.valid < results.candidates
    assert results.metric=='actual_100mob_seconds_per_mob'


def test_persistent_refinement_calls_existing_evaluator_for_two_and_hundred(monkeypatch):
    ir=fake_ir();parent=from_source_rules(ir,(('swipe',()),))
    @dataclass(frozen=True)
    class PreparedStub:
        ir:object
        policy:object
        opening:tuple=()
        allocation:object=None
        source_stage:object=None
    candidate=PreparedStub(ir=ir,policy=parent)
    calls=[]
    def evaluate(c,*,mobs,**kwargs):
        calls.append((c.policy.rules[0].action_id if c.policy.rules else 'auto',mobs))
        score=17. if c.policy.rules and c.policy.rules[0].action_id=='primal_bite' else 19.
        return {'status':'COMPLETE','mean_s_per_mob':score,'mob_completed':mobs,'events':42}
    monkeypatch.setattr('src.v2.source_persistent_policy_neighborhood.evaluate_persistent_candidate',evaluate)
    outcome=refine_source_policy_persistent(candidate,level=30,recovery_policy=None,
              max_proposals=10,max_finalists=2,max_total_wall_s=15.,max_screen_wall_s=.01,
              max_finalist_wall_s=.01,baseline_100mob={'status':'COMPLETE','mean_s_per_mob':19.,'count':100,'events':100})
    assert outcome['winner'] is not None and outcome['winner']['result']['mean_s_per_mob']<=19.
    assert all(n in (2,100) for _,n in calls)
    assert any(n==100 for _,n in calls)
    assert outcome['actual_objective'].startswith('100 consecutive')


def test_source_derived_combo_healing_and_periodic_guards():
    from src.game.model import ResourceScaledDirectDamageEffect,HealEffect,PeriodicEffect
    from src.game.policy_evolution import _semantic_guards
    finisher=replace(action('finisher'),effects=(ResourceScaledDirectDamageEffect(
        effect_type='resource_scaled_direct_damage',school='physical',target='enemy',
        resource_id='combo_points',resource_scope='target',
        base_min_by_resource_amount={1:10,2:20,3:40,4:55,5:70},
        base_max_by_resource_amount={1:20,2:30,3:50,4:65,5:80}),))
    heal=replace(action('heal'),effects=(HealEffect(effect_type='heal',target='actor',
                              resource_id='health',base_min=20,base_max=30),))
    dot=replace(action('dot'),effects=(PeriodicEffect(effect_type='periodic',school='nature',
               target='enemy',aura_id='source:dot',total_base_damage=100,
               duration_s=12,tick_interval_s=2),))
    assert any(c.resource_id=='combo_points' and c.value==1 for c in _semantic_guards(finisher))
    assert any(c.kind=='actor_state' and c.field=='health_pct' for c in _semantic_guards(heal))
    assert any(c.kind=='aura_missing' and c.aura_id=='source:dot' for c in _semantic_guards(dot))


def test_scratch_priority_policy_executes_real_combatruntime():
    from src.game.model import ResourceDefinition,DamageEffect
    from src.game.runtime import ActorState,CombatRuntime,TargetState
    from src.game.policy import execute_priority_policy
    ir=fake_ir()
    damage=DamageEffect(effect_type='damage',school='nature',target='enemy',
                        base_min=15.,base_max=15.)
    source=replace(action('source:shot'),effects=(damage,))
    ir.actions=(source,)
    ir.resources=(ResourceDefinition('health','Health','player',initial_amount=100.,capacity=100.),)
    ir.auto_attacks=()
    candidate=scratch_policies(ir,max_candidates=2)[0]
    actor=ActorState.from_ir(ir.actor,ir.resources)
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('real-target',30))
    result=execute_priority_policy(policy=candidate,actions=ir.actions,
                                   runtime=runtime,max_actions=12)
    assert result.timeline.target_defeated
    assert len(result.selected_actions)==2
    assert runtime.actor.current_time_s==pytest.approx(1.5)

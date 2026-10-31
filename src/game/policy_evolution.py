"""Source-data-only generation and local evolution of canonical Action Priority Lists.

The combat executor is src.game.policy; this module produces *only* Policy IR.
Actions, costs, resource ids, availability and effects come from current GameIR.
Reference builds may seed this search only if separately and explicitly supplied.
A scratch search needs no historical build. No class, spell or talent IDs here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from math import isfinite
from typing import Callable, Iterable

from src.game.model import (PolicyCondition, PolicyDefinition, PolicyRuleDefinition,
    ResourceScaledDirectDamageEffect, ResourceScaledPeriodicEffect, HealEffect,
    PeriodicHealEffect, PeriodicEffect, DamageEffect, WeaponDamageEffect, ControlEffect)

MAX_RULES = 8
VALID_OPS = frozenset({'eq','ne','gt','gte','lt','lte'})
EXPLICIT_NUMERIC_PROXY_GAPS = frozenset({
    ('explicit_gap', 'semantic', 'attack_power_scaling'),
    ('explicit_approximation', 'code', 'approximate_tuning_magnitude'),
})


def _identity(policy: PolicyDefinition) -> str:
    data = [(r.phase,r.action_id,[c.as_dict() for c in r.conditions]) for r in policy.rules]
    return sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()[:16]



def _source_effect_proxy_executable(effect) -> bool:
    """A supported typed runtime effect is a legal *candidate* even when its
    source numerics/secondary semantics remain approximate.

    The approximation ledger remains attached to the source APL. P4/P5/P6
    must evaluate actual runtime behaviour; P1 must not silently remove a
    playable action simply because a secondary detail awaits verification.
    Unknown semantic statuses and unknown effect executor types fail closed.
    """
    from src.game.runtime.effect_capabilities import effect_capability
    if effect_capability(effect) is None:
        return False
    gaps = getattr(effect, 'unsupported_semantics', ())
    if not gaps:
        return True
    supported_documented_statuses = frozenset({
        'explicit_gap', 'explicit_approximation', 'not_yet_modeled',
        'conservative_same_index_family_not_server_verified',
        'legacy_transcription_pending_independent_verification',
    })
    return all(isinstance(gap, dict) and gap.get('status') in supported_documented_statuses
               for gap in gaps)




def _source_effect_notes(action_id: str, index: int, effect) -> list[dict]:
    return [{'action_id': action_id, 'effect_index': index,
             'source_record': dict(record)}
            for record in getattr(effect, 'unsupported_semantics', ())]


def source_policy_uncertainties(policy: PolicyDefinition, actions, *, extra_action_ids=()) -> list[dict]:
    """Surface declared numeric gaps in every scored source APL."""
    selected = {rule.action_id for rule in policy.rules} | set(extra_action_ids)
    notes = []
    for action in actions:
        if action.id not in selected:
            continue
        for index, effect in enumerate(action.effects):
            notes.extend(_source_effect_notes(action.id, index, effect))
    return notes


def _validated(policy: PolicyDefinition, actions, *, max_rules: int = MAX_RULES) -> PolicyDefinition:
    allowed = {a.id: a for a in actions}
    if not (0 <= len(policy.rules) <= max_rules):
        raise ValueError('POLICY_RULE_CAP_EXCEEDED')
    for rule in policy.rules:
        if rule.phase not in ('combat','prepull'):
            raise ValueError('UNSUPPORTED_POLICY_PHASE')
        if rule.action_id not in allowed:
            raise ValueError('POLICY_REFERENCES_NON_SOURCE_ACTION:'+str(rule.action_id))
        if any(not _source_effect_proxy_executable(effect) for effect in allowed[rule.action_id].effects):
            raise ValueError('POLICY_REFERENCES_UNEXECUTABLE_SOURCE_EFFECT')
        for cond in rule.conditions:
            if cond.operator is not None and cond.operator not in VALID_OPS:
                raise ValueError('UNSUPPORTED_POLICY_OPERATOR')
            if cond.kind not in ('resource_threshold','target_state','actor_state','aura_present',
                                 'aura_missing','mode_state','target_control_missing','enemy_count','target_distance','cooldown_ready','stored_cast_charges'):
                raise ValueError('UNSUPPORTED_POLICY_CONDITION:'+cond.kind)
            if cond.kind == 'stored_cast_charges':
                source=allowed[rule.action_id].metadata.get('source_cast_charge_consumer') or {}
                if (cond.field != source.get('bank_id') or type(cond.value) not in (int,float)
                        or not 0 <= float(cond.value) <= 16):
                    raise ValueError('UNKNOWN_SOURCE_CHARGE_BANK')
            if cond.kind == 'cooldown_ready':
                if cond.field not in allowed:
                    raise ValueError('COOLDOWN_UNKNOWN_SOURCE_ACTION:' + str(cond.field))
                if type(cond.value) is not bool or (cond.operator or 'eq') not in ('eq','ne'):
                    raise ValueError('COOLDOWN_INVALID_BOOLEAN_PREDICATE')
            if cond.kind in ('enemy_count','target_distance'):
                # Do not turn unavailable 2D simultaneous-pack combat into a
                # fabricated one-target estimate. Runtime checks it explicitly.
                if not isfinite(float(cond.value)):
                    raise ValueError('NONFINITE_SPATIAL_CONDITION')
            if cond.kind in ('actor_state','target_state') and cond.field not in ('health','health_pct','alive'):
                raise ValueError('UNSUPPORTED_HEALTH_PREDICATE')
    return policy


def from_source_rules(ir, rules: Iterable[tuple[str, tuple[PolicyCondition,...]]],
                      *, provenance: str = 'scratch_generated') -> PolicyDefinition:
    """Create a legal, backend-native APL, not a copy of a legacy rotation."""
    rules=tuple(rules)
    action_map={a.id:a for a in ir.actions}
    policy=PolicyDefinition(
        id=ir.id+':apl:'+provenance,
        label='Source-generated adaptive priority list',
        rules=tuple(PolicyRuleDefinition(id='apl:'+str(i), action_id=action_id,
                        phase=('prepull' if action_map[action_id].metadata.get('stealth_precombat') else 'combat'),
                        conditions=tuple(conditions), provenance={'origin':provenance})
                    for i,(action_id,conditions) in enumerate(rules)),
        provenance={'authority':'generic_policy_evolution','origin':provenance,
                    'source_game_ir':ir.id,'source_policy_seeded':False})
    if any(a.owner_actor_id!=ir.actor.id for a in ir.actions
           if a.id in {r.action_id for r in policy.rules}):
        raise ValueError('POLICY_REFERENCES_NON_PLAYER_ACTION')
    return _validated(policy,ir.actions)


def _cost_gates(action) -> tuple[PolicyCondition,...]:
    return tuple(PolicyCondition(kind='resource_threshold',resource_id=cost.resource_id,
                operator='gte',threshold_source='action_cost')
                 for cost in action.costs if float(cost.amount)>0.)


def _hostile_control(effect) -> bool:
    """A sourced control may affect one enemy or a verified hostile area."""
    return isinstance(effect, ControlEffect) and effect.target in ('enemy', 'enemies')


def _semantic_guards(action) -> tuple[PolicyCondition,...]:
    """Useful source-derived conditions, not a hardcoded class rotation."""
    conditions=list(_cost_gates(action))
    for effect in action.effects:
        if _hostile_control(effect):
            conditions.append(PolicyCondition(kind='target_control_missing', value=effect.control_id))
        if isinstance(effect, ResourceScaledDirectDamageEffect):
            amounts=set(effect.base_min_by_resource_amount)&set(effect.base_max_by_resource_amount)
            if amounts:
                conditions.append(PolicyCondition(kind='resource_threshold',
                    resource_id=effect.resource_id,operator='gte',value=float(min(amounts))))
        if isinstance(effect, ResourceScaledPeriodicEffect):
            amounts=set(effect.total_base_damage_by_resource_amount)
            if amounts:
                conditions.append(PolicyCondition(kind='resource_threshold',
                    resource_id=effect.resource_id,operator='gte',value=float(min(amounts))))
        if isinstance(effect,(HealEffect,PeriodicHealEffect)) and effect.target in ('actor','self'):
            conditions.append(PolicyCondition(kind='actor_state',field='health_pct',
                                             operator='lte',value=.5))
        if isinstance(effect,(PeriodicEffect,ResourceScaledPeriodicEffect)):
            conditions.append(PolicyCondition(kind='aura_missing',scope='target',
                                             aura_id=effect.aura_id))
    unique={}
    for c in conditions:
        key=(c.kind,c.resource_id,c.scope,c.aura_id,c.field,c.value if c.kind == "target_control_missing" else None)
        unique[key]=c
    return tuple(unique.values())


def scratch_policies(ir, *, max_candidates: int=64, max_rules:int=MAX_RULES,
                     opening_ids:tuple[str,...]=()) -> tuple[PolicyDefinition,...]:
    """Round-robin every source action BEFORE deepening; includes auto-only.

    No ability whitelist and no inherited preset. A small bound cannot erase
    later actions simply because the first action yielded more combinations.
    Candidate scores are unknown until paid execution.
    """
    if max_candidates<1 or max_rules<1: raise ValueError('INVALID_POLICY_BUDGET')
    actions=tuple(a for a in ir.actions if a.owner_actor_id==ir.actor.id and a.effects and
                  all(_source_effect_proxy_executable(e) for e in a.effects))
    actions=tuple(sorted(actions,key=lambda a:a.id))
    candidates=[];seen=set()
    def emit(spec):
        if len(candidates)>=max_candidates:return
        p=from_source_rules(ir,spec)
        sig=_identity(p)
        if sig not in seen:
            seen.add(sig);candidates.append(p)
    # A resource-neutral no-cast policy can be valid with sourced auto-attacks.
    if ir.auto_attacks:emit(())
    # Every legal action gets coverage without arbitrary spell-derived weights.
    for action in actions:
        emit(((action.id,_semantic_guards(action)),))
        if len(candidates)>=max_candidates:break
    # Add contingent versions, anchored on source cost; leave actual resource
    # feasibility to existing policy action_eligibility and CombatRuntime.
    for action in actions:
        if len(candidates)>=max_candidates: break
        if _semantic_guards(action):emit(((action.id,()),))
    # Two-action priorities add meaningful options without factorial explosion.
    for i,action in enumerate(actions):
        if len(candidates)>=max_candidates:break
        for other in actions:
            if len(candidates)>=max_candidates:break
            if other.id!=action.id and max_rules>=2:
                emit(((action.id,_semantic_guards(action)),(other.id,_semantic_guards(other))))
    return tuple(candidates)


def _make_child(seed, rules, operation, actions, *, max_rules:int=MAX_RULES):
    base=replace(seed, rules=tuple(replace(rule,id=f'apl:{i}') for i,rule in enumerate(rules)))
    _validated(base,actions,max_rules=max_rules)
    digest=_identity(base)
    return replace(base,id=f'{seed.id}:evolve:{digest}',
                   label='Mutated adaptive priority policy',
                   provenance={**dict(seed.provenance),'authority':'generic_policy_evolution',
                               'parent_policy_id':seed.id,'mutation':operation,
                               'candidate_id':digest,'source_game_ir':seed.provenance.get('source_game_ir')})


def mutations(seed:PolicyDefinition,ir,*,max_candidates:int=64,
              max_rules:int=MAX_RULES) -> tuple[PolicyDefinition,...]:
    """Local priority edits: insert/delete/swap/move/change action/change gates.

    Unrelated actions are not silently ignored: each must exist in the current
    sourced GameIR. No unsupported condition is silently reinterpreted.
    """
    if max_candidates<1 or max_rules<1:raise ValueError('INVALID_MUTATION_BUDGET')
    _validated(seed,ir.actions,max_rules=max_rules)
    actions=tuple(sorted((a for a in ir.actions if a.owner_actor_id==ir.actor.id and a.effects and
                         all(_source_effect_proxy_executable(e) for e in a.effects)),key=lambda a:a.id))
    rules=list(seed.rules)
    buckets={};order=[];seen={_identity(seed)}
    def add(edit,why):
        if not edit and not ir.auto_attacks:return
        try:p=_make_child(seed,edit,why,ir.actions,max_rules=max_rules)
        except ValueError:return
        sig=_identity(p)
        if sig not in seen:
            seen.add(sig)
            if why not in buckets:
                buckets[why]=[];order.append(why)
            buckets[why].append(p)
    # Always support primitive changes before numeric tweaks. Prioritize wide
    # semantic exploration over hundreds of near-identical thresholds.
    if len(rules)<max_rules:
        for action in actions:
            for position in (0,len(rules)):
                add(rules[:position]+[PolicyRuleDefinition(id='apl:new',action_id=action.id,
                    conditions=_semantic_guards(action))]+rules[position:], 'insert_action')
    for idx,rule in enumerate(rules):
        add(rules[:idx]+rules[idx+1:],'remove_action')
        if idx+1<len(rules):
            change=rules.copy();change[idx],change[idx+1]=change[idx+1],change[idx]
            add(change,'swap_adjacent')
        for action in actions:
            if action.id!=rule.action_id:
                changed=rules.copy();changed[idx]=replace(rule,action_id=action.id,
                                                      conditions=_semantic_guards(action))
                add(changed,'replace_action')
        for condition_index,condition in enumerate(rule.conditions):
            if condition.kind=='resource_threshold':
                cost=next((sum(float(c.amount) for c in a.costs if c.resource_id==condition.resource_id)
                          for a in actions if a.id==rule.action_id),0.)
                if condition.threshold_source=='action_cost': value=cost
                else: value=float(condition.value)
                if value>0:
                    for factor in (0.5,2.0,4.0):
                        conds=list(rule.conditions);conds[condition_index]=replace(condition,
                                           threshold_source=None,value=round(value*factor,3))
                        edit=rules.copy();edit[idx]=replace(rule,conditions=tuple(conds))
                        add(edit,'adjust_resource_gate')
            if condition.kind in ('actor_state','target_state') and condition.field=='health_pct':
                for v in (.2,.35,.5,.75,.9):
                    conds=list(rule.conditions);conds[condition_index]=replace(condition,value=v)
                    edit=rules.copy();edit[idx]=replace(rule,conditions=tuple(conds))
                    add(edit,'adjust_health_gate')
        if len(rule.conditions)<3:
            for cond in (PolicyCondition(kind='target_state',field='health_pct',operator='gte',value=.35),
                         PolicyCondition(kind='actor_state',field='health_pct',operator='lte',value=.35)):
                changed=rules.copy();changed[idx]=replace(rule,conditions=(*rule.conditions,cond))
                add(changed,'add_health_gate')
            action=next((a for a in actions if a.id==rule.action_id),None)
            if action is not None:
                for cond in _cost_gates(action):
                    if not any(c.kind=='resource_threshold' and c.resource_id==cond.resource_id for c in rule.conditions):
                        changed=rules.copy();changed[idx]=replace(rule,conditions=(*rule.conditions,cond))
                        add(changed,'add_source_resource_gate')
        if rule.conditions:
            changed=rules.copy();changed[idx]=replace(rule,conditions=rule.conditions[:-1])
            add(changed,'remove_condition')
    # Diversity-preserving bounded mutation envelope: numeric and structural
    # families must not disappear because a large sourced action catalogue
    # generated >budget insertions first.
    out=[];offset=0
    while len(out)<max_candidates:
        progressed=False
        for name in order:
            if offset<len(buckets[name]):
                out.append(buckets[name][offset]);progressed=True
                if len(out)>=max_candidates:break
        if not progressed:break
        offset+=1
    return tuple(out)


@dataclass(frozen=True)
class EvolutionResult:
    winner: PolicyDefinition|None
    trials: tuple[dict,...]
    candidates: int
    valid: int
    metric: str='actual_100mob_seconds_per_mob'

    def as_dict(self):
        return {'winner':None if self.winner is None else self.winner.as_dict(),
                'candidates':self.candidates,'valid':self.valid,'metric':self.metric,
                'trials':list(self.trials)}



def _interleaved_candidates(*pools):
    """Yield diverse candidate families without preferring a longer pool."""
    for index in range(max((len(pool) for pool in pools), default=0)):
        for pool in pools:
            if index < len(pool):
                yield pool[index]


def search_evolved_policies(ir, *, evaluate:Callable[[PolicyDefinition],dict],
                            seed:PolicyDefinition|None=None, budget:int=32,
                            max_rules:int=MAX_RULES, include_scratch:bool=True) -> EvolutionResult:
    """Perform bounded real evaluations; never score on proxy as an accepted optimum.

    The supplied evaluator must return {'status':'COMPLETE',
    'mean_s_per_mob':...} from real execution. Unfinished policies cannot win.
    """
    if budget<1:raise ValueError('INVALID_EVALUATION_BUDGET')
    policies=[];seen=set()
    def add(p):
        if len(policies)>=budget:return
        _validated(p,ir.actions,max_rules=max_rules)
        sig=_identity(p)
        if sig not in seen:policies.append(p);seen.add(sig)
    if seed is not None:
        add(seed)
        mutated = mutations(seed,ir,max_candidates=budget,max_rules=max_rules)
        if include_scratch:
            # Give independently discovered policies an actual budget share;
            # a large mutation neighborhood must not crowd out cold search.
            cold = scratch_policies(ir,max_candidates=budget,max_rules=max_rules)
            for policy in _interleaved_candidates(cold,mutated):
                add(policy)
        else:
            for p in mutated:add(p)
    elif include_scratch:
        for p in scratch_policies(ir,max_candidates=budget,max_rules=max_rules):add(p)
    trials=[];valid=[]
    for p in policies:
        evidence=evaluate(p)
        if not isinstance(evidence,dict):raise TypeError('PAID_EVALUATOR_MUST_RETURN_DICT')
        score=evidence.get('mean_s_per_mob')
        ok=(evidence.get('status')=='COMPLETE' and (evidence.get('mob_completed')==100 or evidence.get('count')==100)
            and type(score) in (int,float)
            and isfinite(float(score)) and float(score)>0)
        row={'candidate_id':_identity(p),'origin':p.provenance.get('mutation',p.provenance.get('origin')),
             'policy_id':p.id,'status':evidence.get('status'),'valid':ok,
             'mean_s_per_mob':float(score) if ok else None,
             'evidence':dict(evidence)}
        trials.append(row)
        if ok:valid.append((float(score),len(p.rules),_identity(p),p))
    return EvolutionResult(winner=min(valid,key=lambda x:x[:3])[3] if valid else None,
                           trials=tuple(trials),candidates=len(trials),valid=len(valid))

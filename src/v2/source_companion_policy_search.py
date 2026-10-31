"""Bounded source-derived companion priority variants, scored by the shared pull engine.

A companion can autoattack with no active skill, use any subset, and use every
priority ordering. Never silently exclude a legal skill; report bounded scope.
"""
from __future__ import annotations
from itertools import permutations
from src.game.model import PolicyDefinition, PolicyRuleDefinition

def companion_policy_envelope(ir, *, max_policies=16):
    if max_policies < 1:raise ValueError('companion policy budget must be positive')
    if not ir.companions:return (({},),{'candidate_count':1,'truncated':False,'skills':[]})
    # Current source corridor has one permanent pet. Multiple companions need
    # a cross-product frontier and cannot be silently scored as one pet.
    if len(ir.companions)!=1:
        raise ValueError('multiple companion policy joint frontier not implemented')
    pet=ir.companions[0]
    actions=sorted((a for a in ir.actions if a.owner_actor_id==pet.id),key=lambda a:a.id)
    if not actions:
        # A sourced pet/totem with an auto-attack is executable even when its
        # action list is empty. The empty policy means 'no active buttons',
        # NOT 'no attacks'. Require the actual sourced attack; otherwise fail.
        autos = tuple(a for a in ir.auto_attacks if a.owner_actor_id == pet.id)
        if not autos:
            raise ValueError('companion has neither sourced skill nor sourced auto attack')
        policy = PolicyDefinition(id=f'{pet.id}:auto-only',
            label='Sourced autonomous companion attacks', rules=(),
            provenance={'companion_policy':True,'owner_actor_id':pet.id,
                        'source_derived':True,'priority_search':True,'auto_only':True})
        return (({pet.id:policy},), {'candidate_count':1,'truncated':False,
                                   'skills':[],'sourced_auto_attack_ids':[a.id for a in autos]})
    options=[]
    for size in range(len(actions)+1):
        for subset in permutations(actions,size):
            if len(options)>=max_policies:
                return (tuple(options),{'candidate_count':len(options),'truncated':True,
                        'skills':[a.id for a in actions]})
            policy=PolicyDefinition(id=f'{pet.id}:priority:{len(options)}',
                label='Independent sourced pet skill priority',
                rules=tuple(PolicyRuleDefinition(f'pet:rule:{i}',a.id)
                            for i,a in enumerate(subset)),
                provenance={'companion_policy':True,'owner_actor_id':pet.id,
                            'source_derived':True,'priority_search':True})
            options.append({pet.id:policy})
    return (tuple(options),{'candidate_count':len(options),'truncated':False,
                           'skills':[a.id for a in actions]})

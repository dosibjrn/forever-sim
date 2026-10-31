"""Source-bounded at-level talent/action/rank candidate evaluation.

This is an intentionally small *naked-gear* candidate envelope, not the
joint gear/talent/policy optimizer or proof of exhaustive strategic policies.
The IR and shared scorer supply all gameplay; no class scorer or class-specific
branch is used here. Fail closed if the source-backed envelope grows too large.
"""
from __future__ import annotations

from itertools import permutations

from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import LevelState, validate_level_state
from src.game.talents import validate_talent_selection
from src.game.talent_search import enumerate_legal_talent_allocations
from src.v2.level_evaluation_trace import evaluate_level_trace, evaluate_mode_auto_attack_trace
from src.game.model import ModeChangeEffect
from src.v2.source_button_discovery import discover_source_combat_buttons


def _source_mode_auto_attack_candidates(ir, *, max_mode_policies: int = 4) -> list[dict]:
    """Discover executable entry/auto/exit candidates from generic Mode IR."""
    initial = [m for m in ir.modes if m.initial]
    if not ir.modes:
        return []
    if len(initial) != 1:
        raise ValueError('mode candidate envelope needs one initial mode')
    initial = initial[0]
    candidates = []
    for mode in ir.modes:
        if mode.initial:
            continue
        auto = [a for a in ir.auto_attacks if a.required_mode_id == mode.id and a.provenance]
        if not auto:
            continue  # A mode without an auto attack is not this candidate type.
        entries = [a for a in ir.actions
                   if a.id in initial.enabled_action_ids and a.provenance
                   and len(a.effects) == 1 and isinstance(a.effects[0], ModeChangeEffect)
                   and a.effects[0].target_mode_id == mode.id]
        exits = [a for a in ir.actions
                 if a.id in mode.enabled_action_ids and a.provenance
                 and len(a.effects) == 1 and isinstance(a.effects[0], ModeChangeEffect)
                 and a.effects[0].target_mode_id == initial.id]
        if len(entries) != 1 or len(exits) != 1:
            raise ValueError('mode auto attack candidate missing unique sourced entry/exit')
        if not any(r.get('kind') == 'mode_is' and r.get('value') == initial.id
                   for r in entries[0].requirements):
            raise ValueError('mode auto attack candidate missing entry mode requirement')
        candidates.append({'mode_id': mode.id, 'entry_action_id': entries[0].id,
                           'exit_action_id': exits[0].id,
                           'auto_attack_ids': [a.id for a in auto]})
    if len(candidates) > max_mode_policies:
        raise ValueError('mode candidate envelope exceeds explicit bound')
    return candidates


def generate_priority_order_candidates(combat_action_ids, *, max_policies: int = 32):
    """Exhaustively order every subset of sourced non-fallback actions.

    The final sourced rule remains the terminating filler. No class or spell
    identity enters the search. Fail closed on excessive combinatorics rather
    than truncating the search and misreporting completeness.
    """
    combat = tuple(combat_action_ids)
    if not combat or len(set(combat)) != len(combat):
        raise ValueError('invalid sourced combat action identities')
    if max_policies < 1:
        raise ValueError('policy candidate envelope exceeds explicit bound')
    optional, fallback = combat[:-1], combat[-1]
    policies = []
    for count in range(len(optional) + 1):
        for order in permutations(optional, count):
            policies.append(order + (fallback,))
            if len(policies) > max_policies:
                raise ValueError('policy candidate envelope exceeds explicit bound')
    return policies


def enumerate_legal_source_candidates(*, class_key: str, level: int,
                                      max_talent_vectors: int = 64,
                                      max_policies: int = 32,
                                      max_mode_policies: int = 4) -> dict:
    """Build a bounded, *complete within declared canonical policy envelope* set.

    Talent vectors include banked points and are independently validated.
    Policies are canonical priority prefixes ending in the canonical fallback;
    arbitrary GCD permutations are deliberately not searched. The entire
    available action/rank catalogue is reported, including noncombat actions.
    """
    ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None or not ir.policies:
        raise ValueError('no source-backed class/level/policy')
    race = ir.actor.metadata.get('race_key')
    if not isinstance(race, str) or not race:
        raise ValueError('no source-backed scenario race')
    ids = [action.id for action in ir.actions]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate action/rank identity in source IR')
    talents = tuple(ir.talents)
    if len({t.id for t in talents}) != len(talents):
        raise ValueError('duplicate talent identity in source IR')
    # Enumerate *legal executable* allocations with source tier/prerequisite
    # pruning. The old Cartesian preflight over every indexed source family
    # incorrectly rejected even L10 after source-only talent identities were
    # added to SQLite. Missing executable effects are exposed as blockers;
    # never treated as zero-effect talent choices or silently truncated.
    vectors, truncated = enumerate_legal_talent_allocations(
        ir, level=level, max_candidates=max_talent_vectors)
    if truncated:
        raise ValueError('talent candidate envelope exceeds explicit bound')
    if not vectors:
        raise ValueError('no legal talent vectors')
    if len(ir.policies) != 1:
        raise ValueError('multiple source policies need an explicit envelope contract')
    combat = tuple(rule.action_id for rule in ir.policies[0].rules if rule.phase == 'combat')
    if not combat or len(set(combat)) != len(combat) or not set(combat).issubset(ids):
        raise ValueError('canonical combat policy has unavailable/duplicate action rank')
    # Search legal priority orderings instead of assuming the source priority
    # is optimal. The sourced fallback is retained as a bounded first step;
    # full action/policy discovery remains an open capability.
    policies = generate_priority_order_candidates(combat, max_policies=max_policies)
    mode_candidates = _source_mode_auto_attack_candidates(ir, max_mode_policies=max_mode_policies)
    discovered = discover_source_combat_buttons(ir, level=level)
    action_catalogue = [
        {'id': a.id, 'family_key': a.family_key, 'name': a.name,
         'source': [dict(p) for p in a.provenance], 'metadata': dict(a.metadata)}
        for a in ir.actions
    ]
    for vector in vectors:
        validate_level_state(LevelState(class_key, level, race, vector, (combat[-1],)))
    return {
        'class_key': class_key, 'level': level, 'race_key': race,
        'ruleset': ir.ruleset, 'source_ir_id': ir.id,
        'status': 'SOURCE_CANDIDATES', 'optimization_ready': False,
        'source_actions': action_catalogue,
        'discovered_combat_buttons': discovered['action_ids'],
        'discovery_excluded_actions': discovered['excluded'],
        'discovery_status': discovered['status'],
        'discovered_not_in_policy': [x for x in discovered['action_ids'] if x not in combat],
        'canonical_combat_action_ids': list(combat),
        'not_in_canonical_combat_policy': [a.id for a in ir.actions if a.id not in combat],
        'all_source_actions_evaluated': False,
        'talent_definitions': [t.as_dict() for t in talents],
        'talent_vectors': list(vectors),
        'source_only_talent_ids': [t.id for t in talents if not any(r.modifiers for r in t.ranks)],
        'complete_source_talent_coverage': (bool(talents) and all(
            len(t.ranks) == int(t.max_rank) and all(r.modifiers for r in t.ranks)
            for t in talents) and not bool(
            (ir.provenance.get('talent_sqlite_coverage') or {}).get('blockers'))),
        'combat_policy_candidates': [list(p) for p in policies],
        'mode_auto_attack_candidates': mode_candidates,
        'not_evaluated_source_actions': [a.id for a in ir.actions
                                         if a.id not in combat
                                         and all(a.id not in (m['entry_action_id'], m['exit_action_id'])
                                                 for m in mode_candidates)],
        'policy_envelope': 'source_combat_priority_permutations_plus_source_mode_auto_attack',
        'gear_envelope': 'source_actor_naked_only',
        'exhaustive_joint_optimizer': False,
        'complete_legal_action_search': False,
    }


def evaluate_source_candidate_envelope(*, class_key: str, level: int,
                                       include_discovered_policy_search: bool = False) -> dict:
    envelope = enumerate_legal_source_candidates(class_key=class_key, level=level)
    rows = []
    for talent in envelope['talent_vectors']:
        for actions in envelope['combat_policy_candidates']:
            trace = evaluate_level_trace(class_key=class_key, level=level,
                                         talent_selection=talent, candidate_action_ids=tuple(actions))
            rows.append({
                'talents': talent, 'actions': actions, 'candidate_kind': 'canonical_combat',
                'seconds_per_mob': trace['evaluation']['seconds_per_mob'],
                'combat_kill_s': trace['combat']['kill_s'],
                'recovery_s': trace['recovery']['total_s'],
                'trace': trace,
            })
    caster_count = len(rows)
    for talent in envelope['talent_vectors']:
        for mode in envelope['mode_auto_attack_candidates']:
            trace = evaluate_mode_auto_attack_trace(
                class_key=class_key, level=level, talent_selection=talent,
                entry_action_id=mode['entry_action_id'],
            )
            rows.append({
                'talents': talent, 'actions': [mode['entry_action_id']],
                'candidate_kind': 'source_mode_auto_attack', 'mode_id': mode['mode_id'],
                'seconds_per_mob': trace['evaluation']['seconds_per_mob'],
                'combat_kill_s': trace['combat']['kill_s'],
                'recovery_s': trace['recovery']['total_s'],
                'trace': trace,
            })
    mode_count = len(rows) - caster_count
    discovered_count = 0
    if include_discovered_policy_search:
        from src.v2.source_policy_search import evaluate_discovered_policy_search
        for talent in envelope['talent_vectors']:
            search = evaluate_discovered_policy_search(
                class_key=class_key, level=level, talent_selection=talent)
            for candidate in [search['winner'], *search['alternatives']]:
                rows.append({
                    'talents': talent, 'actions': candidate['actions'],
                    'candidate_kind': 'source_discovered_combat',
                    'seconds_per_mob': candidate['seconds_per_mob'],
                    'combat_kill_s': candidate['combat_kill_s'],
                    'recovery_s': candidate['recovery_s'], 'trace': candidate,
                })
                discovered_count += 1
    if not rows:
        raise ValueError('no executable source candidates')
    rows.sort(key=lambda x: (x['seconds_per_mob'], str(x['talents']), str(x['actions'])))
    return {
        **envelope, 'status': 'EVALUATED', 'evaluated_count': len(rows),
        'canonical_combat_evaluated_count': caster_count,
        'mode_auto_attack_evaluated_count': mode_count,
        'source_discovered_evaluated_count': discovered_count,
        'winner': rows[0], 'alternatives': rows[1:],
        'complete_optimizer': False,
        'missing': ['attainable_gear_candidates', 'joint_gear_search', 'travel_timing',
                    'survival_validation', 'cross_pull_resource_carry',
                    'independent_fidelity', 'route_continuity'],
    }

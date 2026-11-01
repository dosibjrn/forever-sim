"""Generic source-legal talent × equipment × APL paid frontier.

Every complete score comes from the EXISTING persistent CombatRuntime with
100 sequential mobs and paid recovery.  Source labels and strict coverage
limits stay with the result; a bounded diagnostic is never a certified optimum.
"""
from __future__ import annotations

from src.game.talents import available_talent_points, talented_bonus_for_level
from src.game.talent_frontier import Neighbor, source_legal_talent_neighbors
from collections import defaultdict, deque
from itertools import chain
from dataclasses import replace
from contextlib import contextmanager, nullcontext
import signal
import threading
from heapq import heappop, heappush
import multiprocessing as mp
import json
from copy import deepcopy
from math import isfinite
from time import monotonic, process_time

from src.game.checkpoint_pipeline import checkpoint_enemy, discover_source_damage_seeds
from src.game.policy_evolution import (
    _identity as policy_identity, _semantic_guards, _hostile_control, _validated as validate_policy,
    from_source_rules, mutations, scratch_policies, source_policy_uncertainties,
)
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talent_subset_search import enumerate_executable_allocations
from src.game.talents import validate_talent_selection
from src.game.model import (ModeChangeEffect, ControlEffect, PolicyCondition, HealEffect, PeriodicHealEffect, DamageEffect, WeaponDamageEffect,
    PeriodicEffect, ResourceScaledDirectDamageEffect, ResourceScaledPeriodicEffect, ResourceChangeEffect, PeriodicResourceEffect)
from src.game.recovery_between_pulls import BetweenPullPolicy
from src.v2.source_persistent_joint_finalists import (prepare_candidate,
    evaluate_persistent_candidate)
from src.v2.source_joint_progress import PaidJointProgressJournal, search_context_sha256
from src.v2.source_persistent_slot_search import (_source_slot_proposals,
    _source_weapon_package_proposals, _source_stat_package_proposals)


class _CandidateWallBudgetExpired(RuntimeError):
    """A direct quick-search attempt used its finite allotted wall time."""


@contextmanager
def _quick_candidate_wall_budget(seconds):
    """Kill a pathological quick candidate without forking every 2-mob screen.

    Covers synchronous source candidate preparation and expensive recovery
    paths, even if a nested executor neglects to poll its compute deadline.
    This is search infrastructure, not a game mechanic or search shortcut.
    Keep any enclosing SIGALRM timer intact (including nested candidate calls).
    """
    seconds = float(seconds)
    if not 0 < seconds <= 120 or not isfinite(seconds):
        raise ValueError('INVALID_QUICK_CANDIDATE_WALL_BUDGET')
    if not hasattr(signal, 'setitimer') or threading.current_thread() is not threading.main_thread():
        raise RuntimeError('QUICK_CANDIDATE_HARD_WALL_DEADLINE_REQUIRES_MAIN_THREAD')
    old_handler = signal.getsignal(signal.SIGALRM)
    old_remaining, old_interval = signal.getitimer(signal.ITIMER_REAL)
    started = monotonic()

    def expired(_signum, _frame):
        raise _CandidateWallBudgetExpired('BLOCKED_QUICK_CANDIDATE_WALL_BUDGET')

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL,
                     max(0.000001, min(seconds, old_remaining) if old_remaining > 0 else seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_remaining > 0:
            remaining = old_remaining - (monotonic() - started)
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, remaining), old_interval)


def _key(allocation):
    return tuple(sorted((str(k), int(v)) for k, v in allocation.items() if v))


def _executable_rank_prefix(talent):
    ranks = {int(rank.rank) for rank in talent.ranks if rank.modifiers}
    return max((n for n in range(1, int(talent.max_rank)+1)
                if set(range(1, n+1)).issubset(ranks)), default=0)


def _source_unlock_full_point_allocation(ir, target, *, level, bonus_talent_points=0,
                                         target_rank=1, preferred_tree=None,
                                         minimum_tree_points=0):
    """Find a legal complete source-talent witness without class/build templates.

    The target's prerequisite is paid first, tier gates are filled with lower
    row executable ranks, and every intermediate point uses the real validator.
    Failure means no witness was constructed, NOT proof of unreachability.
    When a product spec constrains one tree, preserve its minimum even while
    witnessing a rank in a *different* source tree. No tree or talent IDs are
    hardcoded into this builder.
    """
    cap = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    definitions = {t.id: t for t in ir.talents}
    rank_caps = {t.id: _executable_rank_prefix(t) for t in ir.talents}
    points_per_row = int((ir.provenance.get('talent_tree_rules') or {}).get('points_per_row', 5))
    allocation = {}
    active = set()
    preferred_tree = target.tree_key if preferred_tree is None else preferred_tree
    if (type(minimum_tree_points) is not int or minimum_tree_points < 0
            or minimum_tree_points > cap
            or preferred_tree not in {t.tree_key for t in ir.talents}):
        return None

    def add_one(talent):
        rank = allocation.get(talent.id, 0) + 1
        if rank > rank_caps[talent.id] or sum(allocation.values()) >= cap:
            return False
        trial = {**allocation, talent.id: rank}
        try:
            validate_talent_selection(ir, trial, level=level,
                                      bonus_talent_points=bonus_talent_points)
        except ValueError:
            return False
        allocation.update(trial)
        return True

    def fill_tier(tree, row):
        required = row * points_per_row
        while sum(v for tid, v in allocation.items()
                  if definitions[tid].tree_key == tree) < required:
            donors = sorted((t for t in ir.talents if t.tree_key == tree
                and t.id != target.id and t.metadata.get('row') is not None
                and int(t.metadata['row']) < row),
                key=lambda t: (int(t.metadata['row']), t.id))
            if not any(add_one(t) for t in donors):
                return False
        return True

    def ensure(talent_id, desired_rank):
        if talent_id in active or talent_id not in definitions:
            return False
        talent = definitions[talent_id]
        if desired_rank > rank_caps[talent_id]:
            return False
        active.add(talent_id)
        prereq = talent.prerequisite
        if prereq and not ensure(str(prereq['talent_id']), int(prereq['required_rank'])):
            active.remove(talent_id)
            return False
        row = talent.metadata.get('row')
        if row is None or not fill_tier(talent.tree_key, int(row)):
            active.remove(talent_id)
            return False
        while allocation.get(talent_id, 0) < desired_rank:
            if not add_one(talent):
                active.remove(talent_id)
                return False
        active.remove(talent_id)
        return True

    if not ensure(target.id, target_rank):
        return None
    # Pay the named-tree constraint before generic filler consumes the budget.
    # Every added point still passes the same canonical talent validator.
    while sum(rank for tid, rank in allocation.items()
              if definitions[tid].tree_key == preferred_tree) < minimum_tree_points:
        donors = sorted((t for t in ir.talents if t.tree_key == preferred_tree),
                        key=lambda t:(int(t.metadata.get('row') or 0), t.id))
        if not any(add_one(t) for t in donors):
            return None
    while sum(allocation.values()) < cap:
        donors = sorted(ir.talents, key=lambda t:(
            t.tree_key != preferred_tree,
            int(t.metadata.get('row') or 0), t.id))
        if not any(add_one(t) for t in donors):
            return None
    return dict(allocation)


def _source_unlock_allocations(ir, *, level, bonus_talent_points=0):
    """Reserve reachable source action grants before a bounded talent beam."""
    found = []
    failed = []
    for talent in ir.talents:
        if not any(mod.kind in ('grant_source_action', 'unlock_action_family',
                                     'conditional_target_aura_damage_pct')
                   for rank in talent.ranks for mod in rank.modifiers):
            continue
        candidate = _source_unlock_full_point_allocation(ir, talent,
            level=level, bonus_talent_points=bonus_talent_points)
        if candidate is None:
            # P4's must-execute unlock obligation applies to *new actions*.
            # A passive condition can be unreachable under a lower point
            # budget without invalidating mandatory action-unlock coverage.
            if any(mod.kind in ('grant_source_action','unlock_action_family')
                   for rank in talent.ranks for mod in rank.modifiers):
                failed.append(talent.id)
        else:
            found.append((talent.id, candidate))
    return found, failed


def _source_max_rank_witness_allocations(ir, *, level, bonus_talent_points, limit):
    """Reserve legal fully ranked sourced mechanics without class/talent lists.

    Compound effects are prioritized because their real executor can change
    policy, survival and cast speed simultaneously. No witness is an optimum.
    """
    ranked=[]
    for talent in ir.talents:
        cap=_executable_rank_prefix(talent)
        if cap < 2:
            continue
        row=next((r for r in talent.ranks if r.rank==cap),None)
        if row is None or not row.modifiers:
            continue
        # Favor sourced multi-effect mechanics, then deep ranks; other talents
        # still remain in the ordinary beam and are not declared covered.
        # Source-typed stateful producer/consumer and control mechanisms need
        # an executable witness before the beam fills with passive stats.
        # These are generic modifier kinds, never talent/class identifiers.
        stateful=any(m.kind in ('cast_charge_exchange','action_control_proc',
                                'control_target_cap_bonus') for m in row.modifiers)
        ranked.append((talent,cap,len(row.modifiers),stateful))
    ranked.sort(key=lambda r:(-int(r[3]),-r[2],-r[1],r[0].tree_key,r[0].id))
    found=[];unresolved=[]
    for talent,cap,_,_ in ranked:
        candidate=_source_unlock_full_point_allocation(ir,talent,level=level,
            bonus_talent_points=bonus_talent_points,target_rank=cap)
        if candidate is None:
            unresolved.append(talent.id)
        else:
            found.append((talent.id,candidate))
    return found[:limit],{'found':[tid for tid,_ in found],
                          'unresolved':unresolved,'quota':limit}


def bounded_full_point_talent_frontier(ir, *, level, bonus_talent_points=0,
                                       max_exact_enumerations=100000,
                                       beam_width=64, max_frontier=12):
    """Produce *legal full-point* allocations without Cartesian explosion.

    Exact supported subset is preferred. With enormous spaces, use legal
    one-rank extensions of class-neutral source tier corridors, preserving
    tree diversity at every beam. Beam coverage is NEVER exhaustive proof.
    """
    if not 1<=beam_width<=2048 or not 1<=max_frontier<=256:
        raise ValueError('INVALID_BOUNDED_TALENT_FRONTIER_BUDGET')
    points=available_talent_points(level, bonus_talent_points=bonus_talent_points)
    complete,proof=enumerate_executable_allocations(ir,level=level,
        bonus_talent_points=bonus_talent_points,max_enumerations=max_exact_enumerations)
    unlocks, failed_unlocks = _source_unlock_allocations(ir, level=level,
        bonus_talent_points=bonus_talent_points)
    rank_witnesses,rank_ledger=_source_max_rank_witness_allocations(ir,level=level,
        bonus_talent_points=bonus_talent_points,limit=max(1,max_frontier//4))
    reserved_by_key={_key(allocation): allocation for _, allocation in
        (*unlocks,*rank_witnesses)}
    reserved=list(reserved_by_key.values())
    reserved_keys=set(reserved_by_key)
    rank_metadata={'source_max_rank_witnesses_found':rank_ledger['found'],
        'source_max_rank_witnesses_unresolved':rank_ledger['unresolved'],
        'source_max_rank_witnesses_admitted':min(len(rank_witnesses),max(0,max_frontier-len(unlocks)))}
    if proof['complete_supported_subspace']:
        ordered = reserved + [a for a in complete if _key(a) not in reserved_keys]
        return ordered[:max_frontier], {'method':'exact_supported_subset',
            'all_legal_supported_allocations':len(complete),
            'frontier_truncated':len(ordered)>max_frontier,
            'source_unlock_allocations_found':[tid for tid,_ in unlocks],
            'source_unlock_allocation_unresolved':failed_unlocks,
            'source_unlock_admitted':min(len(unlocks),max_frontier),
            **rank_metadata,
            'exhaustive':len(complete)<=max_frontier,
            'enumeration':proof}
    # Source talent rows, tier unlocks and prerequisites are checked by the
    # common validator at *every* intermediate allocation.
    from src.v2.source_legal_beam import source_tier_unlock_corridors
    corridors=source_tier_unlock_corridors(ir,level=level,max_corridors=512,
        bonus_talent_points=bonus_talent_points)
    seeds=[{}]+list(corridors)
    max_prefix={t.id:_executable_rank_prefix(t) for t in ir.talents}
    tree_of={t.id:t.tree_key for t in ir.talents}
    seed_unique={_key(a):dict(a) for a in seeds if sum(a.values())<=points}
    layers=defaultdict(list)
    for a in seed_unique.values():
        if all(a.get(t.id,0)<=max_prefix[t.id] for t in ir.talents):
            try:validate_talent_selection(ir,a,level=level,bonus_talent_points=bonus_talent_points)
            except ValueError:continue
            layers[sum(a.values())].append(a)
    # Work outward from every source corridor, never attempt a false proof
    # from the raw product of rank vectors.
    examined=0
    for spent in range(points):
        layer=layers.get(spent,[])
        for a in layer[:beam_width]:
            for talent in ir.talents:
                nxt=a.get(talent.id,0)+1
                if nxt>max_prefix[talent.id]:continue
                trial={**a,talent.id:nxt}
                examined+=1
                try:validate_talent_selection(ir,trial,level=level,
                    bonus_talent_points=bonus_talent_points)
                except ValueError:continue
                layers[spent+1].append(trial)
        if len(layers.get(spent+1,()))>beam_width:
            unique={_key(a):a for a in layers[spent+1]}
            # Round-robin across the source tree of the dominant allocation.
            buckets=defaultdict(list)
            for a in unique.values():
                main=max(sorted(set(tree_of.values())),key=lambda tree:(
                    sum(rank for k,rank in a.items() if tree_of[k]==tree),tree))
                buckets[main].append(a)
            for tree in buckets:
                buckets[tree].sort(key=lambda a:(-sum(v*v for v in a.values()),len(a),_key(a)))
            selected=[]
            while len(selected)<beam_width and any(buckets.values()):
                for tree in sorted(buckets):
                    if buckets[tree] and len(selected)<beam_width:
                        selected.append(buckets[tree].pop(0))
            layers[spent+1]=selected
    full={_key(a):a for a in layers.get(points,[])}
    # When a deep seed itself spends all points, retain it irrespective of beam.
    for a in seed_unique.values():
        if sum(a.values())==points:full[_key(a)]=a
    ranked=sorted(full.values(),key=lambda a:(-sum(v*v for v in a.values()),len(a),_key(a)))
    # Do not make one source tree monopolize a tiny frontier.
    buckets=defaultdict(list)
    for a in ranked:
        main=max(sorted(set(tree_of.values())),key=lambda tree:(
            sum(rank for k,rank in a.items() if tree_of[k]==tree),tree))
        buckets[main].append(a)
    selected=[]
    while len(selected)<max_frontier and any(buckets.values()):
        for tree in sorted(buckets):
            if buckets[tree] and len(selected)<max_frontier:
                selected.append(buckets[tree].pop(0))
    selected = (reserved + [a for a in selected if _key(a) not in reserved_keys])[:max_frontier]
    return selected, {'method':'legal_rank_beam', 'exhaustive':False,
        'raw_cartesian_exceeded':proof.get('raw_combinations'),
        'full_point_legal_discovered':len(full), 'frontier_truncated':len(full)>max_frontier,
        'source_unlock_allocations_found':[tid for tid,_ in unlocks],
        'source_unlock_allocation_unresolved':failed_unlocks,
        'source_unlock_admitted':min(len(unlocks),max_frontier),
        **rank_metadata,
        'visited_proposals':examined, 'beam_width':beam_width,
        'enum_blocker':proof['status']}



def source_spec_talent_frontier(ir, candidates, *, tree_key, minimum_points,
                                level, bonus_talent_points, max_frontier):
    """Legal *spec-constrained* full-point frontier, not source-name presets.

    An unrestricted round-robin beam can give a tree just one slot. Expand
    legal neighbors within the desired tree before paying for joint policies;
    all intermediate source prerequisites remain checked by the source talent
    neighbor generators and the canonical legality validator.
    """
    definitions = {t.id:t for t in ir.talents}
    if tree_key not in {t.tree_key for t in ir.talents}:
        raise ValueError('UNKNOWN_SOURCE_SPEC_TREE:'+str(tree_key))
    budget = available_talent_points(level, bonus_talent_points=bonus_talent_points)
    if (type(minimum_points) is not int or not 0 <= minimum_points <= budget
            or not 1 <= max_frontier <= 256):
        raise ValueError('INVALID_SOURCE_SPEC_POINT_CONSTRAINT')

    def legal(allocation):
        return (sum(allocation.values()) == budget
                and sum(rank for tid,rank in allocation.items()
                    if definitions[tid].tree_key == tree_key) >= minimum_points
                and _is_executable_full_source_allocation(ir, allocation,
                    level=level, bonus_talent_points=bonus_talent_points))

    seeds = [dict(a) for a in candidates if legal(a)]
    # One unrestricted beam allocation is not adequate spec exploration.
    # A named spec constrains the full build, not the set of testable ranks.
    # Witness *every* executable rank in every source tree, including outside
    # the preferred tree. Otherwise P2 falsely reports off-tree ranks absent
    # simply because its bounded beam never sampled their exact rank.
    for talent in ir.talents:
        cap = _executable_rank_prefix(talent)
        for rank in range(1, cap + 1):
            proposal = _source_unlock_full_point_allocation(ir,talent,
                level=level,bonus_talent_points=bonus_talent_points,
                target_rank=rank,preferred_tree=tree_key,
                minimum_tree_points=minimum_points)
            if proposal and legal(proposal):
                seeds.append(proposal)
    if not seeds:
        raise ValueError('NO_LEGAL_SOURCE_SPEC_FULL_POINT_ALLOCATION')

    unique = {_key(a):a for a in seeds}
    priority_seeds = list(unique.values())
    frontier = list(priority_seeds)
    # Build adjacent and full-rank-transfer candidates in alternating rounds.
    # Stop after bounded proposals; never search a combinatorial Cartesian
    # space just to assemble an optimizer's initial population.
    cursor = 0
    cap = max(96, 8*max_frontier)
    while cursor < len(frontier) and len(unique) < cap:
        seed = frontier[cursor]
        cursor += 1
        neighborhood = source_legal_talent_neighbors(ir,seed,level=level,
            bonus_talent_points=bonus_talent_points)['neighbors']
        proposals = list(neighborhood)
        proposals.extend(_source_legal_macro_talent_transfers(ir,seed,
            level=level,bonus_talent_points=bonus_talent_points))
        for proposal in proposals:
            changed = dict(proposal.allocation)
            identity = _key(changed)
            if identity not in unique and legal(changed):
                unique[identity] = changed
                frontier.append(changed)
            if len(unique) >= cap:
                break
    # Retain broad source-rank variation, not only the first alphabetical
    # donor/receiver moves, which frequently differ in one inert talent.
    output = list(unique.values())
    if len(output) > max_frontier:
        anchors = priority_seeds[:max_frontier]
        if len(anchors)<max_frontier:
            remainder = output[len(priority_seeds):]
            take = max_frontier-len(anchors)
            positions = ([i*(len(remainder)-1)//(take-1) for i in range(take)]
                if take>1 else [0])
            anchors.extend(remainder[i] for i in positions)
        output = anchors
    return output, {'source_spec_tree':tree_key,
        'source_spec_minimum_points':minimum_points,
        'source_spec_seed_count':len(seeds),
        'source_spec_legal_expanded':len(unique),
        'source_spec_population':len(output),
        'source_spec_enumeration_exhaustive':False}


def _policy_mode_damage_action_ids(ir, policy, mode_id):
    """Source effect / mode graph defines mode-specific *offensive* actions.

    A form swap by itself is not evidence of a cat/bear policy. The policy
    must contain an attack actually legal in the requested combat mode.
    """
    by_id = {a.id:a for a in ir.actions}
    offensive = {'damage','direct_damage','weapon_damage','periodic_damage',
                 'resource_scaled_direct_damage','resource_scaled_periodic_damage'}
    return frozenset(action.id for rule in policy.rules
        if (action:=by_id.get(rule.action_id)) is not None
        and any(req.get('kind')=='mode_is' and req.get('value')==mode_id
                for req in action.requirements)
        and any(getattr(effect,'effect_type',None) in offensive
                for effect in action.effects))


def _is_executable_full_source_allocation(ir, allocation, *, level,
                                          bonus_talent_points=0):
    """Require every source point and rank executor before admitting a seed."""
    if sum(allocation.values()) != available_talent_points(level, bonus_talent_points=bonus_talent_points):
        return False
    rank_prefix={talent.id:_executable_rank_prefix(talent) for talent in ir.talents}
    if any(rank<0 or rank>rank_prefix.get(talent_id,0)
           for talent_id,rank in allocation.items()):
        return False
    try:
        validate_talent_selection(ir,allocation,level=level,
            bonus_talent_points=bonus_talent_points)
    except ValueError:
        return False
    return True


def _source_reference_talents(ir, *, level, candidates, source_allocation,
                              bonus_talent_points=0):
    """Reserve a full legal seed, or identify the first beam proposal as control."""
    candidates=list(candidates)
    source_allocation=dict(source_allocation or {})
    if not _is_executable_full_source_allocation(ir,source_allocation,level=level,
                                                bonus_talent_points=bonus_talent_points):
        return candidates,'FIRST_INDEPENDENT_SOURCE_LEGAL_PROPOSAL_NOT_SOURCE_SEED'
    seed_key=_key(source_allocation)
    ordered=[source_allocation]+[a for a in candidates if _key(a)!=seed_key]
    return ordered[:max(1,len(candidates))],'LEGAL_SOURCE_FULL_BUILD'


def source_gear_seed_stage(*, gear, ir, source_evidence):
    """Wrap already-sourced full gear in a generic persistent-search stage.

    A gear evidence artifact is NOT silently converted into a class legality
    attestation; actual source legality is still verified in prepare_candidate.
    """
    seeds=discover_source_damage_seeds(ir,max_actions=8)
    if not seeds or not gear.get('slots'):
        raise ValueError('NO_SOURCE_GEAR_OR_APL_FOR_JOINT_STAGE')
    action=next((seed.rules[0].action_id for seed in seeds if len(seed.rules)==1),None)
    if action is None:raise ValueError('NO_SINGLE_SOURCE_DAMAGE_ACTION')
    return {'allocation':{},'paid_candidate_origin':'source_gear_seed_diagnostic',
        'source_gear_evidence':str(source_evidence),
        'gear_policy_result':{'winner':{'gear':deepcopy(gear),
            'winner':{'fallback':action,'prefix':[],
                      'guarded_action':None,'guarded_conditions':[]}}}}


def _cold_source_equipment_payload(*, class_key, level, gear_role, selected):
    """Convert sourced item records to the one canonical persistent gear schema."""
    from src.rulesets.forever.items.runtime_selection import item_payload, effective_level
    slots = {slot: item_payload(item, display_slot=slot,
                effective_level=effective_level(item))
             for slot, item in selected.items()}
    aggregate = {}
    for item in slots.values():
        for axis in ('strength', 'agility', 'stamina', 'intellect', 'spirit',
                     'attack_power', 'spell_power', 'healing', 'mp5', 'armor',
                     'weapon_dps', 'wand_dps'):
            aggregate[axis] = aggregate.get(axis, 0.) + float(item.get(axis, 0.) or 0.)
    gear = {'class_key':class_key, 'level':level, 'role':gear_role,
            'item_count':len(slots), 'slots':slots, 'aggregate_stats':aggregate,
            'selection_weights':{}, 'source':'canonical_sqlite_cold_source_bootstrap'}
    return gear

def source_cold_start_stage(*, class_key, level, source_ir, gear_role):
    """Bootstrap a paid search solely from pinned GameIR and item SQLite.

    The neutral all-zero stat prior chooses a deterministic, high-level legal
    starting package without importing a previous/held-out optimizer winner.
    `gear_role` controls *initial equipment proficiency only*, not the talent
    or policy frontier, and is explicit source/profile input to the caller.
    """
    from src.rulesets.forever.items.runtime_selection import (
        select_gear,
    )
    if not gear_role or source_ir.actor.metadata.get('class_key') != class_key or (
            int(source_ir.actor.metadata.get('level', -1)) != level):
        raise ValueError('COLD_SOURCE_CLASS_LEVEL_OR_GEAR_ROLE_MISMATCH')
    selected = select_gear(class_key, level, gear_role, weights={},
        required_level_policy='observed', exclude_unknown_item_effects=True)
    if not selected:
        raise ValueError('COLD_SOURCE_NO_EXECUTABLE_LEGAL_GEAR')
    gear = _cold_source_equipment_payload(class_key=class_key, level=level,
        gear_role=gear_role, selected=selected)
    stage = source_gear_seed_stage(gear=gear, ir=source_ir,
        source_evidence='canonical_sqlite_and_game_ir_only')
    stage['paid_candidate_origin'] = 'COLD_SQLITE_SOURCE_NO_PREVIOUS_WINNER'
    stage['cold_gear_role'] = gear_role
    return stage

def _source_opening_context_ir(ir, stage):
    """Restrict continuation search to actions enabled after sourced opening.

    No speculative form shift: explicit mode changes in the seed opening are
    replayed in order; single-mode continuations use this restricted view.
    """
    current = _source_opening_mode(ir, stage)
    mode = next((m for m in ir.modes if m.id == current), None)
    if mode is None:
        return ir
    enabled = None if mode.enabled_action_ids is None else set(mode.enabled_action_ids)
    actions = tuple(a for a in ir.actions if
        (enabled is None or a.id in enabled) and all(
            req.get('kind') != 'mode_is' or str(req.get('value')) == current
            for req in a.requirements))
    return replace(ir, actions=actions)


def _source_opening_mode(ir, stage):
    """Replay only sourced opening mode effects; no speculative transitions."""
    current = next((m.id for m in ir.modes if m.initial), None)
    by_id = {a.id: a for a in ir.actions}
    for action_id in stage['gear_policy_result']['winner']['winner'].get('prefix', ()):
        action = by_id.get(action_id)
        if action is None:
            raise ValueError('JOINT_SOURCE_OPENING_ACTION_NOT_IN_IR:'+str(action_id))
        for effect in action.effects:
            if isinstance(effect, ModeChangeEffect):
                current = effect.target_mode_id
    return current



def _source_actor_action_usable_in_mode(ir, action, mode_id):
    """One source-legal mode predicate for witness graph and action rules."""
    mode = next((m for m in ir.modes if m.id == mode_id), None)
    return bool(mode is not None and action.owner_actor_id == ir.actor.id
        and (mode.enabled_action_ids is None or action.id in mode.enabled_action_ids)
        and all(req.get('kind') != 'mode_is' or str(req.get('value')) == mode_id
                for req in action.requirements))


def _source_mode_transition_edges(ir):
    """Source-legal actor mode graph shared by generated APL witnesses."""
    modes = {mode.id: mode for mode in ir.modes}
    edges = defaultdict(list)
    for mode_id in modes:
        for action in ir.actions:
            if not _source_actor_action_usable_in_mode(ir, action, mode_id):
                continue
            for effect in action.effects:
                if isinstance(effect, ModeChangeEffect) and effect.target_mode_id in modes:
                    edges[mode_id].append((effect.target_mode_id, action))
    return edges


def _source_shortest_mode_path(edges, origin, target):
    """Deterministic sourced mode-transition path shared by generated APLs."""
    pending=deque([(origin,())]);visited={origin}
    while pending:
        mode,path=pending.popleft()
        if mode==target:
            return path
        for next_mode,action in sorted(edges[mode],key=lambda row:(row[1].id,row[0])):
            if next_mode not in visited:
                visited.add(next_mode)
                pending.append((next_mode,path+((mode,action),)))
    return None


def source_talent_unlock_witnesses(base_ir, selected_ir, seed_stage):
    """Generate source-only executable APL witnesses for newly unlocked actions.

    A talent grant is not P4 coverage until the ordinary CombatRuntime reports
    a real execution count. This generator merely supplies candidates: it does
    not mark an action covered, seed a historical policy, grant resources, or
    skip form transitions. Mode edges and resource producers come from GameIR.
    """
    from src.game.talents import apply_talent_selection
    unselected_ir, _ = apply_talent_selection(base_ir, {},
        level=int(base_ir.actor.metadata['level']))
    baseline = {a.id for a in unselected_ir.actions}
    unlocked = [a for a in selected_ir.actions if a.id not in baseline
                and a.owner_actor_id == selected_ir.actor.id]
    if not unlocked:
        return ()
    modes = {m.id: m for m in selected_ir.modes}
    initial_mode = _source_opening_mode(base_ir, seed_stage)
    if initial_mode not in modes:
        raise ValueError('P4_UNLOCK_OPENING_MODE_NOT_IN_IR')

    def available_in_mode(action, mode):
        entry = modes[mode]
        return ((entry.enabled_action_ids is None or action.id in entry.enabled_action_ids)
                and all(req.get('kind') != 'mode_is' or str(req.get('value')) == mode
                        for req in action.requirements))

    edges = defaultdict(list)
    for mode in modes:
        for action in selected_ir.actions:
            if not available_in_mode(action, mode):
                continue
            for effect in action.effects:
                if isinstance(effect, ModeChangeEffect) and effect.target_mode_id in modes:
                    edges[mode].append((effect.target_mode_id, action))

    def shortest_mode_path(target, *, start_mode=None):
        origin = initial_mode if start_mode is None else start_mode
        return _source_shortest_mode_path(edges,origin,target)

    def fallback_damage_mode(target_mode):
        """Find a reversible, source-executable combat mode without class facts."""
        alternatives = []
        for mode_id in modes:
            if mode_id == target_mode:
                continue
            outward = shortest_mode_path(mode_id, start_mode=target_mode)
            inward = shortest_mode_path(target_mode, start_mode=mode_id)
            if outward is None or inward is None:
                continue
            damage = [a for a in selected_ir.actions
                if a.owner_actor_id == selected_ir.actor.id
                and available_in_mode(a, mode_id)
                and any(isinstance(e, (DamageEffect, WeaponDamageEffect,
                    PeriodicEffect, ResourceScaledDirectDamageEffect,
                    ResourceScaledPeriodicEffect)) for e in a.effects)]
            if not damage:
                continue
            autos = [a for a in selected_ir.auto_attacks if a.required_mode_id == mode_id]
            fastest = min((float(a.swing_time_s) for a in autos), default=float('inf'))
            alternatives.append((not bool(autos), fastest, len(outward)+len(inward),
                                 mode_id, min(damage,key=_source_action_rank_order),
                                 outward, inward))
        return min(alternatives) if alternatives else None

    def pending_resource_guards(producer, cost):
        """Never abandon a producer's sourced active periodic resource aura."""
        return tuple(PolicyCondition(kind='aura_missing', scope='actor',
                                     aura_id=effect.aura_id)
            for effect in producer.effects
            if isinstance(effect, PeriodicResourceEffect)
            and effect.resource_id == cost.resource_id and effect.aura_id)

    witnesses = []
    for action in sorted(unlocked, key=lambda a: a.id):
        source_talents = sorted({t.id for t in base_ir.talents for rank in t.ranks
            for modifier in rank.modifiers if (
                (modifier.kind == 'unlock_action_family'
                 and modifier.target_id == action.family_key)
                or (modifier.kind.startswith('grant_source_')
                    and (str(modifier.target_id) == str(action.family_key) or
                         str(modifier.target_id) in action.id or
                         any(str(p.get('talent_grant_spell_id', '')) == str(modifier.target_id)
                             for p in action.provenance))))})
        if not source_talents:
            raise ValueError('P4_UNLOCK_ACTION_WITHOUT_SOURCE_TALENT:' + action.id)
        target_modes = sorted({str(req['value']) for req in action.requirements
                               if req.get('kind') == 'mode_is'})
        if len(target_modes) > 1:
            raise ValueError('P4_UNLOCK_ACTION_CONFLICTING_MODES:' + action.id)
        target_mode = target_modes[0] if target_modes else initial_mode
        path = shortest_mode_path(target_mode)
        if path is None:
            raise ValueError('P4_UNLOCK_ACTION_MODE_UNREACHABLE:' + action.id)
        guard = (PolicyCondition(kind='mode_state', operator='eq', value=target_mode),)
        rules = []
        # Source-defined producers supply real resources; neither the policy
        # nor its witness can manufacture rage, mana or energy.
        paid_producers = []
        for cost in action.costs:
            if float(cost.amount) <= 0:
                continue
            producers = [other for other in selected_ir.actions
                if other.id != action.id and available_in_mode(other, target_mode)
                and any((isinstance(effect, ResourceChangeEffect)
                         and effect.resource_id == cost.resource_id
                         and effect.target in ('actor', 'self')
                         and effect.operation == 'add' and effect.amount > 0)
                        or (isinstance(effect, PeriodicResourceEffect)
                            and effect.resource_id == cost.resource_id
                            and effect.target in ('actor', 'self')
                            and effect.operation == 'add' and effect.amount_per_tick > 0)
                        for effect in other.effects)]
            if producers:
                producer = min(producers, key=lambda a: (a.cooldown_s, a.id))
                paid_producers.append((producer, cost))
                rules.append((producer.id, guard + (
                    PolicyCondition(kind='resource_threshold',
                        resource_id=cost.resource_id, operator='lt',
                        value=float(cost.amount)),)))
        rules.append((action.id, guard + _semantic_guards(action)))
        # A source-unlocked *non-damaging* action (control, charge,
        # mobility, resource generation, periodic upkeep, etc.) is not a
        # complete kill policy. A legal mode-specific direct-damage filler
        # comes from GameIR rather than any class/talent rotation template.
        if not any(isinstance(e,(DamageEffect,WeaponDamageEffect,
                       ResourceScaledDirectDamageEffect)) for e in action.effects):
            fillers=[other for other in selected_ir.actions if other.id!=action.id
                and available_in_mode(other,target_mode)
                and any(isinstance(e,(DamageEffect,WeaponDamageEffect,
                    ResourceScaledDirectDamageEffect)) for e in other.effects)
                and not any(isinstance(e,(PeriodicEffect,ResourceScaledPeriodicEffect))
                            for e in other.effects)]
            def filler_priority(other):
                magnitude=sum((float(e.base_min)+float(e.base_max))/2
                    for e in other.effects if isinstance(e,DamageEffect))
                return (-magnitude/max(1.,float(other.cast_time_s),float(other.gcd_s)),
                        float(other.cast_time_s),other.id)
            if fillers:
                filler=min(fillers,key=filler_priority)
                rules.append((filler.id,guard+_semantic_guards(filler)))

        # A talent witness must be a persistent *policy*, not a one-off cast.
        # When its resource producer is cooling down, discover an executable
        # alternative damage mode and the paid routes in both directions.
        # Prefer source-declared auto-attack modes over a spell-only mode so
        # that the fallback can actually continue between GCDs.
        fallback = None
        if len(paid_producers) == 1 and float(paid_producers[0][0].cooldown_s) > 0:
            producer, cost = paid_producers[0]
            alternative = fallback_damage_mode(target_mode)
            if alternative is not None:
                _, _, _, fallback_mode, filler, outward, inward = alternative
                cooldown_off = (PolicyCondition(kind='cooldown_ready', field=producer.id,
                                               operator='eq', value=False),)
                cooldown_on = (PolicyCondition(kind='cooldown_ready', field=producer.id,
                                              operator='eq', value=True),)
                producer_periodics = pending_resource_guards(producer, cost)
                for i, (mode, edge) in enumerate(outward):
                    extra = ((PolicyCondition(kind='resource_threshold',
                        resource_id=cost.resource_id, operator='lt',
                        value=float(cost.amount)),) + producer_periodics) if i == 0 else ()
                    rules.append((edge.id, (PolicyCondition(kind='mode_state',
                        operator='eq', value=mode),) + cooldown_off + extra))
                for mode, edge in inward:
                    rules.append((edge.id, (PolicyCondition(kind='mode_state',
                        operator='eq', value=mode),) + cooldown_on))
                rules.append((filler.id, (PolicyCondition(kind='mode_state',
                    operator='eq', value=fallback_mode),) + _semantic_guards(filler)))
                fallback = {'mode':fallback_mode,'damage_action':filler.id,
                            'resource_producer':producer.id}
        if fallback is None:
            rules.extend((edge.id, (PolicyCondition(kind='mode_state',operator='eq',value=mode),))
                         for mode, edge in path)
        policy = from_source_rules(selected_ir, rules,
                                   provenance='source_talent_unlock_witness')
        witnesses.append({'source_talent_id': source_talents[0],
                          'action_id': action.id,
                          'mode_path': tuple(edge.id for _, edge in path),
                          'policy': policy,
                          'coverage_status': 'GENERATED_NOT_EXECUTED'})
    return tuple(witnesses)


def _source_mode_cycles(ir, stage, *, max_candidates=8):
    """Discover a source-legal in-combat heal/form cycle, not a class rotation.

    All mode edges, heal actions, costs and damage actions are from GameIR.
    HP hysteresis is a search-policy parameter, not a claimed game mechanic.
    """
    current = _source_opening_mode(ir, stage)
    modes = {mode.id: mode for mode in ir.modes}
    if current not in modes:
        return ()
    def usable(action, mode_id):
        mode = modes[mode_id]
        if action.owner_actor_id != ir.actor.id:
            return False
        if mode.enabled_action_ids is not None and action.id not in mode.enabled_action_ids:
            return False
        return all(req.get('kind') != 'mode_is' or str(req.get('value')) == mode_id
                   for req in action.requirements)
    def mode_edge(action, mode_id):
        if not usable(action, mode_id):
            return ()
        return tuple(effect.target_mode_id for effect in action.effects
                     if isinstance(effect, ModeChangeEffect))
    def guard(mode_id):
        return PolicyCondition(kind='mode_state',operator='eq',value=mode_id)
    def hp(op, threshold):
        return PolicyCondition(kind='actor_state',field='health_pct',
                               operator=op,value=threshold)
    # The current mode's sourced damage actions supply the offensive policy.
    context = _source_opening_context_ir(ir, stage)
    pairs, attacks = _source_damage_priority_specs(context)
    damage_specs = [tuple(a for a in pair) for pair in pairs[:2]]
    damage_specs.extend((a,) for a in attacks[:2])
    candidates = []
    seen = set()
    for healing_mode in modes:
        if healing_mode == current:
            continue
        exits = sorted((a for a in ir.actions if healing_mode in mode_edge(a,current)),
                       key=lambda a:a.id)
        entries = sorted((a for a in ir.actions if current in mode_edge(a,healing_mode)),
                         key=lambda a:a.id)
        heals = sorted((a for a in ir.actions if usable(a,healing_mode)
                        and any(isinstance(e,(HealEffect,PeriodicHealEffect))
                                and e.target in ('self','actor') for e in a.effects)),
                       key=_source_action_rank_order)
        if not exits or not entries or not heals:
            continue
        for exit_action in exits[:2]:
            for entry_action in entries[:2]:
                for heal in heals[:3]:
                    for attacks_spec in damage_specs:
                        for low,high in ((.35,.70),(.50,.80)):
                            heal_gates=tuple(c for c in _semantic_guards(heal)
                                if not (c.kind=='actor_state' and c.field=='health_pct'))
                            rules = [
                                (exit_action.id,(guard(current),hp('lte',low),
                                                 *_semantic_guards(exit_action))),
                                (heal.id,(guard(healing_mode),hp('lte',high),*heal_gates)),
                                (entry_action.id,(guard(healing_mode),hp('gte',high),
                                                  *_semantic_guards(entry_action))),
                            ]
                            rules.extend((a.id,(guard(current),*_semantic_guards(a)))
                                         for a in attacks_spec)
                            try:
                                policy=from_source_rules(ir,rules,
                                    provenance='joint_source_mode_cycle')
                            except ValueError:
                                continue
                            sig=policy_identity(policy)
                            if sig not in seen:
                                seen.add(sig);candidates.append(policy)
                                if len(candidates)>=max_candidates:
                                    return tuple(candidates)
    return tuple(candidates)


def _source_action_rank_order(action):
    """Prefer stronger source ranks within a family without deleting downranks."""
    rank = action.metadata.get('source_spell_rank')
    if rank is None:
        rank = next((p.get('source_rank') for p in action.provenance
                     if p.get('source_rank') is not None), 0)
    return (str(action.family_key or action.name), -int(rank), action.id)


def _source_damage_priority_specs(ir):
    """Prefer source periodic upkeep then direct filler; no class/ability IDs."""
    direct = (DamageEffect, WeaponDamageEffect, ResourceScaledDirectDamageEffect)
    periodic = (PeriodicEffect, ResourceScaledPeriodicEffect)
    attacks = [a for a in ir.actions if a.owner_actor_id == ir.actor.id
               and any(isinstance(e, direct + periodic) for e in a.effects)]
    source_rank_order = _source_action_rank_order
    dot = sorted((a for a in attacks if any(isinstance(e, periodic) for e in a.effects)),
                 key=source_rank_order)
    filler = sorted((a for a in attacks if any(isinstance(e, direct) for e in a.effects)
                     and not any(isinstance(e, periodic) for e in a.effects)),
                    key=source_rank_order)
    all_attacks = sorted(attacks,key=source_rank_order)
    pairs = [(a,b) for a in dot for b in filler if a.id != b.id]
    seen = {(a.id,b.id) for a,b in pairs}
    for first in all_attacks:
        for second in all_attacks:
            key = (first.id,second.id)
            if first.id != second.id and key not in seen:
                pairs.append((first,second))
                seen.add(key)
    return pairs, all_attacks


def source_compositional_policies(ir, *, max_candidates=96):
    """Generate whole source-effect strategies rather than tweaking fixed rotations.

    Effect/requirement/resource/target relationships select the APL topology.
    There are NO class, talent, ability, or source spell identifiers here.
    A generated policy is only a candidate: the ordinary paid executor and
    search decide whether it is useful or even survives the encounter.
    """
    if max_candidates < 1:
        raise ValueError('INVALID_COMPOSITION_BUDGET')
    initial = next((m.id for m in ir.modes if m.initial), None)
    if initial is None:
        return ()
    edges = _source_mode_transition_edges(ir)
    periodic = (PeriodicEffect, ResourceScaledPeriodicEffect)
    direct = (DamageEffect, WeaponDamageEffect, ResourceScaledDirectDamageEffect)
    buckets = defaultdict(list)
    seen = set()
    modes = sorted(m.id for m in ir.modes)

    def choose(acts):
        # Preserve the strongest available rank of each action family in each
        # reachable form. Lower ranks remain available in other search pools.
        by_family = {}
        for a in sorted(acts, key=_source_action_rank_order):
            by_family.setdefault(a.family_key or a.id, a)
        return list(by_family.values())

    def emit(category, mode_rules, actions):
        if not actions or len(actions) + len(mode_rules) > 8:
            return
        try:
            # A policy rule may extend the source-derived cost/effect guards
            # with an equally sourced relationship condition (e.g. a charge
            # bank threshold or periodic aura refresh). No action IDs or
            # policy templates are introduced by this API.
            def source_rule(entry):
                action = entry[0]
                extra = entry[2] if len(entry)>2 else ()
                # A sourced refresh guard replaces (rather than ANDs with)
                # the ordinary missing-aura guard for that same aura.
                refresh = {c.aura_id for c in extra if c.kind == 'aura_remaining_s'}
                explicit_health = any(c.kind == 'actor_state' and c.field == 'health_pct'
                                      for c in extra)
                proactive_hot = (any(c.kind == 'aura_missing' and c.scope == 'actor'
                                     for c in extra) and any(isinstance(e,PeriodicHealEffect)
                                     for e in action.effects))
                # Explicit policy health thresholds supersede the default
                # conservative heal threshold. Otherwise a pre-HoT at full HP
                # silently inherits the 50%-HP gate and never happens.
                guards = tuple(c for c in _semantic_guards(action)
                               if not (c.kind == 'aura_missing' and c.aura_id in refresh)
                               and not ((explicit_health or proactive_hot)
                                   and c.kind == 'actor_state' and c.field == 'health_pct'))
                return (action.id, (*guards, *extra),
                        'matching' if entry[1] else None)
            specs = tuple(mode_rules) + tuple(source_rule(entry) for entry in actions)
            candidate = from_source_rules(ir, specs,
                provenance='source_composed_'+category)
        except ValueError:
            return
        signature = policy_identity(candidate)
        if signature not in seen:
            seen.add(signature)
            buckets[category].append((category, candidate))

    for mode_id in modes:
        path = _source_shortest_mode_path(edges, initial, mode_id)
        if path is None:
            continue
        mode_rules = tuple((edge.id, (PolicyCondition(kind='mode_state',
            operator='eq', value=origin), *_semantic_guards(edge)))
            for origin, edge in path)
        legal = choose(a for a in ir.actions if a.owner_actor_id == ir.actor.id
            and a.effects and _source_actor_action_usable_in_mode(ir, a, mode_id))
        dots = [a for a in legal if any(isinstance(e, periodic) and
            getattr(e,'target',None) == 'enemy' for e in a.effects)
            and not any(isinstance(e, ControlEffect) for e in a.effects)]
        controls = [a for a in legal if any(_hostile_control(e) for e in a.effects)
            and not any(isinstance(e,direct) for e in a.effects)]
        damage = [a for a in legal if any(isinstance(e, direct) for e in a.effects)]
        fillers = [a for a in damage if not any(isinstance(e, periodic) for e in a.effects)]
        # Source-defined defensive sustain is a compositional search axis,
        # not a hardcoded healer class or copied leveling-guide rotation.
        # A reactive damage shield is already applied as paid long-lived
        # maintenance by the existing CombatRuntime (never a free APL buff).
        initial_legal = choose(a for a in ir.actions if
            a.owner_actor_id == ir.actor.id and a.effects
            and _source_actor_action_usable_in_mode(ir,a,initial))
        periodic_heals = [a for a in initial_legal if any(
            isinstance(e,PeriodicHealEffect) and e.target in ('self','actor')
            for e in a.effects)]
        direct_heals = [a for a in initial_legal if any(
            isinstance(e,HealEffect) and e.target in ('self','actor')
            for e in a.effects)]
        def heal_upkeep(action, *, threshold=None):
            aura = next((e.aura_id for e in action.effects if
                isinstance(e,PeriodicHealEffect) and e.target in ('self','actor')),None)
            if not aura:
                return (action,False)
            conditions=(PolicyCondition(kind='aura_missing',scope='actor',aura_id=aura),)
            if threshold is not None:
                conditions+=(PolicyCondition(kind='actor_state',field='health_pct',
                    operator='lte',value=threshold),)
            return (action,False,conditions)
        def heal_emergency(action):
            return (action,False,(PolicyCondition(kind='actor_state',
                field='health_pct',operator='lte',value=.45),))
        if mode_id == initial and periodic_heals:
            # Sustain + multidot permits *measured* retaliation to incoming
            # contact by the source maintenance trigger, while paying HoT costs.
            for hot in periodic_heals[:3]:
                for i,dot in enumerate(dots[:6]):
                    for other in dots[i+1:6]:
                        for filler in fillers[:2]:
                            if len({hot.id,dot.id,other.id,filler.id})==4:
                                emit('sustain_multi_dot',mode_rules,
                                     ((dot,True),(other,True),
                                      heal_upkeep(hot,threshold=.9),(filler,False)))
                                emit('prehot_multi_dot',mode_rules,
                                     ((dot,True),(other,True),
                                      heal_upkeep(hot),(filler,False)))
                                for heal in direct_heals[:2]:
                                    emit('sustain_emergency_multi_dot',mode_rules,
                                         (heal_emergency(heal),(dot,True),(other,True),
                                          heal_upkeep(hot,threshold=.9),(filler,False)))
        if mode_id == initial and periodic_heals and controls:
            # Derive a full control + multi-target periodic damage + healing
            # strategy from source effect relationships. Each hostile aura
            # rule selects a target that needs the effect, instead of casting
            # every spell only on the primary enemy. An attack filler is still
            # needed so this strategy eventually finishes the encounter.
            for control in controls[:3]:
                for i, dot in enumerate(dots[:6]):
                    for other in dots[i+1:6]:
                        for hot in periodic_heals[:2]:
                            for filler in fillers[:3]:
                                if len({control.id,dot.id,other.id,hot.id,filler.id})!=5:
                                    continue
                                emit('sustain_control_multi_dot',mode_rules,
                                     ((control,True),(dot,True),(other,True),
                                      heal_upkeep(hot,threshold=.9),(filler,False)))
                                # A distinct sustain/no-refresh candidate is
                                # useful for reactive defenses: melee contact
                                # can be worth more than interrupting GCDs.
                                emit('prehot_control_multi_dot',mode_rules,
                                     (heal_upkeep(hot),(control,True),
                                      (dot,True),(other,True),(filler,False)))
        if mode_id != initial and mode_rules and periodic_heals:
            # Pre-cast a legal HoT / DoT in the source initial form, then
            # enter an eligible defensive form and cleave with its sourced
            # damage/resource effects. The form path is derived from GameIR.
            initial_dots=[a for a in initial_legal if any(isinstance(e,periodic)
                and getattr(e,'target',None)=='enemy' for e in a.effects)
                and not any(isinstance(e,ControlEffect) for e in a.effects)]
            cleaves=[a for a in damage if int(a.metadata.get('max_targets',1))>1]
            producers=[a for a in legal if any(isinstance(e,ResourceChangeEffect)
                and e.operation=='add' for e in a.effects)]
            mitigations=[a for a in legal if any(
                isinstance(e,ControlEffect) or type(e).__name__=='TargetStatDebuffEffect'
                for e in a.effects)]
            for hot in periodic_heals[:2]:
                for cleave in cleaves[:3]:
                    for producer in producers[:2] or [None]:
                        after=tuple(((a,False) for a in
                            ((*mitigations[:1],*([producer] if producer else []),cleave))))
                        for dot in initial_dots[:4]:
                            if len({dot.id,hot.id,cleave.id})==3:
                                emit('prehot_mode_cleave',
                                     ((dot.id,_semantic_guards(dot),'matching'),
                                      (hot.id,tuple(c for c in _semantic_guards(hot)
                                            if not (c.kind=='actor_state' and c.field=='health_pct'))+
                                            (PolicyCondition(kind='aura_missing',scope='actor',
                                                aura_id=next(e.aura_id for e in hot.effects
                                                    if isinstance(e,PeriodicHealEffect))),)),
                                      *mode_rules),after)
                        emit('prehot_mode_cleave',
                             ((hot.id,tuple(c for c in _semantic_guards(hot)
                                     if not (c.kind=='actor_state' and c.field=='health_pct'))+
                                     (PolicyCondition(kind='aura_missing',scope='actor',
                                         aura_id=next(e.aura_id for e in hot.effects
                                             if isinstance(e,PeriodicHealEffect))),)),*mode_rules),
                             after)
        # Prefer efficient maintenance (apply aura only when absent), then
        # filler. Both target selectors and aura IDs come from live GameIR.
        for dot in dots[:8]:
            for filler in fillers[:5]:
                if dot.id != filler.id:
                    emit('upkeep',mode_rules,((dot,True),(filler,False)))
        for control in controls[:5]:
            for filler in fillers[:5]:
                if control.id != filler.id:
                    emit('control_filler',mode_rules,((control,True),(filler,False)))
            for dot in dots[:6]:
                for filler in fillers[:4]:
                    if len({control.id,dot.id,filler.id}) == 3:
                        emit('control_dot_filler',mode_rules,
                             ((control,True),(dot,True),(filler,False)))
        for i,dot in enumerate(dots[:9]):
            for other in dots[i+1:9]:
                for filler in fillers[:4]:
                    if len({dot.id,other.id,filler.id}) == 3:
                        # DoT priority is an actual search dimension. The first
                        # periodic effect in source order need not be the best
                        # opener, and two auras can have different ticks/costs.
                        # Both orders are source-legal; the paid runtime decides.
                        for first,second in ((dot,other),(other,dot)):
                            emit('multi_dot',mode_rules,
                                 ((first,True),(second,True),(filler,False)))
                for control in controls[:3]:
                    for filler in fillers[:3]:
                        if len({dot.id,other.id,control.id,filler.id}) == 4:
                            emit('control_multi_dot',mode_rules,
                                 ((control,True),(dot,True),(other,True),
                                  (filler,False)))
        # Sourced cast-charge producer/consumer relationships are a strategy
        # graph, not a generic mana/energy ResourceChangeEffect.  A producer
        # that banks cast-speed charges must be paired with its beneficiary;
        # for multi-charge banks, the threshold reserves consecutive boosted
        # consumer casts. Periodic upkeep and CC join the same strategy where
        # source actions make all of them legal in the current mode.
        for consumer in legal:
            sink = consumer.metadata.get('source_cast_charge_consumer') or {}
            bank = str(sink.get('bank_id') or '')
            if not bank:
                continue
            producers = [a for a in legal if
                (a.metadata.get('source_cast_charge_producer') or {}).get('bank_id') == bank]
            for producer in producers[:3]:
                source = producer.metadata['source_cast_charge_producer']
                capacity = int(source['capacity'])
                if not 1 <= capacity <= 16 or producer.id == consumer.id:
                    continue
                # Charge thresholds are another *paid* search dimension.
                # Allow both small banks (frequent consumer casts) and large
                # banks (bursty consumers), rather than baking in one rule.
                # The values depend solely on the source-defined bank.
                default_threshold = max(1,capacity - max(1,int(source['grant_per_cast'])-1))
                charge_thresholds = tuple(dict.fromkeys((
                    default_threshold, int(source['grant_per_cast']), 1, capacity)))
                def upkeep(action):
                    effect = next((e for e in action.effects if isinstance(e,periodic)
                                   and e.target == 'enemy'),None)
                    if effect is None:
                        return (action,True)
                    period = float(getattr(effect,'tick_interval_s',0) or 0)
                    threshold = max(0.0,min(2.0,period*.5))
                    return (action,True,(PolicyCondition(kind='aura_remaining_s',
                        scope='target',aura_id=effect.aura_id,operator='lte',value=threshold),))
                for threshold in charge_thresholds:
                    charge_cond = (PolicyCondition(kind='stored_cast_charges',
                        field=bank,operator='gte',value=threshold),)
                    tail = ((consumer,False,charge_cond),(producer,False))
                    if mode_id == initial and periodic_heals and controls:
                        # Compose charged casts with paid sustain and actual
                        # multiple targets; the source engine enforces guards.
                        for control in controls[:2]:
                            for i,dot in enumerate(dots[:5]):
                                for other in dots[i+1:5]:
                                    for hot in periodic_heals[:1]:
                                        if len({control.id,dot.id,other.id,hot.id,
                                                consumer.id,producer.id})==6:
                                            for first,second in ((dot,other),(other,dot)):
                                                emit('sustain_charge_control_multi_dot',mode_rules,
                                                     ((control,True),upkeep(first),upkeep(second),
                                                      heal_upkeep(hot,threshold=.9),*tail))
                    emit('charge_cycle',mode_rules,tail)
                    for dot in dots[:6]:
                        emit('charge_dot',mode_rules,(upkeep(dot),*tail))
                    for control in controls[:3]:
                        emit('charge_control',mode_rules,((control,True),*tail))
                    for i,dot in enumerate(dots[:6]):
                        for other in dots[i+1:6]:
                            for first,second in ((dot,other),(other,dot)):
                                head = (upkeep(first),upkeep(second))
                                emit('charge_multi_dot',mode_rules,(*head,*tail))
                                for control in controls[:2]:
                                    emit('charge_control_multi_dot',mode_rules,
                                         ((control,True),*head,*tail))
        # The resource dependency graph itself yields producers -> consumers.
        # A finite-resource spender has higher priority than its producer;
        # ordinary resource availability is still decided by CombatRuntime.
        producers = defaultdict(list)
        for a in legal:
            for e in a.effects:
                if isinstance(e,ResourceChangeEffect) and e.operation=='add' and e.amount>0:
                    producers[e.resource_id].append(a)
                if isinstance(e,PeriodicResourceEffect) and e.operation=='add' and e.amount_per_tick>0:
                    producers[e.resource_id].append(a)
        for consumer in legal:
            consumed = {c.resource_id for c in consumer.costs if c.amount>0}
            for e in consumer.effects:
                if isinstance(e,(ResourceScaledPeriodicEffect,ResourceScaledDirectDamageEffect)):
                    consumed.add(e.resource_id)
            for resource_id in sorted(consumed):
                for producer in choose(producers.get(resource_id,()))[:6]:
                    if producer.id == consumer.id:
                        continue
                    sequence = ((consumer,any(isinstance(e,periodic) for e in consumer.effects)),
                                (producer,any(isinstance(e,periodic) for e in producer.effects)))
                    emit('resource_cycle',mode_rules,sequence)
                    for filler in fillers[:3]:
                        if len({consumer.id,producer.id,filler.id}) == 3:
                            emit('resource_cycle_filler',mode_rules,
                                 (*sequence,(filler,False)))
        # A sourced conditional target-aura bonus is a *relationship* between
        # a periodic physical producer and a physical beneficiary, regardless
        # of class, spec, or spell names.
        bleeds = [a for a in dots if any(isinstance(e,periodic)
                   and e.school.lower()=='physical' and e.aura_id.endswith(':bleed')
                   for e in a.effects)]
        affected = [a for a in legal if
                    any(m.get('aura_category')=='bleed' for m in
                        a.metadata.get('conditional_target_aura_damage_multipliers',()))
                    and any(isinstance(e,direct) and e.school.lower()=='physical'
                            for e in a.effects)]
        for bleed in bleeds[:6]:
            for strike in affected[:6]:
                if bleed.id != strike.id:
                    emit('conditional_aura',mode_rules,((bleed,True),(strike,False)))
                    for consumer in (a for a in dots[:6] if a.id != bleed.id
                        and any(isinstance(e,ResourceScaledPeriodicEffect) for e in a.effects)):
                        if len({bleed.id,strike.id,consumer.id}) == 3:
                            emit('conditional_aura_finisher',mode_rules,
                                 ((consumer,True),(bleed,True),(strike,False)))
        # Every sourced mode must admit its direct attack, even if not otherwise
        # paired. In Bear this includes spenders whose rage producers are above.
        for attack in fillers[:8]:
            emit('single_mode_damage',mode_rules,((attack,False),))

    # Balanced round-robin across *strategy families*, not numeric variants
    # or alphabetical actions. A bounded search now preserves compound paths.
    order = ('sustain_multi_dot','sustain_control_multi_dot','prehot_control_multi_dot',
             'sustain_charge_control_multi_dot','prehot_multi_dot',
             'sustain_emergency_multi_dot','prehot_mode_cleave',
             'charge_control_multi_dot','charge_multi_dot','charge_dot',
             'charge_control','charge_cycle',
             'control_multi_dot','multi_dot','conditional_aura_finisher',
             'resource_cycle_filler','control_dot_filler','conditional_aura',
             'resource_cycle','control_filler','upkeep','single_mode_damage')
    out=[];idx=0
    while len(out)<max_candidates:
        progressed=False
        for family in order:
            pool=buckets.get(family,())
            if idx < len(pool):
                out.append(pool[idx]);progressed=True
                if len(out)>=max_candidates:
                    break
        if not progressed:
            break
        idx+=1
    return tuple(out)


def _scratch_damage_priority(policy, damaging_ids):
    """Prioritize executable damage, never discard no-cast or utility APLs."""
    damage_rules = sum(rule.action_id in damaging_ids for rule in policy.rules)
    if len(policy.rules) == 1 and damage_rules:
        return 0
    return 1 if damage_rules else 2


def source_joint_policy_frontier(ir, seed_stage, *, max_policies,
                                 include_mode_cycles=False):
    """Interleave source-only scratch, mutation and damage-policy APLs.

    Reuses the canonical policy-evolution grammar and the existing persistent
    runtime; no ability/class whitelist or legacy policy is introduced.
    """
    if not 1 <= max_policies <= 256:
        raise ValueError('INVALID_SOURCE_JOINT_POLICY_BUDGET')
    context_ir = _source_opening_context_ir(ir, seed_stage)
    record = seed_stage['gear_policy_result']['winner']['winner']
    incumbent = _make_policy(context_ir, record['fallback'],
        guarded_action=record.get('guarded_action'),
        guarded_conditions=tuple(_condition_from_record(c)
                                 for c in record.get('guarded_conditions', ())))
    validate_policy(incumbent, context_ir.actions)
    pools = {'compound': [], 'control_opening': [], 'damage_pair': [], 'mode_cycle': [], 'mutation': [],
             'scratch': [], 'damage_single': []}
    pools['compound'] = [p for _,p in source_compositional_policies(
        context_ir,max_candidates=max(32,max_policies*3))]
    pairs, attacks = _source_damage_priority_specs(context_ir)
    # Source-derived movement-control opener followed by a sourced damage
    # filler. The control is not spammable: PolicyCondition follows the actual
    # target control state. No mage/druid/ability preset or extra combat engine.
    rooted = sorted((a for a in context_ir.actions if any(
        _hostile_control(e) and e.control_id == 'root'
        for e in a.effects)), key=_source_action_rank_order)
    for control in rooted[:8]:
        for filler in attacks[:3]:
            if control.id == filler.id:
                continue
            try:
                pools['control_opening'].append(from_source_rules(context_ir, (
                    (control.id, _semantic_guards(control)),
                    (filler.id, _semantic_guards(filler))),
                    provenance='joint_source_movement_control'))
            except ValueError:
                continue
    if include_mode_cycles:
        pools['mode_cycle'] = list(_source_mode_cycles(ir, seed_stage,
            max_candidates=max(8, max_policies)))
    for first, second in pairs[:max(32,max_policies*4)]:
        try:
            pools['damage_pair'].append(from_source_rules(context_ir, (
                (first.id,_semantic_guards(first)),
                (second.id,_semantic_guards(second))),provenance='joint_source_damage'))
        except ValueError:
            continue
    for action in attacks[:max(32,max_policies*4)]:
        try:
            pools['damage_single'].append(from_source_rules(context_ir,
                ((action.id,_semantic_guards(action)),),provenance='joint_source_damage'))
        except ValueError:
            continue
    pools['mutation'] = list(mutations(incumbent, context_ir,
        max_candidates=max(32, max_policies * 4), max_rules=4))
    scratch = list(scratch_policies(context_ir,
        max_candidates=max(64, max_policies * 4), max_rules=4))
    damaging_ids = {a.id for a in attacks}
    pools['scratch'] = sorted(scratch,
        key=lambda policy: _scratch_damage_priority(policy,damaging_ids))
    frontier = [('incumbent', incumbent)]
    seen = {policy_identity(incumbent)}
    offset = 0
    while len(frontier) < max_policies:
        progress = False
        for origin, pool in pools.items():
            if offset >= len(pool):
                continue
            candidate = pool[offset]
            signature = policy_identity(candidate)
            if signature not in seen:
                seen.add(signature)
                frontier.append((origin, candidate))
                progress = True
                if len(frontier) >= max_policies:
                    break
        if not progress and all(offset >= len(pool)-1 for pool in pools.values()):
            break
        offset += 1
    return tuple(frontier)


def _source_conditional_aura_policy_witnesses(selected_ir):
    """Build IR-derived bleed-upkeep → melee policies for conditional talents.

    A passive bonus needs a *policy that makes its condition true*, not merely
    a nonzero rank in a legal talent allocation.  No class, ability name or
    source talent ID is embedded in the optimizer.
    """
    from src.game.model import PolicyCondition
    supported=[]
    for action in selected_ir.actions:
        if not any(rule.get('aura_category') == 'bleed' for rule in
                   action.metadata.get('conditional_target_aura_damage_multipliers',())):
            continue
        if not any(isinstance(e,(DamageEffect,WeaponDamageEffect,ResourceScaledDirectDamageEffect))
                   and e.school.lower()=='physical' for e in action.effects):
            continue
        supported.append(action)
    if not supported:return ()
    bleeds=[]
    for action in selected_ir.actions:
        for effect in action.effects:
            if (isinstance(effect,(PeriodicEffect,ResourceScaledPeriodicEffect))
                    and effect.target == 'enemy' and effect.school.lower() == 'physical'
                    and effect.aura_id.endswith(':bleed')):
                bleeds.append((action,effect.aura_id))
    modes={mode.id:mode for mode in selected_ir.modes}
    initial=next((mode.id for mode in selected_ir.modes if mode.initial),None)
    if initial is None:
        return ()
    edges=_source_mode_transition_edges(selected_ir)

    def path_to(target):
        return _source_shortest_mode_path(edges,initial,target)

    found=[]
    for bleed,aura_id in sorted(bleeds,key=lambda item:_source_action_rank_order(item[0])):
        for damage in sorted(supported,key=_source_action_rank_order):
            if bleed.id == damage.id:
                continue
            required_modes={str(req['value']) for action in (bleed,damage)
                            for req in action.requirements if req.get('kind')=='mode_is'}
            if len(required_modes)>1:
                continue
            path=path_to(next(iter(required_modes),initial))
            if path is None:
                continue
            mode_rules=tuple((edge.id,(PolicyCondition(kind='mode_state',
                operator='eq',value=mode_id),)) for mode_id,edge in path)
            try:
                policy=from_source_rules(selected_ir,mode_rules+(
                    (bleed.id,(*_semantic_guards(bleed), PolicyCondition(
                        kind='aura_missing',scope='target',aura_id=aura_id))),
                    (damage.id,_semantic_guards(damage))),
                    provenance='source_conditional_target_aura_damage')
                found.append(('talent_condition:'+aura_id+':'+damage.id,policy))
                return tuple(found)  # reserve one real policy within 30s
            except ValueError:
                continue
    return ()



def _source_charge_witness_policy(ir, *, path, producer, consumer, bank):
    """Construct one sourced stateful producer/consumer APL, without game IDs."""
    mode_rules=tuple((edge.id,(PolicyCondition(kind='mode_state',
        operator='eq',value=origin),*_semantic_guards(edge)))
        for origin,edge in path)
    return from_source_rules(ir,mode_rules+(
        (consumer.id,(PolicyCondition(kind='stored_cast_charges',
            field=bank,operator='gte',value=1),*_semantic_guards(consumer))),
        (producer.id,_semantic_guards(producer))),
        provenance='source_talent_stateful_charge_witness')


def _source_modified_action_policy_witnesses(base_ir, selected_ir, allocation, seed_stage):
    """Pay for source actions actually modified by the selected legal talent.

    Action identity, affected family, mode transitions and combat rules all
    come from GameIR. An unchanged action or an unexecutable mode is not a
    witness. One high-information policy is reserved per allocation.
    """
    before = {action.id: action for action in base_ir.actions}
    selected_by_family = defaultdict(list)
    for action in selected_ir.actions:
        if action.id in before and action.owner_actor_id == selected_ir.actor.id:
            selected_by_family[action.family_key].append(action)
    initial = _source_opening_mode(base_ir, seed_stage)
    modes = {mode.id: mode for mode in selected_ir.modes}
    if initial not in modes:
        return ()


    edges = _source_mode_transition_edges(selected_ir)

    direct = (DamageEffect, WeaponDamageEffect, ResourceScaledDirectDamageEffect,
              PeriodicEffect, ResourceScaledPeriodicEffect)
    candidates = []
    for talent in base_ir.talents:
        selected_rank = int(allocation.get(talent.id, 0))
        if not selected_rank:
            continue
        row = next((r for r in talent.ranks if int(r.rank) == selected_rank), None)
        if row is None:
            continue
        for modifier in row.modifiers:
            if modifier.kind != 'cast_charge_exchange':
                continue
            source=modifier.provenance
            bank=str(source.get('bank_id') or '')
            producer_family=str(source.get('producer_family') or '')
            consumer_family=str(source.get('consumer_family') or '')
            if not bank or not producer_family or not consumer_family:
                continue
            producers=selected_by_family.get(producer_family,())
            consumers=selected_by_family.get(consumer_family,())
            for mode_id in sorted(modes):
                path=_source_shortest_mode_path(edges,initial,mode_id)
                if path is None:
                    continue
                eligible_producers=[a for a in producers if
                    _source_actor_action_usable_in_mode(selected_ir,a,mode_id)
                    and (a.metadata.get('source_cast_charge_producer') or {}).get('bank_id')==bank]
                eligible_consumers=[a for a in consumers if
                    _source_actor_action_usable_in_mode(selected_ir,a,mode_id)
                    and (a.metadata.get('source_cast_charge_consumer') or {}).get('bank_id')==bank]
                if not eligible_producers or not eligible_consumers:
                    continue
                producer=min(eligible_producers,key=_source_action_rank_order)
                consumer=min(eligible_consumers,key=_source_action_rank_order)
                try:
                    policy=_source_charge_witness_policy(selected_ir,path=path,
                        producer=producer,consumer=consumer,bank=bank)
                except ValueError:
                    continue
                candidates.append(((-100,-selected_rank,
                    _source_action_rank_order(consumer),talent.id),
                    'talent_modified:charge:'+talent.id+':'+consumer.id,policy))
                break
        by_family = defaultdict(list)
        for modifier in row.modifiers:
            if modifier.target_type == 'action_family' and modifier.target_id:
                by_family[str(modifier.target_id)].append(modifier)
        for family, modifiers in by_family.items():
            for action in selected_by_family[family]:
                old = before[action.id]
                changed = any(getattr(action, field) != getattr(old, field) for field in
                    ('cast_time_s', 'gcd_s', 'cooldown_s', 'costs', 'effects', 'requirements'))
                if not changed or not any(isinstance(e, direct) for e in action.effects):
                    continue
                for mode_id in sorted(modes):
                    if not _source_actor_action_usable_in_mode(selected_ir, action, mode_id):
                        continue
                    path = _source_shortest_mode_path(edges, initial, mode_id)
                    if path is None:
                        continue
                    mode_rules = tuple((edge.id, (PolicyCondition(kind='mode_state',
                        operator='eq', value=origin), *_semantic_guards(edge)))
                        for origin, edge in path)
                    try:
                        policy = from_source_rules(selected_ir, mode_rules + (
                            (action.id, _semantic_guards(action)),),
                            provenance='source_talent_modified_action')
                    except ValueError:
                        continue
                    label = 'talent_modified:' + talent.id + ':' + action.id
                    priority = (-len(modifiers), -selected_rank,
                                _source_action_rank_order(action), talent.id)
                    candidates.append((priority, label, policy))
                    break
    if not candidates:
        return ()
    candidates.sort(key=lambda row: row[0])
    _, label, policy = candidates[0]
    return ((label, policy),)


def _source_priority_witness_probes(variants):
    """Unique source-unlock probes first; then bounded changed-action probes."""
    unlocks = {}
    for talent_i, policies in enumerate(variants):
        for policy_i, (label, policy) in enumerate(policies):
            if label.startswith('talent_unlock:') and label not in unlocks:
                unlocks[label] = (talent_i, 0, policy_i, 0, len(policy.rules))
    # A complex mode/resource unlock needs a dedicated paid witness even when
    # a tight budget also contains modified-action probes. Deduplicate the
    # same unlocked action across alternative full-point allocations.
    unlock_probes = [(i, gear, policy, recovery) for i, gear, policy, recovery, _
        in sorted(unlocks.values(), key=lambda row: (-row[4], row[0], row[2]))[:8]]
    # Give every admitted talent allocation at least ONE actually paid
    # compound policy before spending thousands of screens on nearby single
    # action/gear edits. These are generated from source effects; the prefix
    # is NOT an oracle/hand-curated rotation and can lose the paid comparison.
    compound_origins={'sustain_multi_dot','prehot_multi_dot','sustain_emergency_multi_dot',
        'prehot_mode_cleave','charge_control_multi_dot','charge_multi_dot','charge_dot',
        'charge_control','charge_cycle','control_multi_dot','multi_dot','conditional_aura_finisher',
        'resource_cycle_filler','control_dot_filler','conditional_aura',
        'resource_cycle','control_filler','upkeep'}
    composed=[]
    for talent_i, policies in enumerate(variants):
        matched=next((policy_i for policy_i,(label,_) in enumerate(policies)
            if label in compound_origins),None)
        if matched is not None:
            composed.append((talent_i,0,matched,0))
    modified_probes = [(i, 0, 0, 0) for i, policies in enumerate(variants)
        if policies and policies[0][0].startswith('talent_modified:')][:8]
    return (*unlock_probes, *composed, *modified_probes)


def _source_gear_witness_probes(gear_stages, *, max_probes=2):
    """Reserve paid screens for source-legal mixed-stat packages only."""
    return tuple((0,i,0,0) for i,(label,_) in enumerate(gear_stages)
        if label.startswith('source_stat_package:') and '+' in label)[:max_probes]


def _source_witness_first_coordinates(dimensions, variants, proposal_strategy, attempted, *, gear_stages=()):
    """Prioritize paid source witnesses without corrupting marginal pilot scores.

    Marginal pilots are interpreted by their *coordinate*, not by the row's
    position in the changed execution order. The original four-axis model
    and its complete suffix are retained after the bounded witness prefix.
    """
    if not dimensions or any(d <= 0 for d in dimensions):
        return
    priority = _source_priority_witness_probes(variants)
    # Preserve source unlocks before paid hybrid gear screens.
    gear_probes=_source_gear_witness_probes(gear_stages)
    seen = set()
    coord_index = {}
    for coords in (*priority, *gear_probes, (0, 0, 0, 0)):
        if coords not in seen:
            coord_index[coords] = len(coord_index)
            seen.add(coords)
            yield coords
    if proposal_strategy == 'marginal_screen':
        pilot_rows = []
        original = _marginal_screen_coordinates(dimensions, pilot_rows)
        anchor_count = 1 + sum(size - 1 for size in dimensions)
        for _ in range(anchor_count):
            anchor = next(original)
            if anchor not in seen:
                coord_index[anchor] = len(coord_index)
                seen.add(anchor)
                yield anchor
            pilot_rows.append(attempted[coord_index[anchor]])
    else:
        original = _diagonal_coordinates(dimensions)
    for coords in original:
        if coords not in seen:
            seen.add(coords)
            yield coords


def _source_talent_policy_variants(compiled, talents, seed_stage, policies, *, level, bonus_talent_points=0):
    """Preserve the paid four-axis search while specializing source APLs by talent.

    The policy-axis length is unchanged for deterministic journal replay. A
    source-granted action must be attempted with a real paid screen; this
    helper never labels a generated APL as executed or certified.
    """
    from src.game.talents import apply_talent_selection
    policies_by_talent=[]
    expected_unlocks={}
    preparation_blockers=[]
    for allocation in talents:
        # A failure constructing ONE special unlock witness must not discard
        # unrelated executable compound policies for the whole talent build.
        try:
            selected_ir,_=apply_talent_selection(compiled,allocation,level=level,
                bonus_talent_points=bonus_talent_points)
        except (ValueError,KeyError) as exc:
            preparation_blockers.append({'allocation':dict(allocation),
                'reason':str(exc)[:320]})
            policies_by_talent.append(tuple(policies))
            continue
        compositions=source_compositional_policies(selected_ir,
            max_candidates=max(32,len(policies)*3))
        before={a.id:a for a in compiled.actions}
        relevance={}
        for action in selected_ir.actions:
            previous=before.get(action.id)
            if previous is None:
                relevance[action.id]=8  # a real new source-granted action
                continue
            # Structural multi-target / conditional relationships carry more
            # strategy information than broad filler-cost/passive stat edits.
            score=0
            for key in ('source_control_target_caps',
                        'conditional_target_aura_damage_multipliers',
                        'source_cast_charge_consumer','source_cast_charge_producer'):
                if action.metadata.get(key)!=previous.metadata.get(key):
                    score+=5
            if action.effects!=previous.effects:
                score+=2
            if (action.costs!=previous.costs or action.cast_time_s!=previous.cast_time_s
                    or action.gcd_s!=previous.gcd_s or action.cooldown_s!=previous.cooldown_s):
                score+=1
            if action.requirements!=previous.requirements:
                score+=2
            if score:
                relevance[action.id]=score
        # Rank relationship-rich combinations ahead of incidental generic
        # passives; no class/talent IDs and no preferred winner is supplied.
        compositions=tuple(entry for _,entry in sorted(enumerate(compositions),
            key=lambda item:(-sum(relevance.get(rule.action_id,0)
                for rule in item[1][1].rules), item[0])))
        try:
            witnesses=source_talent_unlock_witnesses(compiled,selected_ir,seed_stage)
        except (ValueError,KeyError) as exc:
            preparation_blockers.append({'allocation':dict(allocation),
                'reason':str(exc)[:320]})
            witnesses=()
        try:
            modified=_source_modified_action_policy_witnesses(
                compiled,selected_ir,allocation,seed_stage)
            conditional=_source_conditional_aura_policy_witnesses(selected_ir)
        except (ValueError,KeyError) as exc:
            preparation_blockers.append({'allocation':dict(allocation),
                'reason':str(exc)[:320]})
            modified=()
            conditional=()
        variants=list(modified)
        for witness in witnesses:
            action_id=witness['action_id']
            expected_unlocks.setdefault(action_id,{'source_talent_id':witness['source_talent_id'],
                'allocation':dict(allocation)})
            variants.append(('talent_unlock:'+action_id,witness['policy']))
        variants.extend(conditional)
        # New unlocked/modifying talents get their own *compositional* APLs.
        # Existing old-base APLs alone cannot express these new relationships.
        variants.extend(compositions)
        variants.extend(policies)
        policies_by_talent.append(tuple(variants[:len(policies)]))
    return policies_by_talent,expected_unlocks,preparation_blockers


def _summarize_paid_unlock_coverage(attempted, expected_unlocks,
                                    preparation_blockers, frontier):
    """Distinguish generated, cast-only and complete paid unlock evidence.

    An action cast during a failed screen never certifies P4 coverage.
    """
    unlock_coverage={}
    for action_id,context in sorted(expected_unlocks.items()):
        witnessed=[row for row in attempted if row.get('policy_origin')=='talent_unlock:'+action_id]
        complete=[row for row in witnessed if row.get('screen_status')=='COMPLETE'
                  and int((row.get('source_action_counts') or {}).get(action_id,0))>0]
        total_casts=sum(int((row.get('source_action_counts') or {}).get(action_id,0))
                        for row in witnessed)
        unlock_coverage[action_id]={**context,
            'paid_screen_attempts':len(witnessed),
            'executed_casts':total_casts,
            'complete_paid_screens':len(complete),
            'screen_statuses':[row.get('screen_status') for row in witnessed],
            'status':('EXECUTED_IN_COMPLETE_PAID_SCREEN' if complete
                else 'CAST_EXECUTED_BUT_NO_COMPLETE_SCREEN' if total_casts
                else 'NOT_EXECUTED_P4_BLOCKED')}
    unlock_coverage_complete=(not preparation_blockers
        and not frontier.get('source_unlock_allocation_unresolved')
        and len(frontier.get('source_unlock_allocations_found',()))
            <= frontier.get('source_unlock_admitted',0)
        and all(row['complete_paid_screens']>0 for row in unlock_coverage.values()))
    return unlock_coverage,unlock_coverage_complete


def _recovery_variants(ir, stage, max_recovery_policies):
    """Infer a paid threshold policy and any required form cycle from GameIR."""
    variants=[('always',None)]
    if max_recovery_policies<=1:return variants
    modes={m.id for m in ir.modes if m.initial}
    if len(modes)>1:return variants
    initial_mode=next(iter(modes),None)
    record=stage['gear_policy_result']['winner']['winner']
    enter_actions=[a for a in ir.actions for effect in a.effects
                   if isinstance(effect,ModeChangeEffect)
                   and a.id in record.get('prefix',())
                   and effect.target_mode_id!=initial_mode]
    if enter_actions:
        reentry=enter_actions[0]
        previous=[e.target_mode_id for e in reentry.effects if isinstance(e,ModeChangeEffect)]
        if not previous:return variants
        needed=previous[0]
        exit_actions=[a for a in ir.actions for e in a.effects
                      if isinstance(e,ModeChangeEffect) and e.target_mode_id==initial_mode
                      and a.id not in record.get('prefix',())]
        if not exit_actions:return variants
        # The source ability's form requirement must identify the exact mode.
        exit_actions=[a for a in exit_actions if any(
            r.get('kind')=='mode_is' and r.get('value')==needed for r in a.requirements)]
        if not exit_actions:return variants
        exit_id=exit_actions[0].id
        reentry_id=reentry.id
    else:
        exit_id=reentry_id=None
    for health,mana in ((.50,.10),(.70,.30))[:max_recovery_policies-1]:
        variants.append((f'threshold_{health:.2f}_{mana:.2f}',
            BetweenPullPolicy(health_fraction=health,mana_fraction=mana,
                              exit_action_id=exit_id,reentry_action_id=reentry_id)))
    return variants


def _joint_eval_child(queue, candidate, level, mobs, recovery_policy, timeout_s, pack_size):
    """Evaluate inside a killable process; return only bounded evidence."""
    try:
        result=evaluate_persistent_candidate(candidate,level=level,mobs=mobs,
            max_cpu_s=timeout_s,max_wall_s=timeout_s,max_total_events=200000,
            recovery_policy=recovery_policy,pack_size=pack_size)
        queue.put({k:result.get(k) for k in ('status','mean_s_per_mob','events','count',
            'mob_completed','elapsed_cpu_s','elapsed_wall_s','recovery_s',
            'packs','pack_size','spatial_mode','incoming_attacks_scheduled',
            'source_action_counts')})
    except BaseException as exc:
        queue.put({'status':'BLOCKED_RUNTIME_EXCEPTION',
                   'reason':type(exc).__name__+':'+str(exc)[:320],
                   'events':0})


def isolated_joint_evaluation(candidate, *, level, mobs, recovery_policy=None,
                              timeout_s=8.,pack_size=1):
    """Hard wall deadline including source engine and mixed recovery.

    The old persistent evaluator's compute deadline cannot stop every nested
    recovery loop. A timeout or child error is never a 100mob completion.
    """
    if (type(pack_size) is not int or not 1<=pack_size<=mobs
            or 'fork' not in mp.get_all_start_methods() or not 0<timeout_s<=120):
        raise ValueError('JOINT_CANDIDATE_REQUIRES_FORK_ISOLATION')
    ctx=mp.get_context('fork')
    queue=ctx.Queue(maxsize=1)
    worker=ctx.Process(target=_joint_eval_child,
        args=(queue,candidate,level,mobs,recovery_policy,timeout_s,pack_size))
    start=monotonic();worker.start();worker.join(timeout_s)
    if worker.is_alive():
        worker.terminate();worker.join(.4)
        if worker.is_alive():worker.kill();worker.join(.4)
        result={'status':'OS_TIMEOUT','events':0}
    else:
        try:result=queue.get(timeout=.2)
        except Exception:result={'status':'WORKER_EXIT_NO_RESULT',
                                 'exitcode':worker.exitcode,'events':0}
    queue.close();queue.join_thread()
    if result.get('status')=='COMPLETE':
        score=result.get('mean_s_per_mob')
        if score is None or not isfinite(float(score)) or float(score)<=0:
            result={'status':'INVALID_FINITE_FULL_HORIZON_SCORE','events':0}
    return {**result,'outer_wall_s':monotonic()-start}


def _coordinate_order_key(coords):
    """Stable diagonal ordering: total displacement, largest axis, reverse lex."""
    return (sum(coords), max(coords), tuple(-value for value in coords))


def _diagonal_coordinates(dimensions):
    """Yield the original sorted-product order without materializing the product.

    Each axis increment increases the first key by one, so the min-heap
    visits the same prefix as eager sorting and retains only visited states.
    """
    if not dimensions or any(size <= 0 for size in dimensions):
        return
    start=(0,)*len(dimensions)
    pending=[(_coordinate_order_key(start),start)]
    seen={start}
    while pending:
        _,coords=heappop(pending)
        yield coords
        for axis,limit in enumerate(dimensions):
            if coords[axis]+1 >= limit:
                continue
            neighbor=coords[:axis]+(coords[axis]+1,)+coords[axis+1:]
            if neighbor not in seen:
                seen.add(neighbor)
                heappush(pending,(_coordinate_order_key(neighbor),neighbor))


def _marginal_screen_coordinates(dimensions, attempted):
    """Class-neutral, online four-axis proposal scheduling.

    First pay for the independent one-axis effects, then rank combinations by
    measured 4-mob marginal score. Preserve the incumbent APL early to probe
    gear/talent/recovery interactions before expensive policy cross-products.
    This ranks *screening proposals only*, never asserts additivity or P3/P5.
    Each yielded proposal is unique and every finite product is eventually
    visited, including options with incomplete pilot evidence.
    """
    if not dimensions or any(size <= 0 for size in dimensions):
        return
    root=(0,)*len(dimensions)
    anchors=[root]
    for axis,size in enumerate(dimensions):
        anchors.extend(tuple(index if k==axis else 0 for k in range(len(dimensions)))
                       for index in range(1,size))
    seen=set()
    for coords in anchors:
        seen.add(coords)
        yield coords
    # At this point the caller has recorded a source-runtime result for each
    # independent axis probe in the mutable attempted list.
    if len(attempted)<len(anchors):
        raise AssertionError('MARGINAL_SCREEN_PILOT_RESULTS_MISSING')
    raw=[row.get('screen_s_per_mob') if row.get('screen_status')=='COMPLETE'
         else None for row in attempted[:len(anchors)]]
    if raw[0] is None or not isfinite(float(raw[0])):
        for coords in _diagonal_coordinates(dimensions):
            if coords not in seen:
                seen.add(coords)
                yield coords
        return
    baseline=float(raw[0]); deltas=[[0.] for _ in dimensions]
    pos=1
    for axis,size in enumerate(dimensions):
        axis_raw=raw[pos:pos+size-1];pos+=size-1
        for score in axis_raw:
            # Failed or missing legal source effects must never be credited
            # as a free improvement by the surrogate model.
            delta=(float(score)-baseline if score is not None
                   and isfinite(float(score)) else float('inf'))
            deltas[axis].append(delta)
    # The incumbent policy (axis 2) is reserved as an early interaction probe,
    # not assumed optimal. All other policy variants remain in the suffix.
    # Ties use the original source-neutral diagonal ordering.
    from itertools import product
    # Keep memory bounded for large class-specific legal frontiers. Beyond this
    # point use the original streaming diagonal enumeration, never truncate.
    product_size=1
    for d in dimensions:product_size*=d
    if product_size>200000:
        for coords in _diagonal_coordinates(dimensions):
            if coords not in seen:
                seen.add(coords)
                yield coords
        return
    rest=[coords for coords in product(*(range(d) for d in dimensions))
          if coords not in seen]
    policy_axis=2 if len(dimensions)==4 else None
    rest.sort(key=lambda coords:(
        (coords[policy_axis]!=0) if policy_axis is not None else False,
        sum(deltas[a][value] for a,value in enumerate(coords)),
        _coordinate_order_key(coords)))
    yield from rest


def _policy_behavior_key(row):
    """Identify an actually distinct action/guard/targeting strategy.

    Talent allocation, item ordering and label are deliberately excluded:
    those are separate legal search axes, not independent APL behaviors.
    """
    rules=(row.get('policy_ir') or {}).get('rules')
    if rules is None:
        return ('opaque_policy',row.get('policy_signature',row.get('policy')))
    return tuple((rule.get('action_id'),rule.get('phase','combat'),
                  rule.get('target_selector'),
                  json.dumps(rule.get('conditions') or (),sort_keys=True,
                             separators=(',',':'))) for rule in rules)


def _select_screen_finalists(screened, max_finalists, *, score_key="screen_s_per_mob",
                             diversify_apl=False):
    """Rank paid screens; reserve full-horizon slots for distinct strategies.

    The 2-mob proxy may rank multiple talent/gear variants of one APL above
    an entirely different legal policy. Full 100mob evidence must first test
    distinct APL behaviors, then use spare slots for score-ranked variants.
    """
    ranked=sorted(screened,key=lambda x:(float(x[0][score_key]),
        _key(x[0]['allocation']),x[0]['gear_move'],x[0]['policy'],x[0]['recovery']))
    controls=[x for x in ranked if x[0].get('is_control') is True]
    finalists=[]
    seen_configs=set()
    seen_behaviors=set()
    seen_rows=set()
    def admit(entry):
        row=entry[0]
        config=(_key(row['allocation']),row['gear_move'],
                row.get('policy_signature',row['policy']))
        if config in seen_configs:return False
        seen_configs.add(config)
        seen_behaviors.add(_policy_behavior_key(row))
        finalists.append(entry)
        seen_rows.add(id(row))
        return True
    if diversify_apl:
        for entry in ranked:
            if _policy_behavior_key(entry[0]) in seen_behaviors:continue
            admit(entry)
            if len(finalists)==max_finalists:break
    if len(finalists)<max_finalists:
        for entry in ranked:
            admit(entry)
            if len(finalists)==max_finalists:break
    if len(finalists)<max_finalists:
        finalists.extend(x for x in ranked if id(x[0]) not in seen_rows)
        finalists=finalists[:max_finalists]
    if controls and not any(x[0] is controls[0][0] for x in finalists):
        finalists=finalists[:max_finalists-1]+[controls[0]]
    return finalists


def _qualify_screened_candidates(screened, *, max_qualifiers, level, mobs,
                                 deadline, per_candidate_wall_s, pack_size,
                                 on_evaluated=None,skip_evaluated=False):
    """Pay for an intermediate survival horizon; never promote partial kills."""
    qualified=[]
    evaluated=completed=events=0
    for row,candidate,recovery in _select_screen_finalists(screened,max_qualifiers):
        if skip_evaluated and 'qualification_status' in row:
            evaluated+=1
            if row['qualification_status']=='COMPLETE':
                completed+=1
                qualified.append((row,candidate,recovery))
            continue
        remaining=deadline-monotonic()
        if remaining<=0:break
        mid=isolated_joint_evaluation(candidate,level=level,mobs=mobs,
            timeout_s=min(per_candidate_wall_s,max(.01,remaining)),
            recovery_policy=recovery,pack_size=pack_size)
        evaluated+=1
        count=int(mid.get('events') or 0)
        events+=count
        row['worker_cpu_s']+=float(mid.get('elapsed_cpu_s') or 0)
        row['qualification_status']=mid['status']
        row['qualification_s_per_mob']=mid.get('mean_s_per_mob')
        row['qualification_events']=count
        if mid['status']=='COMPLETE' and isfinite(float(mid['mean_s_per_mob'])):
            completed+=1
            qualified.append((row,candidate,recovery))
        else:
            row['status']='NOT_FULL_EVALUATED_QUALIFICATION_FAILED_OR_BUDGET'
        if on_evaluated is not None:
            on_evaluated(events)
    return qualified,evaluated,completed,events


def _prepare_joint_policy_candidate(*, class_key, level, stage, allocation,
                                    source_ir, allow_partial_gear_stats,
                                    policy_label, policy, bonus_talent_points=0):
    """Identical source-legal candidate for fresh and resumed paid trials."""
    candidate=prepare_candidate(class_key=class_key,level=level,stage=stage,
        allocation_override=allocation,source_ir=source_ir,
        allow_partial_gear_stats=allow_partial_gear_stats,
        bonus_talent_points=bonus_talent_points)
    if policy_label!='incumbent':
        validate_policy(policy,candidate.ir.actions)
        candidate=replace(candidate,policy=policy,
            opening=(() if policy_label.startswith(('talent_unlock:', 'talent_condition:', 'talent_modified:')) else candidate.opening))
    return candidate


def _joint_row_identity(row):
    """Canonical four-axis search identity for reporting distinct proposals."""
    return (_key(row['allocation']),row['gear_move'],
            row['policy_signature'],row['recovery'])


def _joint_gear_move_quotas(max_gear_moves):
    """Share one legal gear-move budget across pure/mixed stats and slots."""
    if type(max_gear_moves) is not int or max_gear_moves < 0:
        raise ValueError('INVALID_JOINT_GEAR_MOVE_BUDGET')
    stat=min(5,(max_gear_moves+1)//2 + (1 if max_gear_moves>=8 else 0))
    weapon=min(2,max(0,(max_gear_moves-stat)//3))
    return stat,weapon,max_gear_moves-stat-weapon


def joint_screen_budget_fraction(*, qualification_mobs, override=None):
    """One source-neutral wall-budget policy for paid screen and finalist phases."""
    if override is not None and not 0 < float(override) < 1:
        raise ValueError('INVALID_JOINT_SCREEN_BUDGET_FRACTION')
    return float(override) if override is not None else (.45 if qualification_mobs else .50)



def _quick_joint_evaluation(candidate, *, level, mobs, recovery_policy,
                            timeout_s, pack_size, backend):
    """One canonical evaluator; direct short-horizon mode avoids fork overhead.

    Direct screening is explicitly not a killable child, so only small (<=4)
    horizons are admitted. It cannot be used for 100-mob qualification.
    """
    if backend == 'isolated':
        return isolated_joint_evaluation(candidate,level=level,mobs=mobs,
            timeout_s=timeout_s,recovery_policy=recovery_policy,pack_size=pack_size)
    if backend != 'direct' or not 1 <= mobs <= 4:
        raise ValueError('QUICK_DIRECT_REQUIRES_1_TO_4_MOBS')
    start=monotonic()
    # A 2-mob direct run can enter sourced recovery paths between runtime
    # deadline polls. Protect the *entire* evaluation with a real wall alarm.
    with _quick_candidate_wall_budget(timeout_s):
        result=evaluate_persistent_candidate(candidate,level=level,mobs=mobs,
            max_cpu_s=timeout_s,max_wall_s=timeout_s,max_total_events=200000,
            recovery_policy=recovery_policy,pack_size=pack_size)
    return {**result,'outer_wall_s':monotonic()-start}


def independently_compare_shortlist(rows, replay, *, max_mobs=100):
    """Acceptance-side replay; never charge long-run tests to 30/300s search.

    ``replay`` must independently prepare and run the pinned canonical runtime.
    A shortlist inversion is evidence that the fast proxy cannot certify its top
    candidate, not permission to conceal a faster full-horizon competitor.
    """
    if max_mobs != 100 or not rows:
        raise ValueError('100MOB_VALIDATION_REQUIRES_NONEMPTY_SHORTLIST')
    results=[]
    for row in rows:
        result=replay(row)
        count=result.get('count',result.get('mob_completed'))
        valid=(result.get('status')=='COMPLETE' and count==100
               and isfinite(float(result.get('mean_s_per_mob') or float('inf'))))
        results.append({'id':row['id'] if 'id' in row else _joint_row_identity(row),
                        'screen_s_per_mob':row.get('screen_s_per_mob'),
                        'full_s_per_mob':result.get('mean_s_per_mob') if valid else None,
                        'status':result.get('status'), 'count':count,
                        'events':result.get('events'),
                        'reason':result.get('reason')})
    full=[r for r in results if r['full_s_per_mob'] is not None]
    winning=min(full,key=lambda r:r['full_s_per_mob']) if full else None
    inverted=winning is not None and winning['id']!=results[0]['id']
    return {'status':('INCOMPLETE_FULL_HORIZON_EVIDENCE' if len(full)!=len(rows)
                      else 'SEARCH_RANKING_REVERSAL' if inverted else 'SHORTLIST_RANKING_CONFIRMED'),
            'search_winner_id':results[0]['id'],
            'validated_winner_id':winning['id'] if winning else None,
            'ranking_reversal':inverted, '100mob_replays':len(results),
            'complete_100mob_replays':len(full), 'rows':results}




def replay_joint_shortlist_100mob(search_report, *, source_ir, seed_stage,
                                 class_key, level, bonus_talent_points=0,
                                 max_per_candidate_wall_s=30., pack_size=1):
    """Independently rebuild Top N from pinned FULL config, then pay for 100 mobs.

    Runs ONLY after a search-only result exists. Source GameIR -> equipped
    items -> talently legal actor -> parsed APL -> SAME CombatRuntime.
    Never reuses a previous prepared candidate or best-score fixture.
    """
    from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition
    if not search_report.get('search_only') or not search_report.get('validation_shortlist'):
        raise ValueError('INDEPENDENT_100MOB_REQUIRES_SEARCH_ONLY_SHORTLIST')
    if search_report.get('complete_100mob_candidates'):
        raise ValueError('SEARCH_ALREADY_CONTAINS_100MOB_EVALUATIONS')
    t0=monotonic();events=0
    source_compiled,_=compile_talent_runtime(source_ir)
    policies_by_recovery=dict(_recovery_variants(source_compiled,seed_stage,4))
    def replay(row):
        nonlocal events
        missing={'equipped_gear','opening_action_ids','allocation','policy_ir','recovery'}-set(row)
        if missing:raise ValueError('INCOMPLETE_SEARCH_CONFIGURATION:'+str(sorted(missing)))
        gear=row['equipped_gear']
        stage={**seed_stage,'score_s_per_mob':None,
            'gear_policy_result':{**seed_stage['gear_policy_result'],
                'winner':{**seed_stage['gear_policy_result']['winner'],'gear':gear}}}
        prepared=prepare_candidate(class_key=class_key,level=level,stage=stage,
            allocation_override=row['allocation'],source_ir=source_compiled,
            bonus_talent_points=bonus_talent_points,allow_partial_gear_stats=True)
        constraints=search_report.get('spec_constraint') or {}
        if constraints.get('tree_key'):
            by_tree={t.id:t.tree_key for t in source_compiled.talents}
            selected=sum(int(rank) for tid,rank in row['allocation'].items()
                if by_tree.get(tid)==constraints['tree_key'])
            if selected<int(constraints['minimum_points']):
                raise ValueError('INDEPENDENT_SPEC_TREE_ALLOCATION_INVALID')
        policy_dict=row['policy_ir']
        policy=PolicyDefinition(id=policy_dict['id'],label=policy_dict['label'],
            rules=tuple(PolicyRuleDefinition(id=r['id'],action_id=r['action_id'],
                phase=r.get('phase','combat'),provenance=r.get('provenance',{}),
                conditions=tuple(PolicyCondition(**c) for c in r.get('conditions',())))
                for r in policy_dict['rules']),
            maintenance=tuple(policy_dict.get('maintenance') or ()),
            provenance=policy_dict.get('provenance') or {})
        validate_policy(policy,prepared.ir.actions)
        required_mode=constraints.get('required_combat_mode')
        mode_damage_ids=(_policy_mode_damage_action_ids(prepared.ir,policy,required_mode)
            if required_mode else frozenset())
        if required_mode and not mode_damage_ids:
            raise ValueError('INDEPENDENT_SPEC_MODE_POLICY_NOT_OFFENSIVE')
        if policy_identity(policy)!=row['policy_signature']:
            raise ValueError('SHORTLIST_APL_IDENTITY_MISMATCH')
        prepared=replace(prepared,policy=policy,
            opening=tuple(row['opening_action_ids']))
        if row['recovery'] not in policies_by_recovery:
            raise ValueError('UNKNOWN_SEARCH_RECOVERY_POLICY')
        result=isolated_joint_evaluation(prepared,level=level,mobs=100,
            timeout_s=max_per_candidate_wall_s,
            recovery_policy=policies_by_recovery[row['recovery']],pack_size=pack_size)
        events+=int(result.get('events') or 0)
        if (required_mode and result.get('status')=='COMPLETE'
                and not any(int(result.get('source_action_counts',{}).get(aid,0))>0
                            for aid in mode_damage_ids)):
            return {**result,'status':'SPEC_MODE_ACTION_NOT_EXECUTED_IN_100MOB',
                'count':result.get('mob_completed') or result.get('count')}
        return {**result,'count':result.get('mob_completed') or result.get('count')}
    shortlist=[{**row,'id':str(i)} for i,row in enumerate(search_report['validation_shortlist'])]
    compared=independently_compare_shortlist(shortlist,replay)
    compared.update(search_wall_s=search_report['wall_s'],
        wall_s_outside_search_budget=monotonic()-t0,
        total_100mob_events=events, validation_outside_search_budget=True)
    return compared


def compare_30_300_independent_100mob(search30,search300,replay):
    """P6 is a post-search replay, never a per-candidate ranking oracle."""
    t0=monotonic()
    results=[]
    for search in (search30,search300):
        winner=search.get('winner') or search.get('search_winner')
        if not winner:return {'status':'P6_FAIL','reason':'MISSING_SEARCH_WINNER'}
        result=replay(winner)
        if (result.get('status')!='COMPLETE'
                or result.get('count',result.get('mob_completed'))!=100
                or not isfinite(float(result.get('mean_s_per_mob') or float('inf')))):
            return {'status':'P6_FAIL','reason':'INCOMPLETE_100MOB_REPLAY','results':results+[result]}
        results.append(result)
    first,second=(float(x['mean_s_per_mob']) for x in results)
    return {'status':'P6_PASS' if first<=1.01*second else 'P6_FAIL',
        'T30_s_per_mob':first,'T300_s_per_mob':second,
        'ratio_T30_T300':first/second,
        'wall_s_outside_search_budgets':monotonic()-t0,
        'validation_outside_search_budgets':True,
        'events':sum(int(x.get('events') or 0) for x in results)}


def _source_legal_macro_talent_transfers(ir, allocation, *, level,
                                         bonus_talent_points):
    """Propose distant full-budget allocations via legal point-by-point paths.

    A single-point hill climb cannot cross fitness valleys between meaningful
    talent ranks. These source-only proposals transfer several points at once,
    but validate EVERY intermediate allocation, including prerequisites, tier
    gates and executable rank records. No talent names or winning builds here.
    """
    original={str(k):int(v) for k,v in allocation.items() if int(v)>0}
    candidates={}
    for donor,owned in sorted(original.items()):
        if owned<3:
            continue
        for receiver in ir.talents:
            if receiver.id==donor:
                continue
            room=int(receiver.max_rank)-original.get(receiver.id,0)
            if room<3:
                continue
            path=[]
            for steps in range(1,min(owned,room)+1):
                changed=dict(original)
                if owned==steps:
                    changed.pop(donor)
                else:
                    changed[donor]=owned-steps
                changed[receiver.id]=original.get(receiver.id,0)+steps
                try:
                    validate_talent_selection(ir,changed,level=level,
                        bonus_talent_points=bonus_talent_points)
                except ValueError:
                    break
                path.append(changed)
            if len(path)<3:
                continue
            # Offer both a medium step and the furthest fully legal step.
            # Their actual merit is established only by the paid runtime.
            for depth in sorted({3,len(path)}):
                target=tuple(sorted(path[depth-1].items()))
                candidates[target]=Neighbor(target,'macro_transfer:'+str(depth),
                    (donor,receiver.id))
    return tuple(sorted(candidates.values(),
        key=lambda n:(-int(n.operation.split(':')[1]),n.changed_ids,n.allocation)))


def _spread_candidates(pool, slots, offset):
    """Stable cyclic sampling across a sourced candidate pool."""
    if not pool or not slots:
        return ()
    stride=max(1,len(pool)//slots)
    return tuple(pool[(offset+i*stride)%len(pool)] for i in range(slots))


def _spread_full_point_talent_neighbors(ir, allocation, *, level,
                                        bonus_talent_points, count, offset):
    """Sample both local and distant legal moves without a curated build list."""
    if count<=0:
        return ()
    full_points=sum(allocation.values())
    neighbors=source_legal_talent_neighbors(ir,allocation,level=level,
        bonus_talent_points=bonus_talent_points)['neighbors']
    local=tuple(sorted((n for n in neighbors if
        sum(rank for _,rank in n.allocation)==full_points),
        key=lambda n:(n.operation,n.changed_ids,n.allocation)))
    macro=_source_legal_macro_talent_transfers(ir,allocation,level=level,
        bonus_talent_points=bonus_talent_points)
    # Reserve capacity for meaningful distant allocations; preserve local
    # exploration so single-rank improvements are never silently excluded.
    macro_slots=min(len(macro),(count+1)//2)
    local_slots=min(len(local),count-macro_slots)
    if local_slots+macro_slots<count:
        macro_slots=min(len(macro),count-local_slots)

    return (_spread_candidates(local,local_slots,offset)+
            _spread_candidates(macro,macro_slots,offset))


def _refine_screened_top_n(*, screened, class_key, level, compiled,
                           policies_by_talent, talents, bonus_talent_points,
                           max_top_n, rounds, stat_axes, probe_delta,
                           max_gear_candidates, max_policy_candidates,
                           max_talent_neighbors, spec_tree=None,
                           min_spec_points=21, required_combat_mode=None,
                           per_candidate_wall_s, deadline,
                           screen_mobs, pack_size, allow_partial_gear_stats,
                           attempted,quick_backend):
    """Live local stat gradient -> sourced equipment -> APL within one search budget.

    The quick score comes from the SAME real CombatRuntime as the global screen,
    only with a short horizon. Long-horizon replays happen outside this method.
    """
    from src.game.gear import apply_stat_delta
    from src.game.data.forever.gear import select_named_gear
    from src.rulesets.forever.items.source_equipment_semantics import validate_equipped_item_ids
    evaluated=0;events=0;cpu=0.;rows=[];stat_probes=0;gear_probes=0;policy_probes=0;talent_probes=0
    if not rounds or not screened:
        return screened,{'rounds_completed':0,'stat_probes':0,'gear_probes':0,
                          'policy_probes':0,'talent_probes':0,
                          'paid_evaluations':0,'events':0,'worker_cpu_s':0.,'rows':[]}
    top=_select_screen_finalists(screened,max_top_n)
    seen={(_joint_row_identity(r),tuple(sorted(int(x['item_id']) for x in c.source_stage['gear_policy_result']['winner']['gear']['slots'].values()))) for r,c,_ in screened}
    completed_rounds=0
    for turn in range(rounds):
        any_attempt=False
        for parent,candidate,recovery in tuple(top):
            if deadline-monotonic()<=.05:break
            original=float(parent['screen_s_per_mob'])
            # Talent neighborhoods must be paid independently of the stat
            # gradient. A different talent can improve the same equipment/APL,
            # or unlock an action that changes the best APL entirely.
            if max_talent_neighbors:
                chosen=_spread_full_point_talent_neighbors(compiled,
                    candidate.allocation,level=level,
                    bonus_talent_points=bonus_talent_points,
                    count=max_talent_neighbors,offset=turn+len(rows))
                for neighbor in chosen:
                    if deadline-monotonic()<=.05:break
                    allocation=dict(neighbor.allocation)
                    if spec_tree is not None:
                        by_tree={t.id:t.tree_key for t in compiled.talents}
                        if sum(rank for tid,rank in allocation.items()
                               if by_tree.get(tid)==spec_tree)<min_spec_points:
                            continue
                    try:
                        # A pathological source candidate must not monopolize
                        # either the 30s or 300s search during preparation.
                        with _quick_candidate_wall_budget(min(per_candidate_wall_s,
                                max(.01,deadline-monotonic()))):
                            contender=prepare_candidate(class_key=class_key,level=level,
                                stage=candidate.source_stage,allocation_override=allocation,
                                source_ir=compiled,bonus_talent_points=bonus_talent_points,
                                allow_partial_gear_stats=allow_partial_gear_stats)
                            options=[('retained_apl',candidate.policy)]
                            if max_policy_candidates>1:
                                try:
                                    options.extend(('talent_unlock:'+w['action_id'],w['policy'])
                                        for w in source_talent_unlock_witnesses(
                                            compiled,contender.ir,candidate.source_stage))
                                except (ValueError,KeyError):pass
                                options.extend(source_compositional_policies(contender.ir,
                                    max_candidates=max(4,2*max_policy_candidates)))
                        # All candidates use source-built PolicyDefinition and
                        # the same paid 2D CombatRuntime, never a proxy scorer.
                        admitted=set()
                        for label,policy in options:
                            if len(admitted)>=max(1,max_policy_candidates) or deadline-monotonic()<=.05:
                                break
                            try:
                                validate_policy(policy,contender.ir.actions)
                                signature=policy_identity(policy)
                                if signature in admitted:continue
                                admitted.add(signature)
                                if required_combat_mode and not _policy_mode_damage_action_ids(
                                        contender.ir,policy,required_combat_mode):
                                    continue
                                fresh=replace(contender,policy=policy,
                                    opening=(contender.opening if label=='retained_apl' else ()))
                                trace={'allocation':allocation,
                                    'gear_move':'talent_refined:'+str(turn+1),
                                    'policy':label,'recovery':parent['recovery'],
                                    'policy_signature':signature}
                                gear=candidate.source_stage['gear_policy_result']['winner']['gear']
                                key=(_joint_row_identity(trace),tuple(sorted(
                                    int(v['item_id']) for v in gear['slots'].values())))
                                if key in seen:continue
                                seen.add(key)
                                result=_quick_joint_evaluation(fresh,level=level,mobs=screen_mobs,
                                    backend=quick_backend,
                                    timeout_s=min(per_candidate_wall_s,max(.01,deadline-monotonic())),
                                    recovery_policy=recovery,pack_size=pack_size)
                            except (ValueError,RuntimeError,KeyError,AssertionError):continue
                            any_attempt=True;talent_probes+=1;policy_probes+=1;evaluated+=1
                            events+=int(result.get('events') or 0)
                            cpu+=float(result.get('elapsed_cpu_s') or 0.)
                            if (required_combat_mode and result['status']=='COMPLETE'
                                    and not any(int(result.get('source_action_counts',{}).get(aid,0))>0
                                        for aid in _policy_mode_damage_action_ids(
                                            fresh.ir,fresh.policy,required_combat_mode))):
                                result={**result,'status':'SPEC_COMBAT_MODE_ACTION_NOT_EXECUTED'}
                            trace.update(screen_status=result['status'],
                                screen_s_per_mob=result.get('mean_s_per_mob'),
                                status='SCREEN_COMPLETE_NOT_PROMOTED' if result['status']=='COMPLETE' else 'SCREEN_BLOCKED',
                                worker_cpu_s=float(result.get('elapsed_cpu_s') or 0.),
                                screen_events=int(result.get('events') or 0),is_control=False,
                                source_action_counts=dict(result.get('source_action_counts') or {}),
                                policy_ir=fresh.policy.as_dict(),equipped_gear=gear,
                                opening_action_ids=list(fresh.opening),refinement_round=turn+1,
                                talent_neighbor_operation=neighbor.operation)
                            rows.append(trace);attempted.append(trace)
                            if result['status']=='COMPLETE':screened.append((trace,fresh,recovery))
                    except (ValueError,RuntimeError,KeyError,AssertionError):continue
            gradient={}
            # Real finite-difference on the current gear + talent + APL. A
            # discrete zero is honestly zero, not an invented positive weight.
            for axis in stat_axes:
                if deadline-monotonic()<=.05:break
                try:
                    modified=replace(candidate,ir=apply_stat_delta(candidate.ir,axis,probe_delta))
                    result=_quick_joint_evaluation(modified,level=level,mobs=screen_mobs,
                        backend=quick_backend,
                        timeout_s=min(per_candidate_wall_s,max(.01,deadline-monotonic())),
                        recovery_policy=recovery,pack_size=pack_size)
                except (ValueError,RuntimeError,KeyError,AssertionError):continue
                any_attempt=True;stat_probes+=1;evaluated+=1
                events+=int(result.get('events') or 0)
                cpu+=float(result.get('elapsed_cpu_s') or 0.)
                if result['status']=='COMPLETE':
                    gradient[axis]=max(0.,(original-float(result['mean_s_per_mob']))/probe_delta)
            if not gradient or not any(v>0 for v in gradient.values()):
                continue
            stage=candidate.source_stage
            base=stage['gear_policy_result']['winner']['gear']
            identity=lambda gear:tuple(sorted((k,int(v['item_id'])) for k,v in gear['slots'].items()))
            origin=identity(base)
            # Multiple weight distributions prevent one lucky finite difference
            # from hiding a useful axis under an item-selection threshold.
            variants=[gradient]
            variants.extend({axis:1.} for axis,v in sorted(gradient.items(),key=lambda x:-x[1]) if v>0)
            for weights in variants[:max_gear_candidates]:
                if deadline-monotonic()<=.05:break
                try:
                    selection=select_named_gear(class_key=class_key,level=level,
                        role=base['role'],stat_weights=weights,
                        required_level_policy='observed',exclude_unknown_item_effects=True)
                    gear=selection.as_dict()
                    if identity(gear)==origin:continue
                    validate_equipped_item_ids(int(v['item_id']) for v in gear['slots'].values())
                    next_stage={**stage,'score_s_per_mob':None,
                        'stage_score_status':'QUICK_REFINEMENT_NOT_100MOB_VALIDATED',
                        'gear_policy_result':{**stage['gear_policy_result'],
                            'winner':{**stage['gear_policy_result']['winner'],'gear':gear}}}
                    contender=prepare_candidate(class_key=class_key,level=level,
                        stage=next_stage,allocation_override=candidate.allocation,
                        source_ir=compiled,bonus_talent_points=bonus_talent_points,
                        allow_partial_gear_stats=allow_partial_gear_stats)
                except (ValueError,RuntimeError,KeyError,AssertionError):continue
                # Reselect APL for the new gear, not a prebaked rotation.
                talent_i=next((i for i,t in enumerate(talents) if _key(t)==_key(candidate.allocation)),None)
                options=policies_by_talent[talent_i] if talent_i is not None else ()
                for label,policy in list(options)[:max_policy_candidates]:
                    if deadline-monotonic()<=.05:break
                    try:
                        if label!='incumbent':
                            validate_policy(policy,contender.ir.actions)
                            fresh=replace(contender,policy=policy,
                                opening=(() if label.startswith(('talent_unlock:', 'talent_condition:',
                                        'talent_modified:')) else contender.opening))
                        else:fresh=contender
                        if (required_combat_mode and not _policy_mode_damage_action_ids(
                                fresh.ir,fresh.policy,required_combat_mode)):
                            continue
                        trace={'allocation':dict(candidate.allocation),
                            'gear_move':'refined:'+str(turn+1)+':'+str(identity(gear)),
                            'policy':label,'recovery':parent['recovery'],
                            'policy_signature':policy_identity(fresh.policy)}
                        key=(_joint_row_identity(trace),tuple(sorted(int(v['item_id']) for v in gear['slots'].values())))
                        if key in seen:continue
                        seen.add(key)
                        result=_quick_joint_evaluation(fresh,level=level,mobs=screen_mobs,
                            backend=quick_backend,
                            timeout_s=min(per_candidate_wall_s,max(.01,deadline-monotonic())),
                            recovery_policy=recovery,pack_size=pack_size)
                    except (ValueError,RuntimeError,KeyError,AssertionError):continue
                    any_attempt=True;gear_probes+=1;policy_probes+=1;evaluated+=1
                    events+=int(result.get('events') or 0)
                    cpu+=float(result.get('elapsed_cpu_s') or 0.)
                    if (required_combat_mode and result['status']=='COMPLETE'
                            and not any(int(result.get('source_action_counts',{}).get(aid,0))>0
                                for aid in _policy_mode_damage_action_ids(
                                    fresh.ir,fresh.policy,required_combat_mode))):
                        result={**result,'status':'SPEC_COMBAT_MODE_ACTION_NOT_EXECUTED'}
                    trace.update(screen_status=result['status'],screen_s_per_mob=result.get('mean_s_per_mob'),
                        status='SCREEN_COMPLETE_NOT_PROMOTED' if result['status']=='COMPLETE' else 'SCREEN_BLOCKED',
                        worker_cpu_s=float(result.get('elapsed_cpu_s') or 0.),
                        screen_events=int(result.get('events') or 0),is_control=False,
                        source_action_counts=dict(result.get('source_action_counts') or {}),
                        policy_ir=fresh.policy.as_dict(),
                        equipped_gear=fresh.source_stage['gear_policy_result']['winner']['gear'],
                        opening_action_ids=list(fresh.opening),
                        refinement_round=turn+1,stat_weights_measured=dict(gradient))
                    rows.append(trace);attempted.append(trace)
                    if result['status']=='COMPLETE':screened.append((trace,fresh,recovery))
        if any_attempt:completed_rounds+=1
        top=_select_screen_finalists(screened,max_top_n)
    return screened,{'rounds_completed':completed_rounds,'stat_probes':stat_probes,
        'gear_probes':gear_probes,'policy_probes':policy_probes,
        'talent_probes':talent_probes,'paid_evaluations':evaluated,
        'events':events,'worker_cpu_s':cpu,'rows':rows}

def search_bounded_joint_frontier(*, class_key,level,source_ir,seed_stage,
                                  bonus_talent_points=0,max_talents=4,
                                  max_gear_moves=2,max_policies=2,
                                  max_recovery_policies=2,
                                  max_paid_builds=16,max_cpu_s=80., per_candidate_wall_s=8.,
                                  finalist_mobs=100,screen_mobs=4,
                                  allow_partial_gear_stats=True,
                                  screen_then_finalists=False,max_finalists=4,
                                  pack_size=1,qualification_mobs=None,
                                  max_qualifiers=12,progress_path=None,
                                  proposal_strategy="diagonal",resume_progress=False,
                                  screen_budget_fraction=None,
                                  search_only=False,refinement_top_n=3,
                                  refinement_rounds=0,refinement_stat_axes=(
                                      'spell_power','strength','agility','intellect'),
                                  refinement_probe_delta=20.,
                                  refinement_gear_candidates=3,
                                  refinement_policy_candidates=3,
                                  refinement_talent_neighbors=2,
                                  screen_evaluator_backend="isolated",
                                  spec_tree=None, min_spec_points=21,
                                  required_combat_mode=None):
    """Budgeted combination search using *one* real paid L2 evaluator.

    4-mob screens are pruning proxies only; only 100-mob completions rank.
    Gear membership and exact Forever encounters remain explicit blockers.
    """
    if (spec_tree is None and required_combat_mode is not None):
        raise ValueError('SOURCE_MODE_REQUIRES_SPEC_TREE')
    if screen_evaluator_backend not in ('isolated','direct'):
        raise ValueError('UNKNOWN_QUICK_SCREEN_BACKEND')
    if screen_evaluator_backend == 'direct' and (not search_only or screen_mobs>4):
        raise ValueError('QUICK_DIRECT_REQUIRES_SEARCH_ONLY_SHORT_HORIZON')
    if (type(refinement_top_n) is not int or refinement_top_n<1
        or type(refinement_rounds) is not int or not 0<=refinement_rounds<=10
        or type(refinement_gear_candidates) is not int or refinement_gear_candidates<1
        or type(refinement_policy_candidates) is not int or refinement_policy_candidates<1
        or type(refinement_talent_neighbors) is not int or not 0<=refinement_talent_neighbors<=16
        or not refinement_stat_axes or len(set(refinement_stat_axes))!=len(refinement_stat_axes)
        or not 0<float(refinement_probe_delta)<=1000):
        raise ValueError('INVALID_REFINEMENT_BUDGET')
    if search_only and resume_progress:
        raise ValueError('REFINEMENT_SEARCH_ONLY_RESUME_NOT_YET_SUPPORTED')
    screen_fraction=joint_screen_budget_fraction(qualification_mobs=qualification_mobs,
        override=screen_budget_fraction)
    if (max_paid_builds<1 or max_cpu_s<=0 or not 0<per_candidate_wall_s<=120
        or not 1<=screen_mobs<finalist_mobs<=100 or max_recovery_policies<1
        or not 1<=max_policies<=16 or not 1<=max_talents<=256 or max_gear_moves<0
        or (screen_then_finalists and not 1<=max_finalists<=max_paid_builds)
        or proposal_strategy not in ("diagonal","marginal_screen")
        or type(pack_size) is not int or not 1<=pack_size<=screen_mobs
        or (qualification_mobs is not None and (
            not screen_then_finalists or type(qualification_mobs) is not int
            or not screen_mobs < qualification_mobs < finalist_mobs
            or type(max_qualifiers) is not int or max_qualifiers < max_finalists))):
        raise ValueError('INVALID_JOINT_SEARCH_BUDGET')
    if resume_progress and (progress_path is None or not screen_then_finalists):
        raise ValueError('RESUME_REQUIRES_SCREEN_THEN_FINALISTS_AND_JOURNAL')
    # None is the current Forever Talented 5/5 scenario (ON by default).
    # Explicit 0 selects the historical OFF comparator. This is hashed into
    # the joint-search journal, so OFF and ON runs cannot resume each other.
    if bonus_talent_points is None:
        bonus_talent_points=talented_bonus_for_level(level,enabled=True)
    if type(bonus_talent_points) is not int or not 0<=bonus_talent_points<=5:
        raise ValueError('INVALID_TALENTED_BONUS_POINTS')
    journal=None
    if progress_path is not None:
        options=dict(bonus_talent_points=bonus_talent_points,max_talents=max_talents,
            max_gear_moves=max_gear_moves,max_policies=max_policies,
            max_recovery_policies=max_recovery_policies,max_paid_builds=max_paid_builds,
            max_cpu_s=max_cpu_s,per_candidate_wall_s=per_candidate_wall_s,
            finalist_mobs=finalist_mobs,screen_mobs=screen_mobs,
            allow_partial_gear_stats=allow_partial_gear_stats,
            screen_then_finalists=screen_then_finalists,
            max_finalists=max_finalists,pack_size=pack_size,
            qualification_mobs=qualification_mobs,max_qualifiers=max_qualifiers,
            proposal_strategy=proposal_strategy,screen_budget_fraction=screen_budget_fraction,
            search_only=search_only,refinement_top_n=refinement_top_n,
            refinement_rounds=refinement_rounds,
            refinement_stat_axes=tuple(refinement_stat_axes),
            refinement_probe_delta=refinement_probe_delta,
            refinement_gear_candidates=refinement_gear_candidates,
            refinement_policy_candidates=refinement_policy_candidates,
            refinement_talent_neighbors=refinement_talent_neighbors,
            screen_evaluator_backend=screen_evaluator_backend,
            talent_unlock_policy_version='source_ir_paid_witness_v2_modified_action',
            spec_tree=spec_tree,min_spec_points=min_spec_points,
            required_combat_mode=required_combat_mode)
        journal=PaidJointProgressJournal(progress_path,
            context_sha256=search_context_sha256(class_key=class_key,level=level,
                source_ir=source_ir,seed_stage=seed_stage,options=options),
            resume=resume_progress)
    recovered=journal.recovered if journal else None
    prior_wall=float(recovered['wall_s_at_snapshot']) if recovered else 0.
    if prior_wall<0 or prior_wall>max_cpu_s:
        raise ValueError('SOURCE_JOINT_PROGRESS_WALL_BUDGET_EXHAUSTED')
    # Allow the final audit, serialization and selection a small bounded
    # margin inside the user wall budget, rather than finishing milliseconds
    # beyond the 30s/300s hard deadline.
    requested_wall_budget_s=max_cpu_s
    max_cpu_s-=min(.25,max_cpu_s*.005)
    t0,c0=monotonic()-prior_wall,process_time()
    compiled,coverage=compile_talent_runtime(source_ir)
    if compiled.actor.metadata['class_key']!=class_key or compiled.actor.metadata['level']!=level:
        raise ValueError('JOINT_SOURCE_IR_CLASS_LEVEL_MISMATCH')
    enemy=checkpoint_enemy(ir=compiled,level=level)
    if required_combat_mode is not None and required_combat_mode not in {
            mode.id for mode in compiled.modes}:
        raise ValueError('UNKNOWN_SOURCE_COMBAT_MODE')
    talents,frontier=bounded_full_point_talent_frontier(compiled,level=level,
        bonus_talent_points=bonus_talent_points,max_frontier=max_talents)
    if spec_tree is not None:
        talents,spec_ledger=source_spec_talent_frontier(compiled,talents,
            tree_key=spec_tree,minimum_points=min_spec_points,
            level=level,bonus_talent_points=bonus_talent_points,
            max_frontier=max_talents)
        frontier={**frontier,**spec_ledger}
    source_allocation=seed_stage.get('allocation')
    if spec_tree is not None:
        definition_tree={t.id:t.tree_key for t in compiled.talents}
        if sum(v for tid,v in (source_allocation or {}).items()
               if definition_tree.get(tid)==spec_tree)<min_spec_points:
            source_allocation=None
    talents,reference_origin=_source_reference_talents(compiled,level=level,
        candidates=talents,source_allocation=source_allocation,
        bonus_talent_points=bonus_talent_points)
    base=seed_stage['gear_policy_result']['winner']['gear']
    # Reserve some search budget for coherent multi-slot statistical moves;
    # otherwise a short paid search samples only isolated gear substitutions.
    stat_package_quota,weapon_package_quota,slot_quota=(
        _joint_gear_move_quotas(max_gear_moves))
    slot_moves,_=_source_slot_proposals(class_key=class_key,level=level,base=base,
        per_slot=2,max_proposals=slot_quota)
    stat_packages,_=_source_stat_package_proposals(class_key=class_key,level=level,
        base=base,max_packages=stat_package_quota)
    packages,_=_source_weapon_package_proposals(class_key=class_key,level=level,
        base=base,max_packages=weapon_package_quota)
    gear_stages=[('incumbent',seed_stage)]
    for slot,item in slot_moves:
        try:
            variant=substituted_multi_stage(stage=seed_stage,class_key=class_key,
                level=level,swaps={slot:int(item.item_id)})
            gear_stages.append((f'{slot}:{item.item_id}',variant))
        except (ValueError,KeyError):continue
    for axis,swaps in stat_packages:
        try:
            variant=substituted_multi_stage(stage=seed_stage,class_key=class_key,
                level=level,swaps=swaps)
            gear_stages.append(('source_stat_package:'+axis,variant))
        except (ValueError,KeyError):continue
    for swaps in packages:
        try:
            variant=substituted_multi_stage(stage=seed_stage,class_key=class_key,
                level=level,swaps=swaps)
            gear_stages.append(('package:'+repr(sorted(swaps.items())),variant))
        except (ValueError,KeyError):continue
    policies=source_joint_policy_frontier(compiled,seed_stage,max_policies=max_policies,
        include_mode_cycles=True)
    policies_by_talent, expected_unlocks, unlock_preparation_blockers = (
        _source_talent_policy_variants(compiled, talents, seed_stage, policies,
            level=level, bonus_talent_points=bonus_talent_points))
    recoveries=_recovery_variants(compiled,seed_stage,max_recovery_policies)
    attempted=deepcopy(recovered['rows']) if recovered else []
    completed=[r for r in attempted if r.get('status')=='COMPLETE'
               and r.get('mobs')==100]
    paid=len(attempted)
    events=int(recovered['events']) if recovered else 0
    screened=[]
    full_evaluated=int(recovered['full_evaluated_candidates']) if recovered else 0
    recovered_phase=recovered['phase'] if recovered else None
    prior_phase_wall=(recovered.get('phase_wall_s') or {}) if recovered else {}
    screen_phase_wall_s=float(prior_phase_wall.get('screen',0.))
    qualification_phase_wall_s=float(prior_phase_wall.get('qualification',0.))
    def persist_partial(phase, *, finished=False, extra_qualification_events=0):
        if journal is not None:
            elapsed=monotonic()-t0
            if phase in ('PREPARED','SCREENING','IMMEDIATE_FULL'):
                phases={'screen':elapsed,'qualification':0.,'finalist':0.}
            elif phase=='SURVIVAL_QUALIFICATION':
                phases={'screen':screen_phase_wall_s,
                    'qualification':max(0.,elapsed-screen_phase_wall_s),'finalist':0.}
            else:
                phases={'screen':screen_phase_wall_s,
                    'qualification':qualification_phase_wall_s,
                    'finalist':max(0.,elapsed-screen_phase_wall_s-qualification_phase_wall_s)}
            journal.write(status=('FINISHED_NOT_CERTIFIED' if finished
                                  else 'IN_PROGRESS_NOT_CERTIFIED'),
                phase=phase,attempted=attempted,completed=completed,
                events=events+extra_qualification_events,
                full_evaluated_candidates=full_evaluated,
                elapsed_wall_s=elapsed,phase_wall_s=phases)
    if not recovered:
        persist_partial('PREPARED')
    # In two-stage mode, screen a broad legal frontier but reserve time for
    # actual 100-mob finalists. A screen is NEVER an accepted full score.
    screen_deadline=(t0 + max_cpu_s*screen_fraction) if (screen_then_finalists and not search_only) else (t0+max_cpu_s)
    search_screen_fraction=(float(screen_budget_fraction) if screen_budget_fraction is not None
                            else .60) if search_only and refinement_rounds else 1.
    if search_only:
        screen_then_finalists=True
        # Search-only can reclaim the unused Top-N refinement reserve after
        # the first pass. The fraction controls exploration vs exploitation.
        screen_deadline=t0+max_cpu_s*search_screen_fraction
    # Diagonal visitation gives EVERY axis a chance under tight budgets.
    # Lexical Cartesian loops previously exhausted budget on the first talent.
    dimensions=(len(talents),len(gear_stages),len(policies),len(recoveries))
    coordinates=_source_witness_first_coordinates(dimensions,policies_by_talent,
        proposal_strategy,attempted,gear_stages=gear_stages)
    recovered_rows=len(attempted)
    def evaluate_coordinate(index, coords, active_deadline):
        """Pay once for a source-legal frontier coordinate (initial or backfill).

        The canonical candidate preparation and CombatRuntime are identical in
        both phases. Recovered journal rows are reconstructed, never repaid.
        """
        nonlocal events,paid,full_evaluated
        talent_i,gear_i,policy_i,recovery_i=coords
        allocation=talents[talent_i]
        gear_label,gear_stage=gear_stages[gear_i]
        policy_label,policy=policies_by_talent[talent_i][policy_i]
        recovery_label,recovery=recoveries[recovery_i]
        if index<recovered_rows:
            # Replay only the deterministic preparation, never a paid
            # screen. The journal's input hash fixes all four axes.
            row=attempted[index]
            if (row['allocation']!=allocation or row['gear_move']!=gear_label
                    or row['policy']!=policy_label or row['recovery']!=recovery_label):
                raise ValueError('SOURCE_JOINT_PROGRESS_FRONTIER_IDENTITY_MISMATCH')
            if row.get('screen_status')=='COMPLETE':
                candidate=_prepare_joint_policy_candidate(
                    class_key=class_key,level=level,stage=gear_stage,
                    allocation=allocation,source_ir=compiled,
                    allow_partial_gear_stats=allow_partial_gear_stats,
                    policy_label=policy_label,policy=policy,
                    bonus_talent_points=bonus_talent_points)
                if policy_identity(candidate.policy)!=row['policy_signature']:
                    raise ValueError('SOURCE_JOINT_PROGRESS_POLICY_IDENTITY_MISMATCH')
                screened.append((row,candidate,recovery))
            return
        t=process_time()
        if required_combat_mode and not _policy_mode_damage_action_ids(
                compiled,policy,required_combat_mode):
            return
        row={'allocation':allocation,'gear_move':gear_label,'policy':policy_label,
            'recovery':recovery_label,'policy_origin':policy_label,
            'is_control':(_key(allocation)==_key(seed_stage.get('allocation',{}))
                          and gear_i==0 and policy_label=='incumbent'
                          and recovery_i==0),
            'policy_signature':policy_identity(policy),'policy_ir':policy.as_dict()}
        try:
            hard_guard = (_quick_candidate_wall_budget(max(.001,
                min(per_candidate_wall_s, active_deadline-monotonic(), t0+max_cpu_s-monotonic())))
                if search_only and screen_evaluator_backend == 'direct' else nullcontext())
            with hard_guard:
                candidate=_prepare_joint_policy_candidate(
                    class_key=class_key,level=level,stage=gear_stage,
                    allocation=allocation,source_ir=compiled,
                    allow_partial_gear_stats=allow_partial_gear_stats,
                    policy_label=policy_label,policy=policy,
                    bonus_talent_points=bonus_talent_points)
                row['policy_ir']=candidate.policy.as_dict()
                if (required_combat_mode and not _policy_mode_damage_action_ids(
                        candidate.ir,candidate.policy,required_combat_mode)):
                    raise ValueError('SPEC_COMBAT_MODE_OFFENSIVE_APL_MISSING')
                row['equipped_gear']=candidate.source_stage['gear_policy_result']['winner']['gear']
                row['opening_action_ids']=list(candidate.opening)
                row['policy_signature']=policy_identity(candidate.policy)
                row['policy_uncertainties']=source_policy_uncertainties(
                    candidate.policy,candidate.ir.actions)
                # Every screen uses the paid runtime. Immediate mode runs
                # each complete screen through 100 mobs; two-stage mode
                # reserves its full-horizon evaluations for finalists.
                remaining=max(.01,(active_deadline if screen_then_finalists
                                    else t0+max_cpu_s)-monotonic())
                screen=_quick_joint_evaluation(candidate,level=level,
                    backend=screen_evaluator_backend,
                    mobs=screen_mobs,timeout_s=min(per_candidate_wall_s,remaining),
                    recovery_policy=recovery,pack_size=pack_size)
                events+=int(screen.get('events') or 0)
                row['screen_status']=screen['status']
                row['screen_s_per_mob']=screen.get('mean_s_per_mob')
                row['source_action_counts']=dict(screen.get('source_action_counts') or {})
                if (required_combat_mode and row['screen_status']=='COMPLETE'
                        and not any(int(row['source_action_counts'].get(aid,0))>0
                            for aid in _policy_mode_damage_action_ids(
                                candidate.ir,candidate.policy,required_combat_mode))):
                    row['screen_status']='SPEC_COMBAT_MODE_ACTION_NOT_EXECUTED'
                row['worker_cpu_s']=float(screen.get('elapsed_cpu_s') or 0)
                if screen_then_finalists:
                    if row['screen_status']=='COMPLETE':
                        row['status']='SCREEN_COMPLETE_NOT_PROMOTED'
                        screened.append((row,candidate,recovery))
                    else:
                        row['status']='NOT_FULL_EVALUATED_SCREEN_FAILED_OR_BUDGET'
                elif row['screen_status']=='COMPLETE' and monotonic()-t0<max_cpu_s:
                    full=isolated_joint_evaluation(candidate,level=level,
                        mobs=finalist_mobs,
                        timeout_s=min(per_candidate_wall_s,max(.01,max_cpu_s-(monotonic()-t0))),
                        recovery_policy=recovery,pack_size=pack_size)
                    full_evaluated+=1
                    events+=int(full.get('events') or 0)
                    row['worker_cpu_s']+=float(full.get('elapsed_cpu_s') or 0)
                    row.update(status=full['status'],mobs=(finalist_mobs if full['status']=='COMPLETE'
                        else int(full.get('mob_completed') or 0)),
                        seconds_per_mob=full.get('mean_s_per_mob'),
                        full_events=full.get('events'))
                    if full['status']=='COMPLETE' and isfinite(float(full['mean_s_per_mob'])):
                        completed.append(row)
                else:
                    row['status']='NOT_FULL_EVALUATED_SCREEN_FAILED_OR_BUDGET'
        except _CandidateWallBudgetExpired as exc:
            row.update(status='BLOCKED_QUICK_CANDIDATE_WALL_BUDGET',
                screen_status='BLOCKED_QUICK_CANDIDATE_WALL_BUDGET',
                blocker=str(exc))
        except (ValueError,RuntimeError,KeyError,AssertionError) as exc:
            row.update(status='BLOCKED_PREPARATION_OR_EXECUTION',
                blocker=str(exc)[:500])
        row['parent_cpu_s']=process_time()-t
        attempted.append(row);paid+=1
        persist_partial('SCREENING' if screen_then_finalists else 'IMMEDIATE_FULL')
    coordinate_iter=enumerate(coordinates)
    pending=None
    for index,coords in coordinate_iter:
        if index>=recovered_rows and (paid>=max_paid_builds or monotonic()>=screen_deadline):
            pending=(index,coords)
            break
        evaluate_coordinate(index,coords,screen_deadline)
    if not recovered or recovered_phase in ('PREPARED','SCREENING'):
        screen_phase_wall_s=monotonic()-t0
    first_pass_paid_candidates=len(attempted)
    qualification_evaluated=sum('qualification_status' in r for r in attempted)
    qualification_complete=sum(r.get('qualification_status')=='COMPLETE' for r in attempted)
    qualification_events=sum(int(r.get('qualification_events') or 0) for r in attempted)
    refinement={'rounds_completed':0,'stat_probes':0,'gear_probes':0,
                'policy_probes':0,'talent_probes':0,
                'paid_evaluations':0,'events':0,'worker_cpu_s':0.,'rows':[]}
    if search_only and refinement_rounds:
        screened,refinement=_refine_screened_top_n(screened=screened,
            class_key=class_key,level=level,compiled=compiled,
            policies_by_talent=policies_by_talent,talents=talents,
            bonus_talent_points=bonus_talent_points,
            max_top_n=refinement_top_n,rounds=refinement_rounds,
            stat_axes=refinement_stat_axes,probe_delta=refinement_probe_delta,
            max_gear_candidates=refinement_gear_candidates,
            max_policy_candidates=refinement_policy_candidates,
            max_talent_neighbors=refinement_talent_neighbors,
            spec_tree=spec_tree,min_spec_points=min_spec_points,
            required_combat_mode=required_combat_mode,
            deadline=t0+max_cpu_s,
            per_candidate_wall_s=per_candidate_wall_s,screen_mobs=screen_mobs,
            pack_size=pack_size,allow_partial_gear_stats=allow_partial_gear_stats,
            attempted=attempted,quick_backend=screen_evaluator_backend)
        events+=refinement['events']
        paid+=refinement['paid_evaluations']
    refinement_phase_wall_s=max(0.,monotonic()-t0-screen_phase_wall_s)
    backfill_screen_candidates=0
    backfill_start=monotonic()
    if search_only and pending is not None:
        # Continue the SAME deterministic frontier after Top-N work. Never
        # restart the iterator or re-evaluate previously paid candidates.
        for index,coords in chain((pending,),coordinate_iter):
            if paid>=max_paid_builds or monotonic()>=t0+max_cpu_s:
                break
            evaluate_coordinate(index,coords,t0+max_cpu_s)
            backfill_screen_candidates+=1
    backfill_phase_wall_s=monotonic()-backfill_start if backfill_screen_candidates else 0.
    frontier_paid_candidates=first_pass_paid_candidates+backfill_screen_candidates
    if screen_then_finalists and not search_only:
        # A screen is a pruning proxy, never a full objective score. Optional
        # intermediate survival qualification is also a proxy, not acceptance.
        if qualification_mobs is not None:
            qualified,new_evaluated,new_completed,new_events = (
                _qualify_screened_candidates(screened,max_qualifiers=max_qualifiers,
                    level=level,mobs=qualification_mobs,
                    deadline=t0+max_cpu_s*.72,
                    per_candidate_wall_s=per_candidate_wall_s,pack_size=pack_size,
                    skip_evaluated=bool(recovered),
                    on_evaluated=lambda partial_events: persist_partial(
                        'SURVIVAL_QUALIFICATION',
                        extra_qualification_events=partial_events)))
            qualification_evaluated=new_evaluated
            qualification_complete=new_completed
            qualification_events+=new_events
            events+=new_events
            qualification_phase_wall_s=(float(prior_phase_wall['qualification'])
                if recovered_phase=='FULL_FINALISTS' else
                monotonic()-t0-screen_phase_wall_s)
            finalists=_select_screen_finalists(qualified,max_finalists,
                score_key='qualification_s_per_mob')
        else:
            finalists=_select_screen_finalists(screened,max_finalists)
        for row,candidate,recovery in finalists:
            if 'full_events' in row:
                continue
            if monotonic()-t0>=max_cpu_s:break
            full=isolated_joint_evaluation(candidate,level=level,mobs=finalist_mobs,
                timeout_s=min(per_candidate_wall_s,max(.01,max_cpu_s-(monotonic()-t0))),
                recovery_policy=recovery,pack_size=pack_size)
            full_evaluated+=1
            events+=int(full.get('events') or 0)
            row['worker_cpu_s']+=float(full.get('elapsed_cpu_s') or 0)
            row.update(status=full['status'],mobs=(finalist_mobs if full['status']=='COMPLETE'
                else int(full.get('mob_completed') or 0)),
                seconds_per_mob=full.get('mean_s_per_mob'),full_events=full.get('events'))
            if full['status']=='COMPLETE' and isfinite(float(full['mean_s_per_mob'])):
                completed.append(row)
            persist_partial('FULL_FINALISTS')
    # Return a ranked *search hypothesis*; an independent 100mob validator
    # must rank it against other screened candidates after the clock stops.
    ranked_screen=_select_screen_finalists(screened,refinement_top_n,
        diversify_apl=True) if search_only else []
    validation_shortlist=[dict(row) for row,_,_ in ranked_screen]
    search_winner=validation_shortlist[0] if validation_shortlist else None
    # Three phase times partition one shared wall budget without double counting.
    finalist_phase_wall_s=monotonic()-t0-screen_phase_wall_s-qualification_phase_wall_s
    completed.sort(key=lambda r:(float(r['seconds_per_mob']),_key(r['allocation']),
                                    r['gear_move'],r['policy'],r['recovery']))
    unlock_coverage,unlock_coverage_complete = _summarize_paid_unlock_coverage(
        attempted,expected_unlocks,unlock_preparation_blockers,frontier)
    persist_partial('COMPLETE_SEARCH',finished=True)
    status=('QUICK_SEARCH_ONLY_REQUIRES_EXTERNAL_100MOB_VALIDATION' if search_only and search_winner
            else 'NO_COMPLETE_QUICK_SCREEN_CANDIDATE' if search_only
            else 'BOUNDED_JOINT_PAID_DIAGNOSTIC' if completed
            else 'NO_COMPLETE_100MOB_JOINT_CANDIDATE')
    return {'status':status,
        'class_key':class_key,'level':level,'enemy':enemy.as_dict(),
        'pack_size':pack_size,
        'talented_enabled':bool(bonus_talent_points),
        'bonus_talent_points':bonus_talent_points,
        'talent_point_budget':available_talent_points(level,bonus_talent_points=bonus_talent_points),
        'spatial_mode':('simultaneous_2d_pack' if pack_size>1 else '2d_sequential_not_simultaneous_pack'),
        'talent_frontier':frontier,'reference_origin':reference_origin,
        'spec_constraint':{'tree_key':spec_tree,
            'minimum_points':min_spec_points if spec_tree else None,
            'required_combat_mode':required_combat_mode},
        'p4_talent_unlock_coverage':unlock_coverage,
        'p4_talent_unlock_coverage_pass':unlock_coverage_complete,
        'p4_talent_unlock_preparation_blockers':unlock_preparation_blockers,
        'proposal_strategy':proposal_strategy,
        'talent_ranks_missing_executor':coverage['rank_missing_executor'],
        'talent_allocations_proposed':len(talents),'gear_variants':len(gear_stages),
        'policy_variants':len(policies),'recovery_variants':len(recoveries),
        'paid_candidates':len(attempted),
        'initial_frontier_paid_candidates':frontier_paid_candidates,
        'first_pass_screen_candidates':first_pass_paid_candidates,
        'backfill_screen_candidates':backfill_screen_candidates,
        'backfill_phase_wall_s':backfill_phase_wall_s,
        'refinement_phase_wall_s':refinement_phase_wall_s,
        'screen_budget_fraction_effective':search_screen_fraction if search_only else screen_fraction,
        'stat_probe_evaluations':refinement['stat_probes'],
        'all_quick_evaluations_including_stat_probes':len(attempted)+refinement['stat_probes'],
        'search_only':bool(search_only),
        'screen_evaluator_backend':screen_evaluator_backend,
        'search_winner':search_winner,
        'validation_shortlist':validation_shortlist,
        'refinement':refinement,
        'refinement_top_n':refinement_top_n,
        'refinement_rounds':refinement_rounds,
        'full_100mob_within_search_budget':not search_only,
        'validation_required_outside_search_budget':bool(search_only),
        'screen_complete_candidates':sum(r.get('screen_status')=='COMPLETE' for r in attempted),
        'full_evaluated_candidates':full_evaluated,
        # Gate P4/P5: prove each of the three optimization dimensions was
        # actually paid in the current run. Proposed but never evaluated
        # alternatives do not count as joint search coverage.
        'joint_axis_paid_coverage':{
            'distinct_talent_allocations':len({_key(row['allocation']) for row in attempted
                if row.get('screen_status')}),
            'distinct_gear_configs':len({json.dumps(row['equipped_gear'],sort_keys=True,default=str)
                for row in attempted if row.get('screen_status') and 'equipped_gear' in row}),
            'distinct_policy_signatures':len({row['policy_signature'] for row in attempted
                if row.get('screen_status') and row.get('policy_signature')}),
            'distinct_recovery_policies':len({row['recovery'] for row in attempted
                if row.get('screen_status') and 'recovery' in row}),
            'paid_screens':sum(bool(row.get('screen_status')) for row in attempted),
        },
        'unique_full_builds':len({_joint_row_identity(r) for r in attempted}),
        'search_strategy':('quick_screen_top_n_refinement' if search_only else
            'screen_qualify_full' if qualification_mobs is not None
            else 'screen_then_full' if screen_then_finalists else 'immediate_full'),
        'screen_phase_wall_s':screen_phase_wall_s,
        'qualification_mobs':qualification_mobs,
        'qualification_evaluated_candidates':qualification_evaluated,
        'qualification_complete_candidates':qualification_complete,
        'qualification_events':qualification_events,
        'qualification_phase_wall_s':qualification_phase_wall_s,
        'finalist_phase_wall_s':finalist_phase_wall_s,
        'complete_100mob_candidates':len(completed),'winner':completed[0] if completed else None,
        'baseline_results':[r for r in attempted if r['is_control']],
        'rows':attempted,'events':events,'parent_cpu_s':process_time()-c0,
        'worker_cpu_s_reported':sum(float(r.get('worker_cpu_s',0)) for r in attempted)
                                + max(0.,refinement['worker_cpu_s'] - sum(float(r.get('worker_cpu_s',0))
                                         for r in refinement['rows'])),
        'wall_s':monotonic()-t0,
        'requested_wall_budget_s':requested_wall_budget_s,
        'internal_wall_budget_s':max_cpu_s,
        'budget_type':'shared_wall_with_os_isolated_candidates',
        'search_budget_exhausted':first_pass_paid_candidates>=max_paid_builds or monotonic()-t0>=max_cpu_s,
        'source_legal_gear_universe_verified':False,
        'named_forever_enemy_verified':enemy.exact_forever_enemy_verified,
        'global_optimum_proven':False,'eligible_for_checkpoint_acceptance':False,
        'limitations':['only bounded source-legal full-point talent beam',
            'gear catalogue class membership not byte-attested',
            'limited source action policies and source gear moves',
            'recovery policy threshold sample only; not exhaustive',
            'Classic proxy encounter, not verified Forever NPC']}

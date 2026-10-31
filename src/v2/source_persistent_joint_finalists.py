"""Two-mob paid screen -> hundred-mob paid finalist selection for source joint search.

This is an extension of the canonical source joint controller, not a second
combat/scoring engine. CombatRuntime + recovery are used unchanged and actor
state is carried between kills. This module never reads old builds or fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from collections import defaultdict, Counter
from time import monotonic, process_time, monotonic_ns, process_time_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility
from src.game.policy import execute_priority_policy, opening_for_persistent_actor
from src.game.recovery import recover_actor_to_full
from src.game.recovery_between_pulls import BetweenPullPolicy, between_pull_recovery
from src.game.data.forever.target_combat_source import target_combat_metadata
from src.shared.leveling.objective import representative_hp
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.game.talent_frontier import allocation_key, source_legal_talent_neighbors
from src.game.runtime.source_maintenance import _execute_source_maintenance_upkeep
from src.game.runtime.simulator import EventTransitionBudgetExceeded, ComputeDeadlineExceeded
from src.shared.leveling.spaced_pulls import SpacedPullLayout


@dataclass(frozen=True)
class PreparedCandidate:
    ir: object
    policy: object
    opening: tuple[str, ...]
    source_stage: dict
    allocation: dict


def _partial_gear_coverage(applied, gear, unresolved):
    """Explicitly mark an executable-but-incomplete diagnostic candidate."""
    return {
        'complete': False,
        'mode': 'EXPLICIT_PARTIAL_DIAGNOSTIC_NOT_CHECKPOINT_L2',
        'unsupported_stats': dict(applied.unsupported_stats),
        'unresolved_item_effects': dict(unresolved),
        'item_ids': [int(v['item_id']) for v in gear['slots'].values()],
        'cannot_certify_checkpoint': True,
    }


def prepare_candidate(*, class_key: str, level: int, stage: dict, allocation_override=None,
                      source_ir=None,strict_l2_item_effects:bool=False,
                      provisional_rating_model:bool=False,
                      allow_partial_gear_stats:bool=False,
                      bonus_talent_points:int=0) -> PreparedCandidate:
    """Rebuild source gear and policy; partial diagnostics never certify L2."""
    if allow_partial_gear_stats and strict_l2_item_effects:
        raise ValueError('PARTIAL_GEAR_DIAGNOSTIC_CANNOT_BE_STRICT')
    root=source_ir if source_ir is not None else build_game_ir_slice(class_key=class_key,level=level)
    allocation=dict(stage['allocation'] if allocation_override is None else allocation_override)
    ir,_=apply_talent_selection(root,allocation,level=level,
        bonus_talent_points=bonus_talent_points)
    result=stage['gear_policy_result']['winner']
    gear=result['gear']
    if not gear or not gear.get('slots') or any(
        entry.get('required_level_origin')!='observed' or int(entry['required_level'])>level
        for entry in gear['slots'].values()
    ):
        raise ValueError('BLOCKED_NAMED_GEAR_SOURCE_LEVEL')
    from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
    audit=audit_named_gear_source(class_key=class_key,level=level,gear=gear)
    if not audit['equipment_legality_complete']:
        raise ValueError('BLOCKED_NAMED_GEAR_CATALOGUE_LEGALITY_OR_STATS')
    # The item L0 universe includes legal but untyped effects. An L2 build
    # may execute them only as an explicitly uncertain diagnostic.
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0
    from src.rulesets.forever.items.runtime_selection import available_items
    by_id={int(x.item_id):x for x in available_items(
        class_key,level,required_level_policy='observed')}
    unresolved={}
    for slot,item in gear['slots'].items():
        effects=source_item_l0(by_id[int(item['item_id'])])['unresolved_effects']
        if effects:
            unresolved[slot]=effects
    if unresolved and not allow_partial_gear_stats:
        raise ValueError('BLOCKED_UNTYPED_ITEM_EFFECTS:'+str(unresolved))
    ir,applied=apply_gear_selection(ir,aggregate_stats=gear['aggregate_stats'],
        selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
    if applied.unsupported_stats and not allow_partial_gear_stats:
        raise ValueError('BLOCKED_UNSUPPORTED_GEAR_STATS')
    if applied.unsupported_stats or unresolved:
        ir=replace(ir,provenance={**dict(ir.provenance),
            'gear_effect_coverage': _partial_gear_coverage(applied, gear, unresolved)})
    # Both are generic source adapters: raw item display stats feed the
    # CombatRuntime probabilities; typed passives alter actual actor stats.
    from src.game.data.forever.source_checkpoint_p3_ratings import apply_source_equipped_item_stats
    ir=apply_source_equipped_item_stats(ir,class_key=class_key,level=level,
        item_ids=(int(v['item_id']) for v in gear['slots'].values()))
    from src.rulesets.forever.items.source_equipment_semantics import apply_equipped_source_effects
    ir=apply_equipped_source_effects(ir,class_key=class_key,level=level,
        item_ids=(int(v['item_id']) for v in gear['slots'].values()))
    from src.rulesets.forever.items.source_numeric_extras import apply_source_numeric_extras
    ir=apply_source_numeric_extras(ir,class_key=class_key,level=level,
        item_ids=(int(v['item_id']) for v in gear['slots'].values()))
    if provisional_rating_model and strict_l2_item_effects:
        raise ValueError('PROVISIONAL_FLAG_NOT_ALLOWED_WITH_STRICT_L2')
    record=result['winner']
    policy=_make_policy(ir,record['fallback'],guarded_action=record.get('guarded_action'),
        guarded_conditions=tuple(_condition_from_record(x) for x in record.get('guarded_conditions',())))
    opening=tuple(record['prefix'])
    return PreparedCandidate(ir,policy,opening,stage,allocation)



def _evaluate_concurrent_source_packs(candidate, *, level, mobs, pack_size,
                                      max_total_events, max_cpu_s, max_wall_s,
                                      recovery_policy):
    """Adapter to the existing multi-target CombatRuntime + recovery scorer."""
    # This is the EXISTING source GameIR/Policy/CombatRuntime pack scorer,
    # not a separate damage or recovery model. It preserves one actor
    # across all packs and schedules real 20-yard aggro and incoming hits.
    from src.game.multi_pull import evaluate_repeated_pulls
    wall_start, cpu_start = monotonic(), process_time()
    try:
        result = evaluate_repeated_pulls(
            ir_slice=candidate.ir, policy=candidate.policy, level=level,
            target_health=float(representative_hp(level)), count=mobs,
            pack_size=pack_size, opening_action_ids=candidate.opening,
            schedule_incoming_attacks=True,
            apply_target_defense=bool(candidate.ir.provenance.get('target_combat_profile')),
            recovery_mode='threshold' if recovery_policy else 'always',
            recovery_health_fraction=(recovery_policy.health_fraction if recovery_policy else .5),
            recovery_mana_fraction=(recovery_policy.mana_fraction if recovery_policy else .1),
            source_maintenance_upkeep=True,
            source_between_pack_policy=recovery_policy)
    except ValueError as exc:
        reason = str(exc)
        if reason.startswith('pull ') and 'failed: actor_died' in reason:
            return {'status':'BLOCKED_ACTOR_DIED','mob_completed':0,
                    'reason':reason,'events':0}
        if reason.startswith('BLOCKED_SOURCE_MAINTENANCE_UPKEEP:'):
            return {'status':'BLOCKED_SOURCE_MAINTENANCE_UPKEEP',
                    'mob_completed':0,'reason':reason}
        if reason.startswith('BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY:'):
            return {'status':'BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY',
                    'mob_completed':0,'reason':reason}
        raise
    wall_elapsed, cpu_elapsed = monotonic()-wall_start, process_time()-cpu_start
    event_count=sum(int(p['event_transitions']) for p in result.pulls)
    maintenance_s=sum(float(p['maintenance_s']) for p in result.pulls)
    maintenance_casts=sum(int(p['maintenance_casts']) for p in result.pulls)
    maintenance_events=sum(int(p['maintenance_runtime_events']) for p in result.pulls)
    between_events=sum(int(p['between_pull_runtime_events']) for p in result.pulls)
    from collections import Counter
    recovery_action_counts=dict(Counter(
        action for p in result.pulls for action in p['source_recovery_actions']))
    if ((max_total_events is not None and event_count > max_total_events)
            or (max_cpu_s is not None and cpu_elapsed > max_cpu_s)
            or (max_wall_s is not None and wall_elapsed > max_wall_s)):
        return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET',
                'mob_completed':0,'events':event_count,
                'elapsed_wall_s':wall_elapsed,'elapsed_cpu_s':cpu_elapsed}
    killed=sum(int(p['mob_count']) for p in result.pulls if p['pack_all_defeated'])
    if killed != mobs or len(result.pulls) != (mobs+pack_size-1)//pack_size:
        return {'status':'BLOCKED_INCOMPLETE_2D_PACK',
                'mob_completed':killed,'events':event_count}
    return {'status':'COMPLETE','count':mobs,'mob_completed':killed,
        'packs':len(result.pulls),'pack_size':pack_size,
        'spatial_mode':'simultaneous_2d_pack',
        'incoming_attacks_scheduled':True,
        'continuous_actor_state':True,
        'total_s':result.end_time_s-result.start_time_s,
        'mean_s_per_mob':result.seconds_per_mob,
        'combat_s':sum(float(p['kill_s']) for p in result.pulls),
        'recovery_s':sum(float(p['recovery_s']) for p in result.pulls),
        'maintenance_s':maintenance_s,
        'maintenance_casts':maintenance_casts,
        'maintenance_runtime_events':maintenance_events,
        'between_pull_runtime_events':between_events,
        'source_recovery_action_counts':recovery_action_counts,
        'events':event_count,'elapsed_wall_s':wall_elapsed,
        'elapsed_cpu_s':cpu_elapsed}

def evaluate_persistent_candidate(candidate: PreparedCandidate, *, level: int, mobs: int, max_wall_s: float | None = None,
                                  max_total_events: int | None = None, max_cpu_s: float | None = None,
                                  recovery_policy: BetweenPullPolicy | None = None,
                                  mob_spacing_yards: float = 0.0,
                                  movement_speed_yards_s: float = 7.0,
                                  pack_size: int = 1,
                                  settle_final_recovery: bool = True,
                                  trace_pulls: bool = False) -> dict:
    """Exactly `mobs` kills on one ActorState.

    Default full-final-recovery semantics preserve the 100mob benchmark.
    Quest horizon explicitly ends at the last kill without paying recovery
    that the requested quest does not require.  Optional traces expose
    executed recovery/cooldowns; no proxy estimator changes runtime scoring.
    """
    if mobs<1:
        raise ValueError('mobs must be positive')
    if max_wall_s is not None and (not isfinite(float(max_wall_s)) or max_wall_s <= 0):
        raise ValueError('max_wall_s must be finite and positive')
    if max_total_events is not None and (type(max_total_events) is not int or max_total_events < 1):
        raise ValueError('max_total_events must be positive')
    if max_cpu_s is not None and (not isfinite(float(max_cpu_s)) or max_cpu_s <= 0):
        raise ValueError('max_cpu_s must be finite and positive')
    if type(pack_size) is not int or not 1 <= pack_size <= mobs:
        raise ValueError('INVALID_SOURCE_2D_PACK_SIZE')
    if pack_size > 1 and (not settle_final_recovery or trace_pulls):
        raise ValueError('QUEST_HORIZON_SEQUENTIAL_ONLY_NOT_SILENTLY_2D_APPROXIMATED')
    if pack_size > 1:
        return _evaluate_concurrent_source_packs(candidate,level=level,mobs=mobs,
            pack_size=pack_size,max_total_events=max_total_events,
            max_cpu_s=max_cpu_s,max_wall_s=max_wall_s,
            recovery_policy=recovery_policy)
    layout=SpacedPullLayout(mob_count=mobs,spacing_yards=mob_spacing_yards,
                            movement_speed_yards_s=movement_speed_yards_s)
    ir=candidate.ir
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    metadata=target_combat_metadata(ir) if ir.provenance.get('target_combat_profile') else {}
    events=0; kills=[]; recoveries=[]; maintenance_elapsed=0.; maintenance_casts=0;maintenance_events=0;skip_count=0;between_pull_events=0;hot_casts=0;full_recovery_count=0;carried_hot_ticks_at_pull=0;carried_hot_heals_in_combat=0
    executed_source_actions=Counter()
    control_proc_attempts=0;control_proc_triggered=0
    pull_trace=[]
    long_actions={a.id:float(a.cooldown_s) for a in ir.actions if float(a.cooldown_s)>=60.0}
    travel_elapsed=0.0;travel_events=0
    clock_begin=float(actor.current_time_s)
    start=monotonic(); cpu_begin=process_time()
    cpu_deadline=(None if max_cpu_s is None else process_time_ns()+int(max_cpu_s*1e9))
    wall_deadline=(None if max_wall_s is None else monotonic_ns()+int(max_wall_s*1e9))
    for index in range(mobs):
        if (max_total_events is not None and events>=max_total_events) or (max_cpu_s is not None and process_time()-cpu_begin>=max_cpu_s):
            return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET','mob_completed':index,'events':events,'elapsed_cpu_s':process_time()-cpu_begin,'elapsed_wall_s':monotonic()-start}

        # The position of the next mob matters. This is explicit sequential
        # movement on the same actor clock, not a fabricated grouped AoE pull.
        if index and layout.spacing_yards:
            try:
                travel=CombatRuntime(actor=actor,target=TargetState.with_health('spaced_travel',1.0))
                travel.advance_to(float(actor.current_time_s)+layout.segment_distances_yards[index-1] / layout.movement_speed_yards_s)
                travel.persist_actor_periodics()
                travel_elapsed+=layout.segment_distances_yards[index-1] / layout.movement_speed_yards_s
                travel_events+=travel.event_transitions;events+=travel.event_transitions
            except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
                return {'status':'BLOCKED_SPACED_TRAVEL_BUDGET','mob_completed':index,
                        'reason':type(exc).__name__,'events':events}
        try:
            upkeep_s,upkeep_casts,upkeep_events=_execute_source_maintenance_upkeep(
                ir,actor,max_new_event_transitions=None if max_total_events is None else max_total_events-events,
                cpu_deadline_ns=cpu_deadline,wall_deadline_ns=wall_deadline)
        except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
            return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET','mob_completed':index,
                'reason':type(exc).__name__,'events':events+exc.events_processed,
                'elapsed_cpu_s':process_time()-cpu_begin,'elapsed_wall_s':monotonic()-start}
        except ValueError as exc:
            return {'status':'BLOCKED_SOURCE_MAINTENANCE_UPKEEP','mob':index+1,
                    'reason':str(exc),'events':events,'elapsed_wall_s':monotonic()-start}
        maintenance_elapsed+=upkeep_s;maintenance_casts+=upkeep_casts
        maintenance_events+=upkeep_events;events+=upkeep_events
        at_start=float(actor.current_time_s)
        resources_before={key:actor.resource_amount(key) for key in ('health','mana','energy')}
        ready_long_cooldowns={aid:float(actor.cooldown_ready_s.get(aid,0.0))<=at_start+1e-7
                              for aid in long_actions}
        target=TargetState.with_health('canonical_leveling_target_L%d_mob%d'%(level, layout.path_indices[index]),float(representative_hp(level)),
            **metadata,source_status='source_backed_canonical_leveling_reference',
            authority='src.shared.leveling.objective.MOB_BASE_HP',
            source_basis='CMaNGOS warrior-class BaseHealthExp0 ordinary melee target curve',level=level)
        carried_hot_ticks_at_pull+=sum(e.kind=='PeriodicTick' for e in actor.pending_actor_periodic_events)
        runtime=CombatRuntime(actor=actor,target=target,
            spell_power=float(actor.stats.get('spell_power',0.0)),auto_attacks=ir.auto_attacks,
            companions=tuple(ActorState.from_ir(d,()) for d in ir.companions),
            timed_summons=ir.timed_summons,incoming_attacks=ir.incoming_attacks,
            mitigation_rules=ir.mitigation_rules,triggers=ir.triggers)
        runtime.event_budget_cap=None if max_total_events is None else max_total_events-events
        runtime.event_budget_start=0
        runtime.cpu_deadline_ns=cpu_deadline
        runtime.wall_deadline_ns=wall_deadline
        opening,skipped=opening_for_persistent_actor(
            opening_action_ids=candidate.opening,actions=ir.actions,actor=actor)
        try:
            result=execute_priority_policy(policy=candidate.policy,actions=ir.actions,
                runtime=runtime,opening_action_ids=opening,max_actions=256)
        except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
            return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET','mob_completed':index,
                'reason':type(exc).__name__,'events':events+exc.events_processed,
                'elapsed_cpu_s':process_time()-cpu_begin,'elapsed_wall_s':monotonic()-start}
        executed_source_actions.update(str(row['action_id']) for row in result.selected_actions)
        proc_events=[e for e in result.timeline.events if e.kind=='ControlApplied'
                     and 'proc_triggered' in e.payload]
        control_proc_attempts+=len(proc_events)
        control_proc_triggered+=sum(bool(e.payload['proc_triggered']) for e in proc_events)
        if result.stopped_reason or not result.timeline.target_defeated or not actor.resource_positive('health') or not result.selected_actions:
            return {'status':'BLOCKED_COMBAT','mob':index+1,
                'reason':result.stopped_reason or 'death_or_empty_policy',
                'source_action_counts':dict(sorted(executed_source_actions.items())),
                'events':events+runtime.event_transitions,
                'elapsed_wall_s':monotonic()-start}
        selected_action_ids={row['action_id'] for row in result.selected_actions}
        carried_hot_heals_in_combat+=sum(e.kind=='Heal' and e.payload.get('periodic')
            and e.action_id not in selected_action_ids for e in result.timeline.events)
        kill=float(result.timeline.target_death_s)-at_start
        resources_at_kill={key:actor.resource_amount(key) for key in ('health','mana','energy')}
        used_long_cooldowns={aid:sum(a['action_id']==aid for a in result.selected_actions)
                             for aid in long_actions}
        used_long_cooldowns={k:v for k,v in used_long_cooldowns.items() if v}
        final_unsettled=bool(index==mobs-1 and not settle_final_recovery)
        try:
            if final_unsettled:
                recovery_s=0.0
                must_be_full=False
                recovery=None
                step={'events':0,'full_recovery':False,'hot_cast':False,
                      'water_s':0.0,'food_s':0.0,'recovery_method':None}
            elif recovery_policy is None:
                recovery=recover_actor_to_full(actor=actor,level=level,actions=ir.actions,
                    start_time_s=float(result.timeline.target_death_s),
                    healing_power=float(actor.stats.get('spell_power',0.0)),
                    cpu_deadline_ns=cpu_deadline,wall_deadline_ns=wall_deadline)
                recovery_s=float(recovery.total_s)
                must_be_full=True
            else:
                step=between_pull_recovery(ir=ir,actor=actor,level=level,
                    mob_index=index,mob_count=mobs,policy=recovery_policy,
                    cpu_deadline_ns=cpu_deadline,wall_deadline_ns=wall_deadline,
                    max_new_events=None if max_total_events is None else max_total_events-events-runtime.event_transitions)
                recovery_s=float(step['elapsed_s'])
                between_pull_events+=int(step['events'])
                hot_casts+=int(step['hot_cast'])
                full_recovery_count+=int(step['full_recovery'])
                must_be_full=index==mobs-1
        except (EventTransitionBudgetExceeded,ComputeDeadlineExceeded) as exc:
            return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET','mob_completed':index,
                'reason':type(exc).__name__, 'events':events+runtime.event_transitions+getattr(exc,'events_processed',0),
                'elapsed_cpu_s':process_time()-cpu_begin,'elapsed_wall_s':monotonic()-start}
        except ValueError as exc:
            return {'status':'BLOCKED_SOURCE_BETWEEN_PULL_RECOVERY','mob':index+1,
                'reason':str(exc),'events':events+runtime.event_transitions,
                'elapsed_wall_s':monotonic()-start}
        kills.append(kill);recoveries.append(recovery_s)
        if trace_pulls:
            pull_trace.append({
                'mob':index+1,'target_id':target.id,
                'pull_started_s':at_start,'kill_finished_s':float(result.timeline.target_death_s),
                'recovery_finished_s':float(actor.current_time_s),
                'combat_s':kill,'recovery_s':recovery_s,
                'health_mana_energy_before':resources_before,
                'health_mana_energy_at_kill':resources_at_kill,
                'health_mana_energy_after_recovery':{key:actor.resource_amount(key)
                    for key in ('health','mana','energy')},
                'full_recovery':False if final_unsettled else
                    (True if recovery_policy is None else bool(step['full_recovery'])),
                'water_s':0.0 if final_unsettled else (float(recovery.water_s)
                    if recovery_policy is None else float(step.get('water_s',0.0))),
                'food_s':0.0 if final_unsettled else (float(recovery.food_s)
                    if recovery_policy is None else float(step.get('food_s',0.0))),
                'recovery_method':None if final_unsettled else (recovery.method
                    if recovery_policy is None else step.get('recovery_method')),
                'long_cooldown_timer_ready_at_pull':ready_long_cooldowns,
                'long_cooldowns_used':used_long_cooldowns,
                'long_cooldowns_not_ready_at_kill':{
                    aid:float(ready-float(result.timeline.target_death_s)) for aid,ready in actor.cooldown_ready_s.items()
                    if aid in long_actions and float(ready)>float(result.timeline.target_death_s)+1e-7},
                'actions':dict(Counter(a['action_id'] for a in result.selected_actions)),
            })
        if not actor.resource_positive('health') or (must_be_full and
            abs(float(actor.resources['health'])-float(actor.resource_capacity['health']))>1e-7):
            return {'status':'BLOCKED_INCOMPLETE_RECOVERY','mob':index+1}
        events+=runtime.event_transitions+(0 if final_unsettled else (int(step['events']) if recovery_policy is not None else int(recovery.periodic_recovery_events)));skip_count+=len(skipped)
        if (max_total_events is not None and events>max_total_events) or (max_cpu_s is not None and process_time()-cpu_begin>max_cpu_s):
            return {'status':'BLOCKED_EVALUATION_COMPUTE_BUDGET',
                'mob_completed':index+1,'events':events,'elapsed_cpu_s':process_time()-cpu_begin,
                'elapsed_wall_s':monotonic()-start}
        # This is a compute-time PRUNING BUDGET, never a claim that the
        # omitted build was worse. Any unfinished candidate is explicitly
        # blocked and cannot win the 100-mob objective.
        if max_wall_s is not None and monotonic()-start > max_wall_s:
            return {'status':'BLOCKED_EVALUATION_TIME_BUDGET',
                'mob_completed':index+1,'mobs_requested':mobs,
                'partial_runtime_s':float(actor.current_time_s)-clock_begin,
                'events':events,'elapsed_wall_s':monotonic()-start}
    total=float(actor.current_time_s)-clock_begin
    # Audit redundant independently reported event and recovery accounting.
    # The objective is always the SAME actual CombatRuntime actor clock.
    if not isfinite(total) or total<=0 or abs(total-(sum(kills)+sum(recoveries)+maintenance_elapsed+travel_elapsed))>1e-7:
        raise ValueError('INVALID_PERSISTENT_CLOCK_ACCOUNTING')
    # The trace is generated by this actual retained gsim ActorState, never
    # reconstructed from aggregate DPS. Native action/ACK remains unverified.
    trace_audit=None
    if trace_pulls:
        from src.v2.persistent_pull_trace_audit import audit_persistent_pull_trace
        trace_audit=audit_persistent_pull_trace(pull_trace,expected_mobs=mobs)
    return {'status':'COMPLETE','count':mobs,'total_s':total,
        'mean_s_per_mob':total/mobs,'combat_s':sum(kills),'recovery_s':sum(recoveries),
        'maintenance_s':maintenance_elapsed,'maintenance_casts':maintenance_casts,
        'spaced_travel_s':travel_elapsed,'spaced_travel_events':travel_events,
        'mob_spacing_yards':layout.spacing_yards,'mob_positions_yards':layout.positions_yards,
        'pull_route_indices':layout.path_indices,
        'spatial_mode':'2d_sequential_not_simultaneous_pack',
        'maintenance_runtime_events':maintenance_events,
        'between_pull_runtime_events':between_pull_events,
        'between_pull_hot_casts':hot_casts,'between_pull_full_recoveries':full_recovery_count,
        'carried_hot_ticks_at_pull':carried_hot_ticks_at_pull,
        'carried_hot_heals_in_combat':carried_hot_heals_in_combat,
        'recovery_policy':None if recovery_policy is None else vars(recovery_policy),
        'events':events,'skipped_satisfied_mode_prefixes':skip_count,
        'source_action_counts':dict(sorted(executed_source_actions.items())),
        'source_control_proc_attempts':control_proc_attempts,
        'source_control_proc_triggered':control_proc_triggered,
        'settle_final_recovery':bool(settle_final_recovery),
        **({'long_cooldown_source_actions_s':long_actions} if trace_pulls else {}),
        'final_resources':{key:actor.resource_amount(key) for key in ('health','mana','energy')},
        **({'pull_trace':pull_trace,'pull_trace_audit':trace_audit} if trace_pulls else {}),
        'continuous_actor_state':True,'source_only':True,
        'elapsed_wall_s':monotonic()-start,'elapsed_cpu_s':process_time()-cpu_begin}



def _paid_source_candidate_stages(joint_result: dict) -> list[dict]:
    """Expose every *actually scored* L2 fixed-policy talent proposal to L2->L3.

    The joint controller previously returned only per-talent gear-search winners
    and an occasional post-refinement winner. Its other paid fixed-policy
    evaluations were invisible to the persistent objective, even if their
    100-mob result would beat every stage winner. Never invent an L2 score,
    item, allocation, or policy here; rebuild only from the controller's
    existing, source-derived paid evidence. These are candidate records, not
    a claim that gear/policy were freshly reoptimized for the new allocation.
    """
    stages=list(joint_result.get('stages',()))
    for record in joint_result.get('fixed_policy_challengers',()):
        if not isfinite(float(record['score_s_per_mob'])):
            continue
        stages.append({'allocation':dict(record['allocation']),
            'score_s_per_mob':float(record['score_s_per_mob']),
            'operation':'paid_parent_fixed_policy',
            'paid_candidate_origin':'paid_parent_fixed_policy',
            'source_policy_and_gear_reused':True,
            'gear_policy_result':{'winner':{
                'gear':record['parent_named_gear'],
                'winner':record['parent_policy']}}})
    refinement=joint_result.get('post_talent_refinement')
    if refinement:
        gear=refinement['fixed_named_gear']
        policy=refinement['fixed_policy_record']
        for record in refinement['observations']:
            if record['status']!='FULL_L2_FIXED_POLICY' or record['score_s_per_mob'] is None:
                continue
            score=float(record['score_s_per_mob'])
            if not isfinite(score) or score<=0:
                continue
            stages.append({'allocation':dict(record['allocation']),
                'score_s_per_mob':score,
                'operation':'paid_refinement_fixed_policy',
                'paid_candidate_origin':'paid_refinement_fixed_policy',
                'source_policy_and_gear_reused':True,
                'gear_policy_result':{'winner':{
                    'gear':gear,'winner':policy}}})
        fresh=refinement.get('fresh_policy_winner')
        if fresh and fresh.get('score_s_per_mob') is not None:
            stages.append({'allocation':dict(refinement['best_fixed_allocation']),
                'score_s_per_mob':float(fresh['score_s_per_mob']),
                'operation':'paid_refinement_fresh_policy',
                'paid_candidate_origin':'paid_refinement_fresh_policy',
                'source_policy_and_gear_reused':True,
                'gear_policy_result':{'winner':{
                    'gear':gear,'winner':fresh}}})
    return stages


def _gear_policy_identity(stage: dict) -> tuple:
    selected=stage['gear_policy_result']['winner']
    policy=selected['winner']
    return (tuple(sorted((slot,int(item['item_id']))
                    for slot,item in selected['gear']['slots'].items())),
            tuple(policy['prefix']),str(policy['fallback']),
            str(policy.get('guarded_action')),
            str(policy.get('guarded_conditions')))


def _diverse_paid_candidate_order(stages: list[dict]) -> list[dict]:
    """Round-robin source gear/policy families, sorted by paid L2 score.

    A single talent neighborhood must not monopolize the bounded 2-mob
    screen; this also preserves the best measured member of each family.
    """
    groups=defaultdict(list)
    for stage in stages:
        groups[_gear_policy_identity(stage)].append(stage)
    for family in groups.values():
        family.sort(key=lambda s:(float(s['score_s_per_mob']),
                                  allocation_key(s['allocation'])))
    families=sorted(groups,key=lambda key:(float(groups[key][0]['score_s_per_mob']),key))
    ordered=[]
    while any(groups.values()):
        for key in families:
            if groups[key]:
                ordered.append(groups[key].pop(0))
    return ordered


def select_persistent_finalists(*, class_key: str,level: int,joint_result: dict,
                                screen_mobs: int=2,finalist_mobs: int=100,
                                max_finalists: int=8, max_screen_candidates: int=32,
                                source_legal_neighbors_per_seed: int=0,
                                max_screen_wall_s: float | None = None,
                                max_finalist_wall_s: float | None = None,
                                max_shared_evidence_events: int | None = None,
                                max_shared_evidence_cpu_s: float | None = None,
                                strict_l2_item_effects:bool=False,
                                recovery_policies:tuple[BetweenPullPolicy | None,...]=(None,)) -> dict:
    """Re-rank self-discovered named gear×talent×policy by continuous mobs.

    All stages and any neighboring talent allocations come from the source IR.
    Never inject old winners. Two-mob shortlist is heuristic, not optimum proof.
    """
    if not recovery_policies or any(p is not None and not isinstance(p,BetweenPullPolicy) for p in recovery_policies):
        raise ValueError('INVALID_RECOVERY_POLICY_FRONTIER')
    if screen_mobs<1 or finalist_mobs<screen_mobs or max_finalists<1 or max_screen_candidates<1:
        raise ValueError('invalid screening/finalist budget')
    if source_legal_neighbors_per_seed<0:
        raise ValueError('negative source neighbor budget')
    source_ir=build_game_ir_slice(class_key=class_key,level=level)
    eligible=[s for s in _paid_source_candidate_stages(joint_result) if s.get('score_s_per_mob') is not None
              and (s.get('gear_policy_result') or {}).get('winner',{}).get('gear')]
    eligible=_diverse_paid_candidate_order(eligible)
    proposed=[];seen=set()
    # Prefer every independent named gear×policy state before exploring talent
    # variants of the first winner. Otherwise neighbors of the best one-mob
    # build can occupy the entire screen and silently drop other gear builds.
    seeds=[]
    for s in eligible:
        if len(proposed)>=max_screen_candidates:break
        p=s['gear_policy_result']['winner']
        key=(allocation_key(s['allocation']),*_gear_policy_identity(s))
        if key in seen:continue
        seen.add(key);proposed.append((s,None));seeds.append((s,key))
    if source_legal_neighbors_per_seed:
        for s,key in seeds:
            if len(proposed)>=max_screen_candidates:break
            neigh=source_legal_talent_neighbors(source_ir,s['allocation'],level=level)
            for n in neigh['neighbors'][:source_legal_neighbors_per_seed]:
                if len(proposed)>=max_screen_candidates:break
                variant=dict(n.allocation);nkey=(allocation_key(variant),*key[1:])
                if nkey not in seen:
                    seen.add(nkey);proposed.append((s,variant))
    if max_shared_evidence_events is not None and (type(max_shared_evidence_events) is not int or max_shared_evidence_events<1):
        raise ValueError('invalid shared event limit')
    if max_shared_evidence_cpu_s is not None and (not isfinite(max_shared_evidence_cpu_s) or max_shared_evidence_cpu_s<=0):
        raise ValueError('invalid shared CPU limit')
    # Recovery is an explicit joint-search axis. Each scored variant uses the
    # same source IR, CombatRuntime and 100-mob objective; no old-build seed.
    proposed=[(stage,allocation,recovery) for stage,allocation in proposed
              for recovery in recovery_policies][:max_screen_candidates]
    paid_events=0;paid_cpu=0.0;cpu_t0=process_time()
    rows=[]
    for s,allocation,recovery in proposed:
        if (max_shared_evidence_events is not None and paid_events>=max_shared_evidence_events) or (max_shared_evidence_cpu_s is not None and paid_cpu>=max_shared_evidence_cpu_s):
            rows.append({'source_stage_score_s_per_mob':s['score_s_per_mob'],
                         'allocation':dict(s['allocation'] if allocation is None else allocation),
                         'source_stage_allocation':dict(s['allocation']),
                         'source_policy_and_gear_reused':True,
                         'screen':{'status':'BLOCKED_SHARED_EVIDENCE_BUDGET','events':0},
                         'stage':s,'override':allocation,'recovery_policy':recovery})
            continue
        one_cpu=process_time()
        try:
            candidate=prepare_candidate(class_key=class_key,level=level,
                stage=s,allocation_override=allocation,source_ir=source_ir,
                strict_l2_item_effects=strict_l2_item_effects)
            screen=evaluate_persistent_candidate(candidate,level=level,mobs=screen_mobs,
                max_wall_s=max_screen_wall_s,
                max_total_events=None if max_shared_evidence_events is None else max(1,max_shared_evidence_events-paid_events),
                max_cpu_s=None if max_shared_evidence_cpu_s is None else max(.001,max_shared_evidence_cpu_s-paid_cpu),
                recovery_policy=recovery)
        except (ValueError,RuntimeError,KeyError) as exc:
            screen={'status':'BLOCKED_CANDIDATE','reason':str(exc)}
        paid_cpu+=process_time()-one_cpu
        paid_events+=int(screen.get('events') or 0)
        rows.append({'source_stage_score_s_per_mob':s['score_s_per_mob'],
                     'allocation':dict(s['allocation'] if allocation is None else allocation),
                     'source_stage_allocation':dict(s['allocation']),
                     'source_policy_and_gear_reused':allocation is not None or bool(s.get('source_policy_and_gear_reused')),
                     'screen':screen,'stage':s,'override':allocation,'recovery_policy':recovery})
    viable=[r for r in rows if r['screen']['status']=='COMPLETE']
    viable.sort(key=lambda r:(r['screen']['mean_s_per_mob'],allocation_key(r['allocation'])))
    finalists=[]
    for row in viable[:max_finalists]:
        if (max_shared_evidence_events is not None and paid_events>=max_shared_evidence_events) or (max_shared_evidence_cpu_s is not None and paid_cpu>=max_shared_evidence_cpu_s):
            finalists.append({'allocation':row['allocation'], 'persistent':{
                'status':'BLOCKED_SHARED_EVIDENCE_BUDGET','events':0},'stage':row['stage'],'recovery_policy':None if row['recovery_policy'] is None else vars(row['recovery_policy'])})
            continue
        one_cpu=process_time()
        candidate=prepare_candidate(class_key=class_key,level=level,stage=row['stage'],
            allocation_override=row['override'],source_ir=source_ir,
            strict_l2_item_effects=strict_l2_item_effects)
        verified=evaluate_persistent_candidate(candidate,level=level,mobs=finalist_mobs,
            max_wall_s=max_finalist_wall_s,
            max_total_events=None if max_shared_evidence_events is None else max(1,max_shared_evidence_events-paid_events),
            max_cpu_s=None if max_shared_evidence_cpu_s is None else max(.001,max_shared_evidence_cpu_s-paid_cpu),
            recovery_policy=row['recovery_policy'])
        paid_cpu+=process_time()-one_cpu
        paid_events+=int(verified.get('events') or 0)
        finalists.append({'allocation':row['allocation'],
            'single_mob_stage_score':row['source_stage_score_s_per_mob'],
            'screen_mean_s_per_mob':row['screen']['mean_s_per_mob'],
            'persistent':verified,
            'source_policy_and_gear_reused':row['source_policy_and_gear_reused'],
            'stage':row['stage'],'recovery_policy':None if row['recovery_policy'] is None else vars(row['recovery_policy'])})
    winners=[x for x in finalists if x['persistent']['status']=='COMPLETE']
    winners.sort(key=lambda x:(x['persistent']['mean_s_per_mob'],allocation_key(x['allocation'])))
    return {'status':'PERSISTENT_VERIFIED_BOUNDED' if winners else 'BLOCKED_NO_PERSISTENT_FINALIST',
       'class_key':class_key,'level':level,
       'screen_mobs':screen_mobs,'finalist_mobs':finalist_mobs,
       'joint_stages':len(joint_result.get('stages',())),'paid_candidate_stages':len(eligible),
       'screen_evaluated':len(rows),
       'screen_completed':len(viable),'finalists_evaluated':len(finalists),
       'winner':winners[0] if winners else None,
       'finalists':finalists,
       'screening':[{'allocation':r['allocation'],
                     'source_stage_score_s_per_mob':r['source_stage_score_s_per_mob'],
                     'screen':r['screen'],
                     'source_policy_and_gear_reused':r['source_policy_and_gear_reused'],
                     'recovery_policy':None if r['recovery_policy'] is None else vars(r['recovery_policy'])} for r in rows],
       'budget_pruned_screens':sum(r['screen']['status']=='BLOCKED_EVALUATION_TIME_BUDGET' for r in rows),
       'budget_pruned_finalists':sum(f['persistent']['status']=='BLOCKED_EVALUATION_TIME_BUDGET' for f in finalists),
       'max_screen_wall_s':max_screen_wall_s,'max_finalist_wall_s':max_finalist_wall_s,
       'paid_persistent_events':paid_events,'paid_persistent_cpu_s':paid_cpu,
       'shared_event_limit':max_shared_evidence_events,'shared_cpu_limit_s':max_shared_evidence_cpu_s,
       'candidate_coverage_complete':False,'global_optimum_proven':False,
       'limitations':['bounded source-stage and two-mob screen; omitted candidates may be better',
                      'unverified sourced action coverage blocks formal acceptance']}


def _refine_fullcycle_winner_with_source_gear(*, class_key: str, level: int, finalists: dict,
                                             enabled: bool, max_proposals: int,
                                             max_finalists: int) -> dict:
    """100-mob legal-gear challengers; never use a two-mob top-list as proof."""
    if not enabled or not finalists.get('winner'):
        return {'status':'NOT_REQUESTED_OR_NO_SEED','winner':None}
    from src.v2.source_persistent_gear_neighborhood import refine_source_gear_persistent
    seed=finalists['winner']
    outcome=refine_source_gear_persistent(class_key=class_key,level=level,
         stage=seed['stage'],screen_mobs=10,finalist_mobs=finalists['finalist_mobs'],
         max_proposals=max_proposals,max_finalists=max_finalists)
    candidate=outcome.get('winner')
    if candidate and candidate['persistent']['mean_s_per_mob'] < seed['persistent']['mean_s_per_mob']-1e-10:
        finalists['winner']={
            'allocation':dict(candidate['stage']['allocation']),
            'single_mob_stage_score':None,  # newly proposed gear not falsely L2-scored
            'screen_mean_s_per_mob':candidate['screen']['mean_s_per_mob'],
            'persistent':candidate['persistent'],
            'source_policy_and_gear_reused':True,
            'gear_refinement_origin':'source_only_weight_perturbation_long_horizon',
            'stage':candidate['stage']}
        finalists['post_search_source_gear_improved']=True
    else:
        finalists['post_search_source_gear_improved']=False
    return outcome


def persistent_winner_source_manifest(*, class_key: str, level: int, winner: dict | None) -> dict:
    """Unambiguous score, gear, talent, policy and acquisition proof for finalist.

    Staged source identity and item acquisition cannot silently be promoted to
    checkpoint-accepted just because a 100-mob scorer returns COMPLETE.
    """
    if winner is None:
        return {'status':'BLOCKED_NO_WINNER','formal_checkpoint_accepted':False}
    from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
    stage=winner['stage']
    selected=stage['gear_policy_result']['winner']
    gear=selected['gear']
    ranked=audit_named_gear_source(class_key=class_key,level=level,gear=gear)
    r=winner['persistent']
    policy=selected['winner']
    return {'status':'BOUNDED_SOURCE_WINNER_WITH_AVAILABILITY_EVIDENCE_GAPS',
            'class_key':class_key,'level':level,
            'allocation':dict(winner['allocation']),
            'gear':{'role':gear['role'],
                    'items':{str(k):{'item_id':int(v['item_id']),'name':str(v['name'])}
                             for k,v in sorted(gear['slots'].items())},
                    'aggregate_stats':dict(gear['aggregate_stats'])},
            'policy':{'opening':list(policy['prefix']),'fallback':policy['fallback'],
                      'guarded_action':policy.get('guarded_action'),
                      'guarded_conditions':policy.get('guarded_conditions')},
            'recovery_policy':winner.get('recovery_policy'),
            'persistent':{'mob_count':r.get('count'),'mean_s_per_mob':r.get('mean_s_per_mob'),
                          'combat_s':r.get('combat_s'),'recovery_s':r.get('recovery_s'),
                          'maintenance_s':r.get('maintenance_s'),'events':r.get('events')},
            'acquisition_evidence':ranked,
            'formal_checkpoint_accepted':False,
            'blockers':['BLOCKED_UNVERIFIED_ITEM_AVAILABILITY_METHOD',
                        'BLOCKED_INCOMPLETE_DURABLE_SOURCE_ABILITIES',
                        'BLOCKED_UNPROVEN_GLOBAL_GEAR_TALENT_POLICY_COVERAGE']}


def run_source_persistent_joint_search(*,class_key: str,level: int,
                                       joint_kwargs: dict,screen_mobs:int=2,
                                       finalist_mobs:int=100,max_finalists:int=8,
                                       max_screen_candidates:int=32,
                                       source_legal_neighbors_per_seed:int=0,
                                       max_screen_wall_s:float|None=None,
                                       max_finalist_wall_s:float|None=None,
                                       source_gear_refinement:bool=True,
                                       max_gear_perturbations:int=24,
                                       max_gear_refined_finalists:int=5) -> dict:
    """Production-facing joint optimizer which *selects* on 100-mob objective."""
    start=monotonic()
    if joint_kwargs.get('initial_allocation'):
        raise ValueError('blind search cannot seed talent allocation')
    if {'class_key','level','ir_slice'} & set(joint_kwargs):
        raise ValueError('class and level must not be overridden by joint_kwargs')
    joint=run_source_budgeted_joint_talents(class_key=class_key,level=level,**joint_kwargs)
    finalists=select_persistent_finalists(class_key=class_key,level=level,
        joint_result=joint,screen_mobs=screen_mobs,finalist_mobs=finalist_mobs,
        max_finalists=max_finalists,max_screen_candidates=max_screen_candidates,
        source_legal_neighbors_per_seed=source_legal_neighbors_per_seed,
        max_screen_wall_s=max_screen_wall_s,max_finalist_wall_s=max_finalist_wall_s)
    gear_refinement=_refine_fullcycle_winner_with_source_gear(
        class_key=class_key,level=level,finalists=finalists,
        enabled=source_gear_refinement,max_proposals=max_gear_perturbations,
        max_finalists=max_gear_refined_finalists)
    return {'schema':'source_persistent_joint_search_v1',
        'class_key':class_key,'level':level,'one_mob_winner':joint['winner'],
        'persistent_winner':finalists['winner'],
        'winner_source_manifest':persistent_winner_source_manifest(class_key=class_key,level=level,winner=finalists['winner']),
        'search_attempts':joint['attempted'],'search_events':joint['event_transitions'],
        'source_context_sha256':joint['source_context_sha256'],
        'screening':finalists,'source_gear_refinement':gear_refinement,'wall_s':monotonic()-start,
        'global_optimum_proven':False,'formal_checkpoint_accepted':False}


def run_source_persistent_profile_search(*,class_key: str, level: int,
                                         profiles: tuple[tuple[str,dict], ...],
                                         screen_mobs: int=2,finalist_mobs: int=100,
                                         max_finalists: int=8,
                                         max_screen_candidates: int=40,
                                         source_legal_neighbors_per_seed: int=0,
                                         max_screen_wall_s:float|None=None,
                                         max_finalist_wall_s:float|None=None,
                                         source_gear_refinement:bool=True,
                                         max_gear_perturbations:int=24,
                                         max_gear_refined_finalists:int=5) -> dict:
    """Independent blind budget profiles; one paid persistent objective.

    Each profile independently starts from the source-empty talent build. It
    cannot consume any winner from another profile or from historical files.
    The union of L2-tested configurations is screened and finally ranked by
    persistent CombatRuntime kill + recovery, not by first-mob time.
    """
    if not profiles or len({name for name,_ in profiles}) != len(profiles):
        raise ValueError('need named unique source search profiles')
    t0=monotonic();results=[];all_stages=[];attempts=events=0
    for name,kwargs in profiles:
        if not name or {'class_key','level','ir_slice'} & set(kwargs):
            raise ValueError('profile may not override source context')
        if kwargs.get('initial_allocation'):
            raise ValueError('blind profile cannot seed talent allocation')
        began=monotonic()
        result=run_source_budgeted_joint_talents(class_key=class_key,level=level,**kwargs)
        attempts+=result['attempted'];events+=result['event_transitions']
        all_stages.extend(_paid_source_candidate_stages(result))
        results.append({'name':name,'attempted':result['attempted'],
            'event_transitions':result['event_transitions'],
            'talent_states_evaluated':result['talent_states_evaluated'],
            'unsearched_legal_talents':result['pending_legal_talent_states'],
            'winner_single_mob_s':result['winner']['score_s_per_mob'] if result['winner'] else None,
            'source_context_sha256':result['source_context_sha256'],
            'wall_s':monotonic()-began})
    combined={'stages':all_stages}
    finalists=select_persistent_finalists(class_key=class_key,level=level,
        joint_result=combined,screen_mobs=screen_mobs,finalist_mobs=finalist_mobs,
        max_finalists=max_finalists,max_screen_candidates=max_screen_candidates,
        source_legal_neighbors_per_seed=source_legal_neighbors_per_seed,
        max_screen_wall_s=max_screen_wall_s,max_finalist_wall_s=max_finalist_wall_s)
    gear_refinement=_refine_fullcycle_winner_with_source_gear(
        class_key=class_key,level=level,finalists=finalists,
        enabled=source_gear_refinement,max_proposals=max_gear_perturbations,
        max_finalists=max_gear_refined_finalists)
    return {'schema':'source_persistent_blind_multi_profile_v1',
        'class_key':class_key,'level':level,'profile_results':results,
        'total_search_attempts':attempts,'total_search_events':events,
        'persistent_winner':finalists['winner'],
        'winner_source_manifest':persistent_winner_source_manifest(class_key=class_key,level=level,winner=finalists['winner']),
        'screening':finalists,'source_gear_refinement':gear_refinement,'wall_s':monotonic()-t0,
        'global_optimum_proven':False,'formal_checkpoint_accepted':False}

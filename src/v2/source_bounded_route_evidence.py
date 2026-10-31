"""Fail-closed reader for *bounded* source-legal scored route evidence.

This is deliberately not a product route-completion or independent fidelity
certificate. It only promotes a current-version, source-identical set of real
L2-scored consecutive native scenarios into the `evaluated` evidence tier.
"""
from __future__ import annotations

from hashlib import sha256
from json import dumps, loads
from math import isfinite
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.game.talents import apply_talent_selection
from src.game.data.forever.sqlite_talents import DEFAULT_DB as TALENT_DB
from src.version import SOFTWARE_VERSION
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record, source_execution_context
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.v2.generic_backend import _policy_combat_evaluation

EVIDENCE_FILE='data/forever/source_bounded_level_routes_v1.json'


def checked_source_scenario_routes(root: Path, *, version: str, item_db_sha: str):
    path=Path(root)/EVIDENCE_FILE
    diagnostic={'path':EVIDENCE_FILE, 'valid':False, 'sha256':None, 'failures':[]}
    rows={}
    if not path.is_file():
        diagnostic['failures'].append('missing_bounded_route_evidence')
        return diagnostic, rows
    payload=path.read_bytes()
    diagnostic['sha256']=sha256(payload).hexdigest()
    try:
        data=loads(payload)
        if data.get('software_version')!=version or version!=SOFTWARE_VERSION:
            raise ValueError('version_mismatch')
        if data.get('canonical_item_db_sha256')!=item_db_sha:
            raise ValueError('item_database_mismatch')
        if data.get('canonical_talent_db_sha256')!=sha256(Path(TALENT_DB).read_bytes()).hexdigest():
            raise ValueError('talent_database_mismatch')
        classes=data.get('classes')
        if not isinstance(classes,dict) or set(classes)!=set(
                ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')):
            raise ValueError('nine_class_scope_mismatch')
        expected_start=int(data['start_level']); expected_end=int(data['end_level'])
        if expected_start < 10 or expected_end > 60 or expected_start>expected_end:
            raise ValueError('invalid_level_range')
        # Cheap whole-file structural/legality-claim preflight. Reject bogus
        # summaries, route claims or budgets BEFORE running any costly L2
        # scratch replays. The second pass checks actual source IR and scores.
        preliminary_events=preliminary_attempts=preliminary_steps=preliminary_full=0
        for cls,record in classes.items():
            if record.get('full_route_complete') is not False or record.get('accepted_class_level_checkpoints')!=0:
                raise ValueError('unproven_completion_or_checkpoint_claim')
            if any(record.get(flag) is not False for flag in (
                    'named_gear_acquisition_verified',
                    'ability_trainer_quest_rune_acquisition_verified',
                    'travel_and_xp_timing_verified',
                    'cross_level_resource_carry_verified',
                    'indexed_effect_source_complete',
                    'independent_reference_verified')):
                raise ValueError('false_fidelity_evidence_claim')
            route=record.get('selected_route') or []
            last=record.get('last_contiguous_level')
            if [s.get('level') for s in route]!=list(range(expected_start,expected_start+len(route))):
                raise ValueError(f'{cls}:broken_level_sequence')
            if bool(route) != (last is not None) or (route and last != route[-1]['level']):
                raise ValueError(f'{cls}:incorrect_route_endpoint')
            complete=bool(route and last==expected_end)
            if record.get('status')!=('EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
                    if complete else 'PARTIAL_BOUNDED_SOURCE_SCENARIO'):
                raise ValueError(f'{cls}:misclassified_corridor')
            preliminary_full+=int(complete)
            preliminary_steps+=len(route)
            measured=record.get('compute') or {}
            budget=record.get('global_budget') or {}
            if (not 0<=measured.get('event_transitions',-1)<=budget.get('max_events',-1) or
                    not 0<=measured.get('l2_attempts',-1)<=budget.get('max_l2_attempts',-1)):
                raise ValueError(f'{cls}:compute_budget_broken')
            preliminary_events+=int(measured['event_transitions'])
            preliminary_attempts+=int(measured['l2_attempts'])
            for step in route:
                if (step.get('scratch_verification_complete') is not True or
                    step.get('real_l2_attempts',0)<3 or step.get('executor_event_transitions',0)<1 or
                    step.get('cpu_ns',0)<1 or
                    not isinstance(step.get('full_cycle_s_per_mob'),(int,float)) or
                    not isfinite(step['full_cycle_s_per_mob']) or step['full_cycle_s_per_mob']<=0):
                    raise ValueError(f'{cls}:unverified_or_invalid_score')
        summ=data.get('summary') or {}
        if (summ.get('full_bounded_legal_source_scenario_corridors')!=preliminary_full or
            summ.get('source_legal_scratch_verified_steps_in_selected_paths')!=preliminary_steps or
            summ.get('total_real_executor_events_all_attempts')!=preliminary_events or
            summ.get('total_real_L2_attempts')!=preliminary_attempts or
            summ.get('accepted_source_complete_class_level_checkpoints')!=0 or
            summ.get('validated_full_continuous_leveling_routes')!=0):
            raise ValueError('summary_integrity_mismatch')
        all_events=all_attempts=all_selected_steps=full_count=0
        for cls,record in classes.items():
            if record.get('full_route_complete') is not False or record.get('accepted_class_level_checkpoints')!=0:
                raise ValueError('unproven_completion_or_checkpoint_claim')
            if any(record.get(flag) is not False for flag in (
                    'named_gear_acquisition_verified',
                    'ability_trainer_quest_rune_acquisition_verified',
                    'travel_and_xp_timing_verified',
                    'cross_level_resource_carry_verified',
                    'indexed_effect_source_complete',
                    'independent_reference_verified')):
                raise ValueError('false_fidelity_evidence_claim')
            route=record.get('selected_route') or []
            last=record.get('last_contiguous_level')
            if [s.get('level') for s in route]!=list(range(expected_start,expected_start+len(route))):
                raise ValueError(f'{cls}:broken_level_sequence')
            if bool(route) != (last is not None) or (route and last != route[-1]['level']):
                raise ValueError(f'{cls}:incorrect_route_endpoint')
            complete=bool(route and last==expected_end)
            required_status=('EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
                             if complete else 'PARTIAL_BOUNDED_SOURCE_SCENARIO')
            if record.get('status')!=required_status:
                raise ValueError(f'{cls}:misclassified_corridor')
            all_selected_steps+=len(route)
            full_count+=int(complete)
            parent=None
            for step in route:
                level=int(step['level'])
                source=build_game_ir_slice(class_key=cls,level=level)
                if source is None:
                    raise ValueError(f'{cls}:no_source_ir_L{level}')
                talented,_=apply_talent_selection(source,step['talents'],level=level)
                source_context=source_execution_context(talented)
                if source_context!=step.get('source_context'):
                    raise ValueError(f'{cls}:source_or_engine_context_mismatch_L{level}')
                state=LevelState(class_key=cls,level=level,
                    race_key=step.get('source_scenario_race'),
                    talents=step['talents'],action_ids=tuple(step['source_action_ids']))
                validate_level_state(state)
                legal=(validate_level_transition(parent,state) if parent else None)
                if legal!=step.get('source_legal_transition'):
                    raise ValueError(f'{cls}:bad_talent_or_acquisition_transition_L{level}')
                if (step.get('scratch_verification_complete') is not True or
                    step.get('real_l2_attempts',0)<3 or step.get('executor_event_transitions',0)<1 or
                    step.get('cpu_ns',0)<1 or
                    not isinstance(step.get('full_cycle_s_per_mob'),(int,float)) or
                    not isfinite(step['full_cycle_s_per_mob']) or step['full_cycle_s_per_mob']<=0):
                    raise ValueError(f'{cls}:unverified_or_invalid_score_L{level}')
                # Do not trust a copied 'scratch_verified=True' flag or an
                # edited score: independently REPLAY the exact saved policy
                # through the production executor on canonical talent-adjusted
                # source IR, with real incoming damage and full recovery.
                guard_conditions=tuple(_condition_from_record(x)
                                       for x in step.get('guarded_conditions', ()))
                replay_policy=_make_policy(talented,step['fallback'],
                    guarded_action=step.get('guarded_action'),
                    guarded_conditions=guard_conditions)
                actual,execution,_=_policy_combat_evaluation(
                    talented,level=level,policy_override=replay_policy,
                    opening_action_ids=tuple(step['prefix']),
                    schedule_incoming_attacks=True)
                if (actual is None or execution is None or
                    not execution.timeline.target_defeated or
                    not ordered_prefix_executed(execution,tuple(step['prefix'])) or
                    abs(float(actual.seconds_per_mob)-float(step['full_cycle_s_per_mob']))>1e-9):
                    raise ValueError(f'{cls}:independent_full_cycle_replay_mismatch_L{level}')
                rows[(cls,level)]={'legacy_fallback':False,
                    'seconds_per_mob':float(step['full_cycle_s_per_mob']),
                    'policy_ir': {'prefix':step['prefix'],'fallback':step['fallback']},
                    'bounded_route_source':'source_budgeted_level_route',
                    'source_legal_level_transition':legal is not None,
                    'scratch_l2_verified':True}
                parent=state
            measured=record.get('compute') or {}
            all_events+=int(measured.get('event_transitions',-1))
            all_attempts+=int(measured.get('l2_attempts',-1))
            budget=record.get('global_budget') or {}
            if (not 0<=measured.get('event_transitions',-1)<=budget.get('max_events',-1) or
                    not 0<=measured.get('l2_attempts',-1)<=budget.get('max_l2_attempts',-1)):
                raise ValueError(f'{cls}:compute_budget_broken')
        summ=data.get('summary') or {}
        if (summ.get('full_bounded_legal_source_scenario_corridors')!=full_count or
            summ.get('source_legal_scratch_verified_steps_in_selected_paths')!=all_selected_steps or
            summ.get('total_real_executor_events_all_attempts')!=all_events or
            summ.get('total_real_L2_attempts')!=all_attempts or
            summ.get('accepted_source_complete_class_level_checkpoints')!=0 or
            summ.get('validated_full_continuous_leveling_routes')!=0):
            raise ValueError('summary_integrity_mismatch')
        diagnostic.update(valid=True,
            full_bounded_corridors=full_count,
            scratch_verified_source_scenario_steps=all_selected_steps,
            real_l2_attempts=all_attempts, executor_events=all_events)
        return diagnostic,rows
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
        diagnostic['failures'].append(f'{type(exc).__name__}:{exc}')
        return diagnostic,{}

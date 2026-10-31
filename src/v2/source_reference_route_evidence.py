"""Independently replayed historical full-point source-scenario route evidence.

This is a read-only held-out reference validator, NOT a search, acquisition
proof or product checkpoint certificate. Rejects stale source/HP/ruleset.
"""
from __future__ import annotations
import json
from math import isfinite
from pathlib import Path
from hashlib import sha256
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.v2.source_stateful_budgeted import _make_policy, source_execution_context
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.v2.generic_backend import _policy_combat_evaluation
from src.version import SOFTWARE_VERSION

REFERENCE_PATH='data/forever/wf289_parent_druid_l1_60_replay.json'


def checked_reference_druid_route(root: Path, *, version: str):
    path=Path(root)/REFERENCE_PATH
    diag={'path':REFERENCE_PATH,'valid':False,'sha256':None,'failures':[]}
    if not path.is_file():
        diag['failures'].append('missing_replayed_reference')
        return diag,{}
    blob=path.read_bytes();diag['sha256']=sha256(blob).hexdigest()
    try:
        d=json.loads(blob)
        if (d.get('software_version')!=version or version!=SOFTWARE_VERSION or
            d.get('class_key')!='druid' or
            d.get('authority')!='WF288-heldout-reference-replayed-on-WF289-production-executor'):
            raise ValueError('wrong_current_source_or_engine_authority')
        steps=d['steps']
        if (len(steps)!=60 or d.get('replayed_levels')!=60 or
            [r.get('level') for r in steps]!=list(range(1,61)) or
            d.get('status')!='EVALUATED_BOUNDED_CONTIGUOUS_SOURCE_SCENARIO'):
            raise ValueError('incomplete_continuity')
        if (d.get('full_source_complete_checkpoints')!=0 or
            d.get('full_world_legal_leveling_routes')!=0 or
            d.get('independent_joint_search_performed') is not False or
            any(d.get(x) is not False for x in (
                'gear_acquisition_verified', 'trainer_quest_rune_verified',
                'xp_travel_and_resource_carry_verified',
                'independent_forever_fidelity_verified'))):
            raise ValueError('false_route_completion_or_search_claim')
        if sum(int(x.get('real_full_executor_events',-1)) for x in steps)!=d.get('sum_event_transitions'):
            raise ValueError('replay_event_count_mismatch')
        rows={};prev=None
        for step in steps:
            level=int(step['level'])
            ir=build_game_ir_slice(class_key='druid',level=level)
            if ir is None:raise ValueError(f'missing_ir_L{level}')
            talented,_=apply_talent_selection(ir,step['talents'],level=level)
            if source_execution_context(talented)!=step['source_context']:
                raise ValueError(f'stale_source_or_scenario_L{level}')
            state=LevelState('druid',level,step.get('source_scenario_race'),
                step['talents'],tuple(step['source_action_ids']))
            validate_level_state(state)
            edge=validate_level_transition(prev,state) if prev else None
            if edge!=step.get('source_legal_transition'):
                raise ValueError(f'illegal_transition_L{level}')
            if ((level<10 and sum(step['talents'].values())!=0) or
                (level>=10 and sum(step['talents'].values())!=level-9)):
                raise ValueError(f'not_full_source_talent_points_L{level}')
            if step.get('scratch_replayed_real_executor') is not True:
                raise ValueError('missing_real_executor_replay')
            policy=_make_policy(talented,step['continuation_fallback'],
                    guarded_action=step.get('guarded_action'))
            result,execution,details=_policy_combat_evaluation(
                talented,level=level,policy_override=policy,
                opening_action_ids=tuple(step['policy_prefix']),
                schedule_incoming_attacks=True)
            score=float(step['full_cycle_s_per_mob'])
            if (result is None or execution is None or
                not execution.timeline.target_defeated or
                not ordered_prefix_executed(execution,tuple(step['policy_prefix'])) or
                not isfinite(score) or score <= 0 or
                abs(result.seconds_per_mob-score)>1e-9):
                raise ValueError(f'full_cycle_score_replay_mismatch_L{level}')
            rows[('druid',level)]={
                'legacy_fallback':False, 'seconds_per_mob':score,
                'policy_ir':{'prefix':step['policy_prefix'],
                             'fallback':step['continuation_fallback']},
                'bounded_route_source':'wf288-fullpoint-parent-replay',
                'scratch_l2_verified':True}
            prev=state
        diag.update(valid=True,independently_replayed_levels=len(rows))
        return diag,rows
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        diag['failures'].append(f'{type(exc).__name__}:{exc}')
        return diag,{}

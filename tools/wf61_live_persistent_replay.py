"""Issue #61: execute actual source-backed gsim 1/2/100 paid-pull replays.

This invokes the EXISTING persistent CombatRuntime evaluator; it does not
implement native combat or native↔world ACK and cannot certify PROCESS gates.
Example (sourced L30 diagnostic, NOT the Druid L60 acceptance checkpoint):
  python tools/wf61_live_persistent_replay.py --class druid --level 30 \
    --stage evidence/wf353/WF353_L30_P3_BEST_JOINT_ITEM_STAGE.json \
    --ability-db data/forever/staged_druid_l30_talents_70338.sqlite \
    --observations evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json \
    --control-observations evidence/wf321/druid_l20_control_observations.json \
    --build-as-of 2026-10-13 --out /tmp/wf61-source-gsim-replay.json
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
import shutil
from tempfile import TemporaryDirectory
from math import isfinite
from pathlib import Path
COUNTS = (1, 2, 100)


def load_source_stage(path: Path) -> tuple[dict, str]:
    """Read actual candidate input; fingerprint raw bytes, never a saved score."""
    raw = path.read_bytes()
    data = json.loads(raw)
    stage = data.get('winner', data) if isinstance(data, dict) else None
    if (not isinstance(stage, dict)
            or not isinstance(stage.get('allocation'), dict)
            or not isinstance(stage.get('gear_policy_result'), dict)):
        raise ValueError('WF61_INVALID_SOURCE_STAGE')
    return stage, sha256(raw).hexdigest()


def _finite_number(value, name: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError('WF61_INVALID_NUMBER:' + name)
    return float(value)


_TRACE_RESOURCE_CHANNELS = ('health', 'mana', 'energy')


def _actor_resources(resources: object, label: str, expected_channels: frozenset[str]) -> dict:
    """Require explicit numbers for sourced channels, explicit None for absent ones.

    The existing gsim producer emits all three keys but ActorState.resource_amount
    returns None for channels not defined by the class. Missing keys remain errors.
    """
    if not isinstance(resources, dict):
        raise ValueError('WF61_ACTOR_RESOURCE_EVIDENCE_MISSING:' + label)
    values = {}
    for channel in _TRACE_RESOURCE_CHANNELS:
        if channel not in resources:
            raise ValueError('WF61_ACTOR_RESOURCE_EVIDENCE_MISSING:' + label + ':' + channel)
        value = resources[channel]
        if channel not in expected_channels:
            if value is not None:
                raise ValueError('WF61_UNEXPECTED_ACTOR_RESOURCE:' + label + ':' + channel)
            values[channel] = None
            continue
        value = _finite_number(value, label + '_' + channel)
        if value < 0 or (channel == 'health' and value <= 0):
            raise ValueError('WF61_ACTOR_INVALID_RESOURCE:' + label + ':' + channel)
        values[channel] = value
    return values


def validate_real_replay(result: dict, requested_mobs: int, *,
                         expected_resource_channels: frozenset[str] | None = None) -> dict:
    """Fail closed on missing actual gsim trace, clock, actions or paid time.

    Contract validation alone is NOT a combat execution; the caller must
    supply the real result from evaluate_persistent_candidate(trace_pulls=True).
    """
    if expected_resource_channels is None:
        # Contract-only callers default to three present channels. Production
        # passes the class's source-defined actor channels explicitly.
        expected_resource_channels = frozenset(_TRACE_RESOURCE_CHANNELS)
    if ('health' not in expected_resource_channels
            or not expected_resource_channels.issubset(_TRACE_RESOURCE_CHANNELS)):
        raise ValueError('WF61_INVALID_SOURCE_RESOURCE_CHANNEL_SET')
    if not isinstance(result, dict) or result.get('status') != 'COMPLETE':
        raise ValueError('WF61_INCOMPLETE_COMBAT')
    if (type(requested_mobs) is not int or requested_mobs < 1
            or type(result.get('count')) is not int
            or result['count'] != requested_mobs):
        raise ValueError('WF61_INCORRECT_MOB_COUNT')
    # The paid 100-mob objective includes recovery after the final kill.
    # A coherent but intentionally unsettled quest-horizon trace is not
    # interchangeable with this objective.
    if result.get('settle_final_recovery') is not True:
        raise ValueError('WF61_FINAL_RECOVERY_NOT_SETTLED')
    if (result.get('continuous_actor_state') is not True
            or result.get('source_only') is not True
            or result.get('spatial_mode') != '2d_sequential_not_simultaneous_pack'):
        raise ValueError('WF61_NOT_PERSISTENT_SOURCE_GSIM')
    if (type(result.get('events')) is not int or result['events'] < requested_mobs
            or not isinstance(result.get('source_action_counts'), dict)
            or not result['source_action_counts']):
        raise ValueError('WF61_NO_EXECUTED_SOURCE_ACTIONS')
    total = _finite_number(result.get('total_s'), 'total_s')
    mean = _finite_number(result.get('mean_s_per_mob'), 'mean_s_per_mob')
    recovery = _finite_number(result.get('recovery_s'), 'recovery_s')
    combat = _finite_number(result.get('combat_s'), 'combat_s')
    maintenance = _finite_number(result.get('maintenance_s'), 'maintenance_s')
    travel = _finite_number(result.get('spaced_travel_s'), 'spaced_travel_s')
    if (total <= 0 or mean <= 0 or combat <= 0 or recovery < 0
            or maintenance < 0 or travel < 0
            or abs(total - (combat + recovery + maintenance + travel)) > 1e-6 * max(1., total)
            or abs(total - mean * requested_mobs) > 1e-6 * max(1., total)
            or total + 1e-6 < combat + recovery):
        raise ValueError('WF61_UNPAID_OR_INCONSISTENT_OBJECTIVE')
    audit = result.get('pull_trace_audit')
    if (not isinstance(audit, dict)
            or audit.get('status') != 'GSIM_PERSISTENT_TRACE_INVARIANTS_ONLY'
            or type(audit.get('distinct_targets')) is not int
            or audit['distinct_targets'] != requested_mobs
            or audit.get('native_world_action_ack_verified') is not False):
        raise ValueError('WF61_TRACE_AUDIT_NOT_GSIM_ONLY')
    # The real source evaluator emits a duration map for every long cooldown.
    # A trace must not invent ready timers or used actions unrelated to it.
    long_cooldowns = result.get('long_cooldown_source_actions_s')
    if (not isinstance(long_cooldowns, dict)
            or not all(isinstance(k, str) and k
                       and type(v) in (int, float) and isfinite(v) and v > 0
                       for k, v in long_cooldowns.items())):
        raise ValueError('WF61_LONG_COOLDOWN_SOURCE_MAP_INVALID')
    rows = result.get('pull_trace')
    if not isinstance(rows, list) or len(rows) != requested_mobs:
        raise ValueError('WF61_MISSING_ACTUAL_PULL_TRACE')
    final_resources = _actor_resources(result.get('final_resources'), 'final', expected_resource_channels)
    previous_end = 0.
    previous_resources = None
    ids = set()
    sum_combat = sum_recovery = 0.
    inter_pull_s = 0.
    action_totals = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or type(row.get('mob')) is not int or row['mob'] != index:
            raise ValueError('WF61_PULL_ORDER')
        target = row.get('target_id')
        if not isinstance(target, str) or not target or target in ids:
            raise ValueError('WF61_TARGET_NOT_DISTINCT')
        ids.add(target)
        start = _finite_number(row.get('pull_started_s'), 'pull_started_s')
        kill = _finite_number(row.get('kill_finished_s'), 'kill_finished_s')
        paid = _finite_number(row.get('recovery_s'), 'pull_recovery_s')
        end = _finite_number(row.get('recovery_finished_s'), 'recovery_finished_s')
        combat_s = _finite_number(row.get('combat_s'), 'pull_combat_s')
        if (start + 1e-7 < previous_end or kill <= start
                or paid < 0
                or abs(end - (kill + paid)) > 1e-6 * max(1., abs(end))
                or abs((kill - start) - combat_s) > 1e-6):
            raise ValueError('WF61_PULL_CLOCK_OR_RECOVERY')
        # The real retained gsim producer emits these snapshots on every pull.
        # A COMPLETE flag cannot conceal death or an inconsistent final actor.
        before = _actor_resources(row.get('health_mana_energy_before'), 'before', expected_resource_channels)
        # A zero-time transition cannot silently change the same actor's state.
        # With positive paid inter-pull time, upkeep/periodics may change it.
        if previous_resources is not None and abs(start - previous_end) <= 1e-7:
            for channel, value in before.items():
                prior = previous_resources[channel]
                if value is None:
                    continue
                if abs(value - prior) > 1e-6 * max(1., abs(prior)):
                    raise ValueError('WF61_ZERO_GAP_RESOURCE_DISCONTINUITY:' + channel)
        _actor_resources(row.get('health_mana_energy_at_kill'), 'kill', expected_resource_channels)
        recovered = _actor_resources(
            row.get('health_mana_energy_after_recovery'), 'recovered',
            expected_resource_channels)
        if index == requested_mobs:
            for channel, final_value in final_resources.items():
                if final_value is None:
                    continue
                if abs(recovered[channel] - final_value) > 1e-6 * max(1., abs(final_value)):
                    raise ValueError('WF61_FINAL_RESOURCE_SNAPSHOT_MISMATCH:' + channel)
        actions = row.get('actions')
        if (not isinstance(actions, dict) or not actions
                or not all(isinstance(k, str) and k and type(n) is int and n > 0
                           for k, n in actions.items())):
            raise ValueError('WF61_PULL_WITHOUT_REAL_ACTIONS')
        ready = row.get('long_cooldown_timer_ready_at_pull')
        used = row.get('long_cooldowns_used')
        remaining = row.get('long_cooldowns_not_ready_at_kill')
        if (not isinstance(ready, dict) or set(ready) != set(long_cooldowns)
                or any(type(flag) is not bool for flag in ready.values())
                or not isinstance(used, dict)
                or any(k not in long_cooldowns or type(n) is not int or n <= 0
                       or n > actions.get(k, 0) for k, n in used.items())
                or any(used.get(k, 0) != actions.get(k, 0)
                       for k in long_cooldowns)
                or not isinstance(remaining, dict)
                or any(k not in long_cooldowns or type(seconds) not in (int, float)
                       or not isfinite(seconds) or seconds <= 0
                       for k, seconds in remaining.items())):
            raise ValueError('WF61_LONG_COOLDOWN_TRACE_INVALID')
        for key, value in actions.items():
            action_totals[key] = action_totals.get(key, 0) + value
        inter_pull_s += max(0., start - previous_end)
        previous_end = end
        previous_resources = recovered
        sum_combat += combat_s
        sum_recovery += paid
    if (not all(isinstance(k, str) and k and type(v) is int and v > 0
                for k, v in result['source_action_counts'].items())
            or action_totals != result['source_action_counts']):
        raise ValueError('WF61_SOURCE_ACTION_AGGREGATE_MISMATCH')
    # A monotonic trace is insufficient: every actor-clock second must be
    # charged to combat, recovery, source maintenance or spatial travel.
    # This catches omitted downtime and fabricated paid overhead alike.
    if (abs(previous_end - total) > 1e-6 * max(1., total)
            or abs(inter_pull_s - (maintenance + travel)) > 1e-6 * max(1., total)):
        raise ValueError('WF61_ACTOR_CLOCK_UNPAID_OR_PHANTOM_GAP')
    if (abs(sum_combat - combat) > 1e-6 * max(1., combat)
            or abs(sum_recovery - recovery) > 1e-6 * max(1., recovery)):
        raise ValueError('WF61_PULL_AGGREGATE_MISMATCH')
    return {'status': 'GSIM_SOURCE_PAID_REPLAY_VERIFIED',
            'actual_distinct_targets': len(ids), 'seconds_per_mob': mean,
            'paid_recovery_s': recovery, 'native_world_action_ack_verified': False,
            'checkpoint_certified': False}


def execute_source_replays(*, class_key: str, level: int, stage_path: Path,
                           max_wall_s: float, source_ir=None,
                           strict_l2_item_effects: bool = False,
                           source_identity: dict | None = None) -> dict:
    """Run fresh 1-, 2-, 100-mob horizons on one source build, each internally persistent."""
    stage, source_sha = load_source_stage(stage_path)
    # No substitute backend or synthetic score: import production evaluator.
    from src.v2.source_persistent_joint_finalists import (
        prepare_candidate, evaluate_persistent_candidate,
    )
    candidate = prepare_candidate(class_key=class_key, level=level, stage=stage,
                                  source_ir=source_ir,
                                  strict_l2_item_effects=strict_l2_item_effects)
    # Source IR defines which of the producer's three trace channels actually
    # exist on this actor. A Mage must not be required to invent energy.
    expected_resource_channels = frozenset(
        str(resource.id) for resource in candidate.ir.resources
        if (resource.owner_actor_id == candidate.ir.actor.id
            and str(resource.scope or 'actor') != 'target'
            and resource.initial_amount is not None
            and str(resource.id) in _TRACE_RESOURCE_CHANNELS)
    )
    report = {'status': 'NOT_YET_COMPLETE', 'engine': 'gsim',
              'native_world_action_ack_verified': False,
              'checkpoint_certified': False, 'process_gate_verdict': 'NOT_EVALUATED',
              'class_key': class_key, 'level': level,
              'source_stage_path': str(stage_path),
              'source_stage_sha256': source_sha,
              'source_identity': source_identity or {},
              'fresh_independent_horizons': list(COUNTS), 'runs': []}
    for count in COUNTS:
        try:
            actual = evaluate_persistent_candidate(
                candidate, level=level, mobs=count, trace_pulls=True,
                max_wall_s=max_wall_s, pack_size=1, settle_final_recovery=True,
            )
        except Exception as exc:
            # Preserve the real 1/2-mob results and pinned input identity when
            # a later source-backed horizon raises. The outer CLI handler
            # otherwise discards all preceding raw trace and provenance.
            report['status'] = 'EXECUTION_ERROR'
            report['runs'].append({
                'requested_mobs': count,
                'execution_error': {'status': 'EXECUTION_ERROR',
                                    'error_type': type(exc).__name__,
                                    'reason': str(exc)},
            })
            return report
        row = {'requested_mobs': count, 'actual_gsim_result': actual}
        report['runs'].append(row)
        try:
            row['verification'] = validate_real_replay(
                actual, count, expected_resource_channels=expected_resource_channels)
        except ValueError as exc:
            row['verification'] = {'status': 'NOT_YET_VERIFIED', 'reason': str(exc)}
            return report
    report['status'] = 'GSIM_ONLY_1_2_100_REPLAY_COMPLETE'
    return report



def execute_staged_source_replays(*, class_key: str, level: int, stage_path: Path,
                                  max_wall_s: float, ability_db: Path,
                                  observations: Path, control_observations: Path,
                                  build_as_of: str) -> dict:
    """Use the same observed-source SQLite overlay as existing WF357 live tests."""
    from src.game.data.forever.source_db_scope import ability_source_scope
    from src.game.data.forever.source_observed_rank_parity import ingest_observations
    from src.game.data.forever.registry import build_game_ir_slice
    from tools.wf321_ingest_control_observations import ingest as ingest_control

    source_identity = {
        'ability_db_sha256': sha256(ability_db.read_bytes()).hexdigest(),
        'observations_sha256': sha256(observations.read_bytes()).hexdigest(),
        'control_observations_sha256': sha256(control_observations.read_bytes()).hexdigest(),
        'build_as_of': build_as_of,
    }
    previous = os.environ.get('WOW_FOREVER_BUILD_AS_OF')
    try:
        os.environ['WOW_FOREVER_BUILD_AS_OF'] = build_as_of
        with TemporaryDirectory(prefix='wf61-source-') as tmp:
            scoped_db = Path(tmp) / 'source.sqlite'
            shutil.copy2(ability_db, scoped_db)
            ingest_observations(scoped_db, observations)
            ingest_control(scoped_db, control_observations)
            with ability_source_scope(scoped_db):
                ir = build_game_ir_slice(class_key=class_key, level=level,
                                         ability_db_path=scoped_db)
                return execute_source_replays(
                    class_key=class_key, level=level, stage_path=stage_path,
                    max_wall_s=max_wall_s, source_ir=ir,
                    strict_l2_item_effects=True, source_identity=source_identity)
    finally:
        if previous is None:
            os.environ.pop('WOW_FOREVER_BUILD_AS_OF', None)
        else:
            os.environ['WOW_FOREVER_BUILD_AS_OF'] = previous

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--class', dest='class_key', required=True)
    parser.add_argument('--level', type=int, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--max-wall-s', type=float, default=180.)
    parser.add_argument('--ability-db', type=Path)
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--control-observations', type=Path)
    parser.add_argument('--build-as-of', default='2026-10-13')
    args = parser.parse_args(argv)
    if not isfinite(args.max_wall_s) or args.max_wall_s <= 0:
        parser.error('--max-wall-s must be positive and finite')
    if args.ability_db is not None and (args.observations is None or args.control_observations is None):
        parser.error('--ability-db requires both source observation files')
    if args.ability_db is None and (args.observations is not None or args.control_observations is not None):
        parser.error('source observations require --ability-db')
    try:
        if args.ability_db is None:
            report = execute_source_replays(
                class_key=args.class_key, level=args.level, stage_path=args.stage,
                max_wall_s=args.max_wall_s)
        else:
            report = execute_staged_source_replays(
                class_key=args.class_key, level=args.level, stage_path=args.stage,
                max_wall_s=args.max_wall_s, ability_db=args.ability_db,
                observations=args.observations,
                control_observations=args.control_observations,
                build_as_of=args.build_as_of)
    except Exception as exc:
        report = {'status': 'EXECUTION_ERROR', 'error_type': type(exc).__name__,
                  'reason': str(exc), 'engine': 'gsim',
                  'native_world_action_ack_verified': False,
                  'checkpoint_certified': False}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(report['status'], args.out)
    return 0 if report['status'] == 'GSIM_ONLY_1_2_100_REPLAY_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())

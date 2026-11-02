#!/usr/bin/env python3
"""Real gsim 2D -> ONE pinned Go simulation -> native range receipt -> gsim tick.

Range-only bridge diagnostic. Neither native spell action identity nor applied
world-action ACK exists yet; never use this as P7 or 1/148 acceptance.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game.model import ActorDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
from src.game.runtime.go_native_spell_observations import NativeSpellObservationLedger
from src.game.runtime.go_native_target_spell_observations import NativeTargetSpellObservationLedger
from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier

PINNED_GO_REVISION = 'a667dce8492bd9fb94269a9f864289cb74006775'


def source_target_health_from_request(raw: bytes) -> float:
    """Read the target's Health stat from the actual pinned Go RaidSimRequest.

    The source Go stats.Stats enum maps Health to index 32. Do not replace
    this with the bridge's former arbitrary 10-million-HP diagnostic target.
    """
    try:
        targets = json.loads(raw)['encounter']['targets']
        if len(targets) != 1 or targets[0]['level'] != 63:
            raise ValueError('SOURCE_DPS_TARGET_NOT_SINGLE_LEVEL_63')
        health = targets[0]['stats'][32]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('SOURCE_TARGET_HEALTH_MISSING') from exc
    if type(health) not in (int, float) or not math.isfinite(health) or health <= 0:
        raise ValueError('SOURCE_TARGET_HEALTH_INVALID')
    return float(health)


def diagnostic_gsim_world(*, target_spawn_yards: float = 20., enemy_move_speed_yards_s: float = 5.,
                          target_health: float = 10_000_000.,
                          target_initial_health_fraction: float = 1.):
    """Real gsim moving pack, but NOT a source-verified L60 Druid build."""
    if (not math.isfinite(target_health) or target_health <= 0
            or not math.isfinite(target_initial_health_fraction)
            or not 0 < target_initial_health_fraction <= 1):
        raise ValueError('INVALID_SOURCE_WORLD_TARGET_HEALTH')
    actor = ActorState.from_ir(
        ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    runtime = CombatRuntime(
        actor=actor, target=TargetState.with_health('m0', target_health),
        other_targets=(TargetState.with_health('m1', target_health),),
        spatial_positions_yards={'m0': (0., 0.), 'm1': (target_spawn_yards, 0.)},
        enemy_move_speed_yards_s=enemy_move_speed_yards_s, melee_radius_yards=5.)
    # The actual gsim target owns starting HP. Native must consume it via
    # the first measured world ACK, not via a synthetic native-only counter.
    runtime.targets['m1'].health = target_health * target_initial_health_fraction
    runtime.engage_target('m1')
    runtime.select_target('m1')
    return runtime


def run(binary: Path, request: Path, *, ticks: int = 20, timeout_s: float = 15.,
        target_spawn_yards: float = 20., enemy_move_speed_yards_s: float = 5.,
        corrupt_ack: bool = False, target_health: float = 10_000_000.,
        target_initial_health_fraction: float = 1., pulls: int = 1,
        recovery_s: float = 0., source_target_health: bool = False) -> dict:
    # 1500 x 100 ms covers the saved 120 s +/- 15 s encounter horizon.
    # The native server independently limits sessions to 10000 world ticks.
    if (ticks < 2 or ticks > 1500 or timeout_s <= 0 or pulls not in (1, 2)
            or not math.isfinite(recovery_s) or recovery_s < 0 or recovery_s > 10):
        raise ValueError('INVALID_PROBE_LIMITS')
    binary, request = binary.resolve(), request.resolve()
    raw = request.read_bytes()
    request_sha = hashlib.sha256(raw).hexdigest()
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    if source_target_health:
        if target_health != 10_000_000.:
            raise ValueError('SOURCE_TARGET_HEALTH_OVERRIDE_CONFLICT')
        target_health = source_target_health_from_request(raw)
    runtime = diagnostic_gsim_world(target_spawn_yards=target_spawn_yards,
        enemy_move_speed_yards_s=enemy_move_speed_yards_s, target_health=target_health,
        target_initial_health_fraction=target_initial_health_fraction)
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    spell_ledger = NativeSpellObservationLedger()
    target_spell_ledger = NativeTargetSpellObservationLedger()
    world_applier = GsimNativeDamageWorldApplier(runtime)
    previous_ack_id = ''
    proc = subprocess.Popen([str(binary), '--request', str(request),
        '--source-revision', PINNED_GO_REVISION],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1)
    lines: queue.Queue[str] = queue.Queue()
    # Drain native stderr concurrently: a dead native process must reveal its
    # first actual Go error, not just an opaque stdout EOF. Bound memory use.
    native_stderr = deque(maxlen=60)

    def read_stderr():
        for line in proc.stderr:
            native_stderr.append(line.rstrip())

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    def native_failure_details() -> str:
        if proc.poll() is not None:
            stderr_thread.join(timeout=1)
        return f'exit={proc.poll()} stderr={chr(10).join(native_stderr)[-4096:]}'

    def read_lines():
        for line in proc.stdout:
            lines.put(line)
        lines.put('')

    thread = threading.Thread(target=read_lines, daemon=True)
    thread.start()
    observations = []
    killed_target_ids = []
    native_pid = None
    recovery_offset_s = 0.
    last_committed_world_health = None
    last_committed_target_id = None
    native_encounter_end_ns = None
    native_encounter_end_reached = False
    try:
        for idx in range(ticks):
            runtime.advance_to(idx / 10. + recovery_offset_s)
            tick = feed.next_tick()
            tick['previous_world_ack_id'] = previous_ack_id
            proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + '\n')
            proc.stdin.flush()
            try:
                raw_reply = lines.get(timeout=timeout_s)
            except queue.Empty as exc:
                raise RuntimeError('NATIVE_GO_RANGE_RECEIPT_TIMEOUT: ' + native_failure_details()) from exc
            if not raw_reply:
                raise RuntimeError('NATIVE_GO_SESSION_TERMINATED_BEFORE_RECEIPT: ' + native_failure_details())
            response = json.loads(raw_reply)
            if (response.get('type') != 'native_go_range_receipt'
                    or response.get('sequence') != tick['sequence']
                    or response.get('observed_input_world_sha256') != tick['world_sha256']
                    or response.get('native_source_revision') != PINNED_GO_REVISION
                    or response.get('native_request_sha256') != request_sha
                    or response.get('native_spell_action_ack') is not False
                    or response.get('checkpoint_certified') is not False
                    or type(response.get('native_process_id')) is not int
                    or response['native_process_id'] != proc.pid):
                raise RuntimeError('NATIVE_GO_RANGE_ENVELOPE_MISMATCH')
            # Native samples the saved encounter's duration/variation using
            # its pinned source RNG. The gsim controller must consume that
            # boundary instead of running a fixed 120s past native termination.
            reported_end = response.get('native_encounter_end_ns')
            if (type(reported_end) is not int or reported_end <= tick['native_clock_ns']
                    or (native_encounter_end_ns is not None and reported_end != native_encounter_end_ns)):
                raise RuntimeError('NATIVE_ENCOUNTER_END_RECEIPT_INVALID')
            native_encounter_end_ns = reported_end
            if native_pid is None:
                native_pid = response['native_process_id']
            elif native_pid != response['native_process_id']:
                raise RuntimeError('NATIVE_GO_PROCESS_RESTARTED')
            # A native action may produce source damage between world ticks,
            # but that damage is not world health until gsim ACKs it. The next
            # native decision must use the last committed world HP, not the
            # native engine's speculative unACKed damage accumulator.
            if (last_committed_world_health is not None
                    and tick['selected_target_id'] == last_committed_target_id):
                native_fraction = response.get('native_health_fraction')
                if (response.get('native_world_health_feedback_active') is not True
                        or type(native_fraction) not in (float, int)
                        or not math.isfinite(native_fraction)
                        or abs(native_fraction - last_committed_world_health) > 1e-8):
                    raise RuntimeError('NATIVE_WORLD_UNACKED_DAMAGE_CHANGED_DECISION_HEALTH')
            actor_state = response.get('native_actor_state')
            if (not isinstance(actor_state, dict)
                    or actor_state.get('native_clock_ns') != tick['native_clock_ns']
                    or not isinstance(actor_state.get('cooldown_ready_at_ns'), list)
                    or not isinstance(actor_state.get('active_auras'), list)):
                raise RuntimeError('NATIVE_GO_ACTOR_STATE_RECEIPT_INVALID')
            spell_deltas = spell_ledger.observe(response.get('native_spell_counters'), sequence=tick['sequence'])
            target_deltas = target_spell_ledger.observe(
                response.get('native_target_spell_counters'),
                sequence=tick['sequence'], gsim_target_id=tick['selected_target_id'])
            fields = feed.accept_range_receipt(response.get('native_range_receipt'))
            world_ack = world_applier.apply(tick, response)
            if corrupt_ack and idx == 0:
                # Negative control: real gsim has applied the source events,
                # but the native process must reject this forged before-hash.
                world_ack['world_before_sha256'] = '0' * 64
            proc.stdin.write(json.dumps(world_ack, sort_keys=True, allow_nan=False) + '\n')
            proc.stdin.flush()
            try:
                raw_confirmation = lines.get(timeout=timeout_s)
            except queue.Empty as exc:
                raise RuntimeError('NATIVE_GO_WORLD_ACK_CONFIRMATION_TIMEOUT: ' + native_failure_details()) from exc
            if not raw_confirmation:
                raise RuntimeError('NATIVE_GO_WORLD_ACK_CONFIRMATION_MISSING: ' + native_failure_details())
            confirmation = json.loads(raw_confirmation)
            if (confirmation.get('type') != 'native_go_world_ack_accepted'
                    or confirmation.get('sequence') != tick['sequence']
                    or confirmation.get('native_process_id') != proc.pid
                    or confirmation.get('observed_world_after_sha256') != world_ack['world_after_sha256']
                    or confirmation.get('checkpoint_certified') is not False
                    or type(confirmation.get('ack_id')) is not str
                    or len(confirmation['ack_id']) != 64
                    or confirmation.get('native_spell_action_ack') != bool(world_ack['applied_event_ids'])):
                raise RuntimeError('NATIVE_GO_WORLD_ACK_CONFIRMATION_FORGED_OR_WRONG')
            if not confirmation.get('native_world_health_applied'):
                raise RuntimeError('NATIVE_GO_WORLD_HEALTH_NOT_CONSUMED')
            actual_target = runtime.targets[tick['selected_target_id']]
            if abs(confirmation['native_remaining_health_fraction'] -
                   actual_target.health / actual_target.max_health) > 1e-8:
                raise RuntimeError('NATIVE_GO_HEALTH_FEEDBACK_MISMATCH')
            previous_ack_id = confirmation['ack_id']
            last_committed_world_health = confirmation['native_remaining_health_fraction']
            last_committed_target_id = tick['selected_target_id']
            observations.append({'world_tick': tick, 'native_range_receipt': response['native_range_receipt'],
                                 'native_spell_counters': response['native_spell_counters'],
                                 'native_spell_counter_deltas': spell_deltas,
                                 'native_target_spell_counters': response['native_target_spell_counters'],
                                 'native_target_spell_counter_deltas': target_deltas,
                                 'validated_range_only': fields,
                                 'native_damage_events': response['native_damage_events'],
                                 'native_actor_state': actor_state,
                                 'gsim_applied_world_ack': world_ack,
                                 'native_world_ack_confirmation': confirmation,
                                 'native_health_fraction_at_boundary': response['native_health_fraction'],
                                 'native_execute_phase_at_boundary': response['native_execute_phase'],
                                 'native_world_health_feedback_active_at_boundary': response['native_world_health_feedback_active']})
            # A lethal ACK ends this mob, not the retained native actor.
            # A second identical source mob may be selected without restarting
            # Go or resetting player resources/cooldowns/auras.
            if not actual_target.alive:
                killed_target_ids.append(actual_target.id)
                if len(killed_target_ids) == pulls:
                    break
                next_id = next((target_id for target_id, target in runtime.targets.items()
                                if target.alive), None)
                if next_id is None:
                    raise RuntimeError('NATIVE_GO_NEXT_WORLD_TARGET_MISSING')
                runtime.engage_target(next_id)
                runtime.select_target(next_id)
                world_applier.begin_next_world_target(next_id)
                target_spell_ledger.begin_next_world_target(actual_target.id, next_id)
                # This is paid wall-clock recovery in the real gsim controller;
                # the retained native scheduler advances through the same gap.
                recovery_offset_s += recovery_s
            # End the same retained session at the actual source-sampled
            # native encounter boundary, without submitting an illegal tick.
            # A sub-tick remainder (<100ms) is intentionally not simulated.
            next_tick_ns = round(((idx + 1) / 10. + recovery_offset_s) * 1e9)
            if next_tick_ns >= native_encounter_end_ns:
                native_encounter_end_reached = True
                break
        proc.stdin.close()
        if proc.wait(timeout=timeout_s) != 0:
            raise RuntimeError('NATIVE_GO_RANGE_SESSION_FAILED_ON_CLOSE: ' + native_failure_details())
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        stderr_thread.join(timeout=1)
        proc.stderr.close()
    return {'kind': 'real_gsim_2d_pinned_go_live_range_only_v1',
            'target_spawn_yards': target_spawn_yards,
            'enemy_move_speed_yards_s': enemy_move_speed_yards_s,
            'target_initial_health_fraction': target_initial_health_fraction,
            'native_spell_activity_observed': any(bool(x['native_spell_counter_deltas']) for x in observations),
            'status': 'NATIVE_GO_WORLD_DAMAGE_ACK_NOT_P7',
            'native_binary_sha256': binary_sha,
            'native_source_revision': PINNED_GO_REVISION,
            'native_request_sha256': request_sha,
            'native_process_id': native_pid,
            'native_encounter_end_ns': native_encounter_end_ns,
            'native_encounter_end_reached': native_encounter_end_reached,
            'killed_target_ids': killed_target_ids,
            'pulls_requested': pulls,
            'recovery_seconds_between_pulls': recovery_s,
            'observations': observations,
            'native_process_reused': True,
            'native_spell_counters_observed': all('native_spell_counters' in x for x in observations),
            'native_target_spell_counters_observed': all('native_target_spell_counters' in x for x in observations),
            'native_spell_metrics_are_cumulative_not_action_ack': True,
            'gsim_runtime_real': True,
            'native_spell_action_ack': any(bool(x['gsim_applied_world_ack']['applied_event_ids']) and
                                           x['native_world_ack_confirmation']['native_spell_action_ack']
                                           for x in observations),
            'checkpoint_certified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--expect-invalid-ack-rejected', action='store_true')
    parser.add_argument('--target-initial-health-fraction', type=float, default=1.)
    parser.add_argument('--ticks', type=int, default=20)
    parser.add_argument('--pulls', type=int, choices=(1, 2), default=1)
    parser.add_argument('--recovery-seconds', type=float, default=0.)
    args = parser.parse_args()
    if args.expect_invalid_ack_rejected:
        try:
            run(args.binary, args.request, ticks=args.ticks, corrupt_ack=True,
                target_initial_health_fraction=args.target_initial_health_fraction,
                pulls=args.pulls, recovery_s=args.recovery_seconds)
        except RuntimeError as exc:
            if 'WORLD_EFFECT_ACK_ID_OR_HASH_MISMATCH' not in str(exc):
                raise
            print('REAL_NATIVE_GO_REJECTED_FORGED_WORLD_ACK')
            return
        raise SystemExit('NATIVE_GO_ACCEPTED_FORGED_WORLD_ACK')
    result = run(args.binary, args.request, ticks=args.ticks,
        target_initial_health_fraction=args.target_initial_health_fraction,
        pulls=args.pulls, recovery_s=args.recovery_seconds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(f'{result["status"]}: {len(result["observations"])} ticks (NOT P7)')


if __name__ == '__main__':
    main()

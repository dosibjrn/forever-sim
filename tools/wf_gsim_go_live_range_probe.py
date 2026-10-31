#!/usr/bin/env python3
"""Real gsim 2D -> ONE pinned Go simulation -> native range receipt -> gsim tick.

Range-only bridge diagnostic. Neither native spell action identity nor applied
world-action ACK exists yet; never use this as P7 or 1/148 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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

PINNED_GO_REVISION = 'a667dce8492bd9fb94269a9f864289cb74006775'


def diagnostic_gsim_world():
    """Real gsim moving pack, but NOT a source-verified L60 Druid build."""
    actor = ActorState.from_ir(
        ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    runtime = CombatRuntime(
        actor=actor, target=TargetState.with_health('m0', 500),
        other_targets=(TargetState.with_health('m1', 500),),
        spatial_positions_yards={'m0': (0., 0.), 'm1': (20., 0.)},
        enemy_move_speed_yards_s=5., melee_radius_yards=5.)
    runtime.engage_target('m1')
    runtime.select_target('m1')
    return runtime


def run(binary: Path, request: Path, *, ticks: int = 20, timeout_s: float = 15.) -> dict:
    if ticks < 2 or ticks > 100 or timeout_s <= 0:
        raise ValueError('INVALID_PROBE_LIMITS')
    binary, request = binary.resolve(), request.resolve()
    raw = request.read_bytes()
    request_sha = hashlib.sha256(raw).hexdigest()
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    runtime = diagnostic_gsim_world()
    feed = GsimGoRangeFeed(runtime, native_player_index=0)
    proc = subprocess.Popen([str(binary), '--request', str(request),
        '--source-revision', PINNED_GO_REVISION],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1)
    lines: queue.Queue[str] = queue.Queue()

    def read_lines():
        for line in proc.stdout:
            lines.put(line)
        lines.put('')

    thread = threading.Thread(target=read_lines, daemon=True)
    thread.start()
    observations = []
    native_pid = None
    try:
        for idx in range(ticks):
            runtime.advance_to(idx / 10.)
            tick = feed.next_tick()
            proc.stdin.write(json.dumps(tick, sort_keys=True, allow_nan=False) + '\n')
            proc.stdin.flush()
            try:
                raw_reply = lines.get(timeout=timeout_s)
            except queue.Empty as exc:
                raise RuntimeError('NATIVE_GO_RANGE_RECEIPT_TIMEOUT') from exc
            if not raw_reply:
                raise RuntimeError('NATIVE_GO_SESSION_TERMINATED_BEFORE_RECEIPT')
            response = json.loads(raw_reply)
            if (response.get('type') != 'native_go_range_receipt'
                    or response.get('sequence') != tick['sequence']
                    or response.get('observed_input_world_sha256') != tick['world_sha256']
                    or response.get('native_source_revision') != PINNED_GO_REVISION
                    or response.get('native_request_sha256') != request_sha
                    or response.get('native_spell_action_ack') is not False
                    or response.get('checkpoint_certified') is not False
                    or type(response.get('native_process_id')) is not int
                    or response['native_process_id'] <= 0):
                raise RuntimeError('NATIVE_GO_RANGE_ENVELOPE_MISMATCH')
            if native_pid is None:
                native_pid = response['native_process_id']
            elif native_pid != response['native_process_id']:
                raise RuntimeError('NATIVE_GO_PROCESS_RESTARTED')
            fields = feed.accept_range_receipt(response.get('native_range_receipt'))
            observations.append({'world_tick': tick, 'native_range_receipt': response['native_range_receipt'],
                                 'validated_range_only': fields})
        proc.stdin.close()
        if proc.wait(timeout=timeout_s) != 0:
            raise RuntimeError('NATIVE_GO_RANGE_SESSION_FAILED_ON_CLOSE')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return {'kind': 'real_gsim_2d_pinned_go_live_range_only_v1',
            'status': 'RANGE_BIDIRECTIONAL_NOT_SPELL_ACTION_CAUSALITY',
            'native_binary_sha256': binary_sha,
            'native_source_revision': PINNED_GO_REVISION,
            'native_request_sha256': request_sha,
            'native_process_id': native_pid,
            'observations': observations,
            'native_process_reused': True,
            'gsim_runtime_real': True,
            'native_spell_action_ack': False,
            'checkpoint_certified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.binary, args.request)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(f'{result["status"]}: {len(result["observations"])} ticks (NOT P7)')


if __name__ == '__main__':
    main()

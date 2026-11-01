from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from src import state_manager as sm


class RuntimeReporter:
    """Own optimizer runtime status publication and heartbeat side effects.

    Search/orchestration code only calls ``update``; viewer snapshots, BEST
    enrichment, checkpoint mirroring and heartbeat history stay here.
    """

    def __init__(self, args, *, stop_event, active_checkpoint):
        self.args = args
        self.stop_event = stop_event
        self.active_checkpoint = active_checkpoint
        self.lock = threading.Lock()
        self.live = {
            'mode': 'optimizer', 'state': 'starting', 'pid': os.getpid(),
            'workers': args.workers, 'message': 'initializing',
            'started_at': time.time(), 'water_mode': None,
        }

    def _enrich(self, snapshot: dict) -> dict:
        mode = snapshot.get('water_mode') or 'buy_water'
        snapshot['best'] = sm.current_best_meta(mode)
        snapshot['best_by_water'] = {m: sm.current_best_meta(m) for m in sm.WATER_MODES}
        return snapshot

    def snapshot(self) -> dict:
        with self.lock:
            return self._enrich(dict(self.live))

    def _publish(self, snapshot: dict) -> None:
        sm.publish_status(snapshot)
        for mode in sm.WATER_MODES:
            sm.publish_viewer_snapshot(mode, snapshot)

    def update(self, **kwargs) -> dict:
        with self.lock:
            self.live.update(kwargs)
            snapshot = dict(self.live)
        self._enrich(snapshot)
        self._publish(snapshot)
        return snapshot

    def heartbeat_once(self) -> dict:
        snapshot = self.snapshot()
        cp = self.active_checkpoint.get('path')
        if cp and Path(cp).exists():
            try:
                sm.atomic_copy(Path(cp), sm.RUNTIME / 'optimizer.pkl')
            except Exception as exc:
                snapshot['heartbeat_copy_error'] = repr(exc)
        self._publish(snapshot)
        sm.heartbeat_snapshot(snapshot, keep=self.args.heartbeat_history)
        try:
            sm.make_chat_handoff()
        except Exception as exc:
            print(f'[heartbeat] chat handoff failed: {exc}', flush=True)
        return snapshot

    @staticmethod
    def _progress_text(snapshot: dict) -> str:
        if snapshot.get('validation_total'):
            return f" validation={snapshot.get('validation_done', 0)}/{snapshot.get('validation_total')}"
        return ''

    def heartbeat_loop(self) -> None:
        first = True
        while not self.stop_event.is_set():
            snapshot = self.heartbeat_once()
            if not first:
                elapsed = time.time() - snapshot.get('started_at', time.time())
                print(
                    f"[heartbeat] state={snapshot.get('state','?')} water={snapshot.get('water_mode','?')} "
                    f"exp={snapshot.get('experiment','?')} level={snapshot.get('level','—')}"
                    f"{self._progress_text(snapshot)} elapsed={elapsed/60:.1f}m | {snapshot.get('message','')}",
                    flush=True,
                )
            first = False
            self.stop_event.wait(max(5, min(60, self.args.heartbeat_seconds)))

    def start_thread(self):
        thread = threading.Thread(target=self.heartbeat_loop, name='heartbeat', daemon=True)
        thread.start()
        return thread

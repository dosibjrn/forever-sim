#!/usr/bin/env python3
"""Fail-closed port of the Rust end-of-pull event-queue preservation fix.

This edits the maintained Rust fork during the existing token-authorized
source-packaging workflow; it does not implement combat rules in Python.
The real two-target native session is a separate, still-required operation.
"""
from __future__ import annotations

import sys
from pathlib import Path

STEP = "    fn step(&mut self) -> bool {"
POP = """        let Some((time, handle, action)) = self.queue.pop() else {
            return false;
        };
"""
GUARD = """        // Preserve scheduled post-pull events for a continuing native session.
        // The existing one-shot iteration still resets the queue on its next run.
        if next > self.end_of_combat {
            return false;
        }
"""


def port_source(source: str) -> str:
    if source.count(STEP) != 1:
        raise ValueError("Rust Fight::step anchor missing or ambiguous")
    head, step_body = source.split(STEP, 1)
    if GUARD in step_body:
        # The patched guard must be IMMEDIATELY before the destructive pop.
        # A moved guard is unsafe even if the same two strings still occur.
        if (step_body.count(GUARD) != 1 or step_body.count(POP) != 1
                or step_body.count(GUARD + POP) != 1):
            raise ValueError("Rust queue guard present but not directly before pop")
        return source
    if step_body.count(POP) != 1:
        raise ValueError("Rust queued-action pop anchor missing or ambiguous")
    preceding = step_body.split(POP, 1)[0]
    if "let next = self.queue.peek_time()" not in preceding:
        raise ValueError("Rust queue ordering changed; inspect before porting")
    if "if time > self.end_of_combat" not in step_body.split(POP, 1)[1][:160]:
        raise ValueError("Rust end-of-combat behavior changed; inspect before porting")
    return head + STEP + step_body.replace(POP, GUARD + POP, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_pull_queue.py RUST_ENGINE_ROOT")
    source_file = Path(argv[1]) / "src/core/fight.rs"
    source = source_file.read_text()
    updated = port_source(source)
    if updated != source:
        source_file.write_text(updated)
        print("RUST_NATIVE_POST_PULL_QUEUE_GUARD_PORTED")
    else:
        print("RUST_NATIVE_POST_PULL_QUEUE_GUARD_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Focused non-engine regression for the Rust fork pull-boundary source port.

These prove only that the exact pinned scheduler seam is guarded. The separate
native 2-target actor/ACK/paid-recovery test is still required for #19.
"""
import unittest
from port_native_pull_queue import GUARD, POP, port_source

BASE = """impl Fight {
    fn step(&mut self) -> bool {
        let next = self.queue.peek_time().unwrap_or(NEVER_EXPIRES);
        let Some((time, handle, action)) = self.queue.pop() else {
            return false;
        };
        if time > self.end_of_combat {
            return false;
        }
        self.run_action(handle, action);
        true
    }
}
"""


class PullQueuePortTests(unittest.TestCase):
    def test_preserves_future_event_before_pop_and_is_idempotent(self):
        updated = port_source(BASE)
        self.assertIn(GUARD + POP, updated)
        self.assertEqual(updated.count(GUARD), 1)
        self.assertEqual(port_source(updated), updated)
        self.assertIn("if time > self.end_of_combat", updated)

    def test_fails_closed_when_step_pop_seam_changes(self):
        with self.assertRaisesRegex(ValueError, "queued-action pop anchor"):
            port_source(BASE.replace("self.queue.pop()", "self.queue.pop_ready()"))

    def test_fails_closed_when_combat_limit_changes(self):
        with self.assertRaisesRegex(ValueError, "end-of-combat behavior"):
            port_source(BASE.replace("if time > self.end_of_combat", "if time > self.deadline"))

    def test_fails_closed_without_a_single_native_step(self):
        with self.assertRaisesRegex(ValueError, "step anchor"):
            port_source(BASE.replace("fn step(", "fn next_step("))


if __name__ == "__main__":
    unittest.main()

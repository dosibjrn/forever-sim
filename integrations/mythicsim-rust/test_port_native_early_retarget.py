"""Fail-closed source-port checks; real Rust actor behavior runs in cargo CI."""
import unittest
from port_native_early_retarget import (
    HELPER, METHOD_MARKER, NEW_GUARD, OLD_GUARD, TEST, port_source,
)

SOURCE = (
    "impl<A> Fight<A> {\n" +
    METHOD_MARKER + " -> Result<(), &'static str> {\n" +
    OLD_GUARD +
    "        if world_bridge::enabled() {\n"
    "            world_bridge::begin_next_target(at_ns)?;\n"
    "        }\n"
    "        self.advance_to(at_ns);\n"
    "        Ok(())\n"
    "    }\n"
    "}\n"
    "mod tests {\n"
    "    #[test]\n"
    "    fn native_persistent_next_target_retains_actor_and_native_queue() {}\n"
    "}\n"
)


class EarlyRetargetPortTests(unittest.TestCase):
    def test_early_clock_is_live_only_and_persisted_once(self):
        patched = port_source(SOURCE)
        self.assertIn("if live_world { at_ns <= self.end_of_combat }", patched)
        self.assertIn("else { at_ns == self.end_of_combat }", patched)
        self.assertIn("world_bridge::begin_next_target(at_ns)?", patched)
        self.assertEqual(patched.count(HELPER), 1)
        self.assertEqual(patched.count(TEST), 1)
        self.assertEqual(port_source(patched), patched)

    def test_refuses_missing_native_source_bridge(self):
        with self.assertRaisesRegex(ValueError, "anchors missing"):
            port_source(SOURCE.replace("world_bridge::begin_next_target(at_ns)?", ""))

    def test_refuses_changed_clock_guard(self):
        with self.assertRaisesRegex(ValueError, "anchors missing"):
            port_source(SOURCE.replace("at_ns != self.end_of_combat",
                                       "at_ns > self.end_of_combat"))

    def test_refuses_partial_successor(self):
        with self.assertRaisesRegex(ValueError, "partially applied"):
            port_source(port_source(SOURCE).replace(TEST, "", 1))


if __name__ == "__main__":
    unittest.main()

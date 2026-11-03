"""Fail-closed source-port checks; real Rust actor behavior runs in cargo CI."""
import unittest
from port_native_early_retarget import (
    HELPER, METHOD_MARKER, NEW_GUARD, OLD_GUARD, TEST, port_source,
)
from port_native_persistent_target import FIGHT_TEST, replace_once

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

    def test_typed_rng_descendant_is_idempotent_and_still_fail_closed(self):
        patched = port_source(SOURCE)
        typed_rng = "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)"
        typed = patched.replace("DruidAgent::fight(&prepared)", typed_rng, 1)
        self.assertEqual(typed.count(TEST), 0)
        self.assertEqual(typed.count(TEST.replace("DruidAgent::fight(&prepared)", typed_rng, 1)), 1)
        self.assertEqual(port_source(typed), typed)

        broken = typed.replace(
            "assert!(fight.accepts_next_target_clock(early, early + 2_000_000, true));",
            "assert!(!fight.accepts_next_target_clock(early, early + 2_000_000, true));",
            1,
        )
        with self.assertRaisesRegex(ValueError, "partially applied"):
            port_source(broken)

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


    def test_base_persistent_port_recognizes_intact_early_clock_successor(self):
        # The original port inserts a test with trailing newlines stripped.
        # Early-clock inserts a second test between the module header and it.
        original = ("mod tests {\n"
                    "    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};\n\n"
                    + FIGHT_TEST.rstrip("\n"))
        marker = "    fn native_persistent_next_target_retains_actor_and_native_queue()"
        early = original.replace("    #[test]\n" + marker,
                                 TEST + "    #[test]\n" + marker)
        self.assertNotIn(original, early)
        self.assertEqual(replace_once(early, "", original, marker), early)
        # Never interpret a modified base actor/resource test as idempotent.
        broken = early.replace("let kept_mana =", "let fake_mana =", 1)
        with self.assertRaisesRegex(ValueError, "partial or ambiguous"):
            replace_once(broken, "", original, marker)

    def test_base_persistent_port_recognizes_typed_rng_early_clock_successor(self):
        # The selected fork pin already contains the typed-RNG descendant.
        # Its early-retarget and persistent-target tests must remain exact.
        typed_rng = "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)"
        typed_early_test = TEST.replace("DruidAgent::fight(&prepared)", typed_rng, 1)
        typed_fight_test = FIGHT_TEST.replace("DruidAgent::fight(&prepared)", typed_rng, 1).rstrip("\n")
        marker = "    fn native_persistent_next_target_retains_actor_and_native_queue()"
        early = ("mod tests {\n"
                 "    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};\n\n"
                 + typed_early_test + "    #[test]\n" + typed_fight_test)
        self.assertEqual(replace_once(early, "", FIGHT_TEST.rstrip("\n"), marker), early)

        # The method-level guard must also accept exactly this typed-RNG child.
        method_source = (METHOD_MARKER + HELPER + NEW_GUARD + typed_early_test)
        self.assertEqual(replace_once(
            method_source, "", "unused", "    pub(crate) fn begin_next_target(&mut self"
        ), method_source)

        # A changed child test must still fail closed.
        broken = early.replace("let kept_mana =", "let fake_mana =", 1)
        with self.assertRaisesRegex(ValueError, "partial or ambiguous"):
            replace_once(broken, "", FIGHT_TEST.rstrip("\n"), marker)


if __name__ == "__main__":
    unittest.main()

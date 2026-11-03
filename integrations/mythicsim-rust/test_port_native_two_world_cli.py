#!/usr/bin/env python3
"""Typed-RNG idempotence checks for the native two-world CLI source port."""
from __future__ import annotations

import unittest

import port_native_two_pull_cli as two_pull

from port_native_two_world_cli import (
    CLASSES_ANCHOR,
    CLASS_MARKER,
    CLASS_METHOD,
    CLI_ANCHOR,
    CLI_MARKER,
    CLI_METHOD,
    PREPARED_ANCHOR,
    PREPARED_MARKER,
    PREPARED_METHOD,
    TYPED_RNG_PORTS,
    insert,
)


class TypedRngTwoWorldPortTests(unittest.TestCase):
    def cases(self):
        return (
            (CLASSES_ANCHOR, CLASS_MARKER, CLASS_METHOD),
            (PREPARED_ANCHOR, PREPARED_MARKER, PREPARED_METHOD),
            (CLI_ANCHOR, CLI_MARKER, CLI_METHOD),
        )

    def test_exact_base_and_typed_rng_descendants_are_idempotent_without_anchor(self):
        for anchor, marker, replacement in self.cases():
            with self.subTest(marker=marker, descendant="base"):
                self.assertEqual(insert(replacement, anchor, marker, replacement), replacement)
            with self.subTest(marker=marker, descendant="typed-rng"):
                beginning, expected = TYPED_RNG_PORTS[marker]
                self.assertEqual(expected.count(beginning), 1)
                # The typed descendant replaces/consumes the original anchor.
                self.assertNotIn(anchor, expected)
                self.assertEqual(insert(expected, anchor, marker, replacement), expected)

    def test_modified_typed_rng_descendants_fail_closed(self):
        mutations = (
            ('"ClassDruid"', '"ClassDruidBroken"'),
            ("RUST_MULTI_WORLD_TARGET_COUNT_INVALID", "RUST_MULTI_WORLD_TARGET_COUNT_INVALID_BROKEN"),
            ("native-world-pulls requires --infile", "native-world-pulls requires another input"),
        )
        for (_, marker, replacement), (old, replacement_text) in zip(self.cases(), mutations):
            with self.subTest(marker=marker):
                _, expected = TYPED_RNG_PORTS[marker]
                broken = expected.replace(old, replacement_text, 1)
                self.assertNotEqual(broken, expected)
                with self.assertRaisesRegex(ValueError, "TYPED_RNG_DRIFT"):
                    insert(broken, "anchor-absent", marker, replacement)


    def test_two_pull_typed_prepared_gateway_composes_without_duplicate_anchor(self):
        source = two_pull.PREPARED_METHOD_TYPED + two_pull.PREPARED_INSERTION_ANCHOR
        self.assertEqual(two_pull.port_prepared(source), source)
        self.assertEqual(source.count(PREPARED_ANCHOR), 1)
        combined = insert(
            source, PREPARED_ANCHOR, PREPARED_MARKER, PREPARED_METHOD
        )
        self.assertEqual(combined.count(PREPARED_ANCHOR), 1)
        self.assertIn("pub fn native_two_world_targets(", combined)
        self.assertEqual(two_pull.port_prepared(combined), combined)

    def test_two_pull_untyped_gateway_inserts_once_and_remains_idempotent(self):
        source = two_pull.PREPARED_INSERTION_ANCHOR
        installed = two_pull.port_prepared(source)
        self.assertIn(two_pull.PREPARED_METHOD_UNTYPED, installed)
        self.assertEqual(installed.count(PREPARED_ANCHOR), 1)
        self.assertEqual(two_pull.port_prepared(installed), installed)

    def test_two_pull_typed_gateway_rejects_forged_callsite(self):
        broken = (
            two_pull.PREPARED_METHOD_TYPED.replace(
                two_pull.ENGINE_TYPED_CALL, two_pull.ENGINE_CALL_OLD, 1
            )
            + two_pull.PREPARED_INSERTION_ANCHOR
        )
        with self.assertRaisesRegex(ValueError, "typed prepared two-pull gateway drift"):
            two_pull.port_prepared(broken)


if __name__ == "__main__":
    unittest.main()

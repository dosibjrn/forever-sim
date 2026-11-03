#!/usr/bin/env python3
"""Typed-RNG idempotence checks for the native two-world CLI source port."""
from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Exact typed-RNG idempotence checks for the native two-world CLI source port."""
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

    def test_exact_typed_rng_descendants_are_idempotent(self):
        for anchor, marker, replacement in self.cases():
            with self.subTest(marker=marker):
                beginning, typed = TYPED_RNG_PORTS[marker]
                self.assertTrue(typed.startswith(beginning))
                source = typed + anchor
                self.assertEqual(insert(source, anchor, marker, replacement), source)

    def test_modified_typed_rng_descendants_fail_closed(self):
        mutations = (
            ('"ClassDruid"', '"ClassDruidBroken"'),
            ("RUST_MULTI_WORLD_TARGET_COUNT_INVALID",
             "RUST_MULTI_WORLD_TARGET_COUNT_INVALID_BROKEN"),
            ("native-world-pulls requires --infile",
             "native-world-pulls requires another input"),
        )
        for (anchor, marker, replacement), (old, new) in zip(self.cases(), mutations):
            with self.subTest(marker=marker):
                beginning, typed = TYPED_RNG_PORTS[marker]
                self.assertTrue(typed.startswith(beginning))
                broken = typed.replace(old, new, 1)
                self.assertNotEqual(broken, typed)
                with self.assertRaisesRegex(ValueError, "TYPED_RNG_DRIFT"):
                    insert(broken + anchor, anchor, marker, replacement)


if __name__ == "__main__":
    unittest.main()

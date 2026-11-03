#!/usr/bin/env python3
"""Typed-RNG idempotence checks for the native two-world CLI source port."""
from __future__ import annotations

import unittest

from port_native_two_world_cli import (
    CLASS_ANCHOR,
    CLASS_MARKER,
    CLASS_METHOD,
    CLI_ANCHOR,
    CLI_MARKER,
    CLI_METHOD,
    PREPARED_ANCHOR,
    PREPARED_MARKER,
    PREPARED_METHOD,
    insert,
    typed_rng_descendant,
)


class TypedRngTwoWorldPortTests(unittest.TestCase):
    def cases(self):
        return (
            (CLASS_ANCHOR, CLASS_MARKER, CLASS_METHOD),
            (PREPARED_ANCHOR, PREPARED_MARKER, PREPARED_METHOD),
            (CLI_ANCHOR, CLI_MARKER, CLI_METHOD),
        )

    def test_exact_typed_rng_descendants_are_idempotent(self):
        for anchor, marker, replacement in self.cases():
            with self.subTest(marker=marker):
                typed = typed_rng_descendant(marker, replacement)
                self.assertIsNotNone(typed)
                source = typed if anchor in typed else typed + anchor
                self.assertEqual(insert(source, anchor, marker, replacement), source)

    def test_modified_typed_rng_descendants_fail_closed(self):
        mutations = (
            ('"ClassDruid"', '"ClassDruidBroken"'),
            ("RUST_MULTI_WORLD_TARGET_COUNT_INVALID", "RUST_MULTI_WORLD_TARGET_COUNT_INVALID_BROKEN"),
            ("native-world-pulls requires --infile", "native-world-pulls requires another input"),
        )
        for (anchor, marker, replacement), (old, replacement_text) in zip(self.cases(), mutations):
            with self.subTest(marker=marker):
                typed = typed_rng_descendant(marker, replacement)
                self.assertIsNotNone(typed)
                broken = typed.replace(old, replacement_text, 1)
                self.assertNotEqual(broken, typed)
                source = broken if anchor in broken else broken + anchor
                with self.assertRaises(ValueError):
                    insert(source, anchor, marker, replacement)


if __name__ == "__main__":
    unittest.main()

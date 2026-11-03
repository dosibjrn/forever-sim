#!/usr/bin/env python3
"""Fail-closed, idempotent guards for the native talent-layout API source port."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

PORT_PATH = Path(__file__).resolve().parent / "port_native_talent_layout_api.py"
spec = importlib.util.spec_from_file_location("native_talent_layout_api_port", PORT_PATH)
port = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(port)


class NativeTalentLayoutApiPortTest(unittest.TestCase):
    def test_all_source_anchors_apply_once_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, patches in port.PATH_PATCHES.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "\n".join(old for old, _, _ in patches) + "\n",
                    encoding="utf-8",
                )

            self.assertEqual(port.main([directory]), 0)
            first = {relative: (root / relative).read_bytes() for relative in port.PATHS}
            self.assertEqual(port.main([directory]), 0)
            second = {relative: (root / relative).read_bytes() for relative in port.PATHS}
            self.assertEqual(first, second)

            prepare = (root / "src/classes/druid/prepare.rs").read_text(encoding="utf-8")
            library = (root / "src/lib.rs").read_text(encoding="utf-8")
            main = (root / "src/main.rs").read_text(encoding="utf-8")
            self.assertIn('"max_ranks": talent.max_ranks', prepare)
            self.assertIn('"in_proto": talent.in_proto', prepare)
            self.assertIn("pub fn forever_druid_talent_layout()", library)
            self.assertIn("druid_talent_layout_api_tests", library)
            self.assertFalse(library.endswith("\n\n"))
            self.assertIn('args == ["talent-layout", "--class", "druid"]', main)
            self.assertIn("forever-engine talent-layout --class druid", main)

    def test_missing_native_anchor_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
            port.port_text("src/classes/druid/prepare.rs", "unrelated source")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused idempotence and anchor-drift tests for the Druid layout source port."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from port_native_druid_talent_layout_export import PortError, apply_port


LIB_ANCHOR = (
    "pub use prepare::{\n"
    "    prepare, prepare_json, prepare_json_with, PrepareError, Refusal as PrepareRefusal, Rules,\n"
    "};"
)


class NativeDruidTalentLayoutPortTest(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        (root / "src/classes/druid").mkdir(parents=True)
        (root / "src/classes/druid/prepare.rs").write_text(
            "pub(crate) const FOREVER_TREES: [&[LayoutTalent]; 3] = [];\n"
            "/// Which of Go's three registered Druid specs the player is.\n"
            "pub(crate) fn spec() {}\n",
            encoding="utf-8",
        )
        (root / "src/lib.rs").parent.mkdir(parents=True, exist_ok=True)
        (root / "src/lib.rs").write_text(LIB_ANCHOR + "\n", encoding="utf-8")
        (root / "src/main.rs").write_text(
            "use forever_engine::{\n"
            "    contracts::prepared_v2::PreparedV2,\n"
            "};\n"
            'println!("usage\\nforever-engine version");\n'
            '    if args[0] == "native-world-pulls" {\n',
            encoding="utf-8",
        )

    def test_patch_is_idempotent_and_limited_to_native_export(self):
        with tempfile.TemporaryDirectory(prefix="native-druid-layout-port-") as tmp:
            root = Path(tmp)
            self._fixture(root)
            changed = apply_port(root)
            self.assertTrue(changed)
            files = (
                root / "src/classes/druid/prepare.rs",
                root / "src/lib.rs",
                root / "src/main.rs",
            )
            first = {path: path.read_text(encoding="utf-8") for path in files}
            self.assertIn("native_talent_layout_json", first[files[0]])
            self.assertIn("druid_talent_layout_json", first[files[1]])
            self.assertIn('args[0] == "talent-layout"', first[files[2]])
            self.assertIn("talent-layout --class druid", first[files[2]])
            self.assertFalse(apply_port(root))
            second = {path: path.read_text(encoding="utf-8") for path in files}
            self.assertEqual(first, second)

    def test_source_drift_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="native-druid-layout-drift-") as tmp:
            root = Path(tmp)
            self._fixture(root)
            path = root / "src/classes/druid/prepare.rs"
            path.write_text("pub(crate) fn unrelated() {}\n", encoding="utf-8")
            with self.assertRaises(PortError):
                apply_port(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Ensure Mage mechanics tests remain discoverable and are moved byte-for-byte."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
MAGE = ROOT / "tests" / "mechanics" / "mage"
MOVED = (
    "test_ice_barrier.py",
    "test_ice_lance_all_spec_selection_v0114622.py",
    "test_ice_lance_cumulative_selection_v0114723.py",
    "test_ice_lance_selection_v0114618.py",
    "test_frostbite_shatter_pipeline.py",
    "test_forever_mage_frozen_ice_lance.py",
    "test_mage_periodic_crit_v0114713.py",
)


class MageMechanicsLayout(unittest.TestCase):
    def test_all_existing_modules_moved_into_one_group(self):
        for name in MOVED:
            with self.subTest(test_module=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                p = MAGE / name
                self.assertTrue(p.is_file())
                tree = ast.parse(p.read_text(), filename=str(p))
                self.assertTrue(any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("test_") for n in ast.walk(tree)
                ))
                self.assertNotIn("from tests.", p.read_text())
                self.assertNotIn("__file__", p.read_text())

    def test_regular_pytest_collection_includes_mechanics_group(self):
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", ini)
        self.assertNotIn("norecursedirs = mechanics", ini)
        self.assertIn("norecursedirs = release", ini)


if __name__ == "__main__":
    unittest.main()

"""Verify the generic search module relocation without importing simulator code."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
SEARCH = ROOT / "tests" / "generic" / "search"
MOVED = (
    "test_generic_search_kernel_v0114867.py",
    "test_generic_talent_policy_search_g19.py",
    "test_generic_gear_stat_sensitivity_g20.py",
    "test_optimizer_fixed_point_g21.py",
    "test_generic_level_frontier_g22.py",
    "test_generic_mode_g23.py",
    "test_generic_cross_mode_policy_g30.py",
)


class GenericSearchLayout(unittest.TestCase):
    def test_original_modules_moved_and_parse(self):
        for name in MOVED:
            with self.subTest(module=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = SEARCH / name
                self.assertTrue(path.is_file())
                code = path.read_text(encoding="utf-8")
                parsed = ast.parse(code, filename=str(path))
                self.assertTrue(any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")
                    for node in ast.walk(parsed)
                ))
                self.assertNotIn("Path(__file__)", code)
                self.assertNotIn("from tests.", code)

    def test_default_pytest_collection_remains_enabled(self):
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("pythonpath = .", ini)
        self.assertIn("testpaths = tests", ini)
        self.assertIn("norecursedirs = release", ini)
        self.assertNotIn("norecursedirs = generic", ini)

    def test_current_workflows_do_not_reintroduce_legacy_generic_glob(self):
        # The private layout-only workflows were deliberately not migrated.
        # Guard the original broad-trigger concern against actual live files.
        workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertTrue(workflows)
        for path in workflows:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("'tests/test_generic_*.py'", source, path.name)


if __name__ == "__main__":
    unittest.main()

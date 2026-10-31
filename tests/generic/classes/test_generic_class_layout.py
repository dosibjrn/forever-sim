"""Source-preserving generic class-adapter test suite layout contract."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
CLASSES = ROOT / "tests" / "generic" / "classes"
MOVED = (
    "test_generic_bear_policy_g29.py",
    "test_generic_druid_closure_g33.py",
    "test_generic_druid_routes_g32.py",
    "test_generic_hunter_pet_g35.py",
    "test_generic_mage_g45.py",
    "test_generic_mage_g46.py",
    "test_generic_mage_g46b.py",
    "test_generic_mage_g46c.py",
    "test_generic_mage_g46d.py",
    "test_generic_priest_g40.py",
    "test_generic_rogue_g38.py",
    "test_generic_shaman_wand_g41.py",
    "test_generic_warlock_g43.py",
    "test_generic_warlock_g44.py",
    "test_generic_warrior_g37.py",
)


class GenericClassLayout(unittest.TestCase):
    def test_original_class_modules_relocated(self):
        for name in MOVED:
            with self.subTest(module=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = CLASSES / name
                self.assertTrue(path.is_file())
                source = path.read_text()
                nodes = ast.parse(source, filename=str(path))
                self.assertTrue(any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_")
                    for node in ast.walk(nodes)
                ))
                self.assertNotIn("__file__", source)
                self.assertNotIn("from tests.", source)

    def test_pytest_discovery_includes_class_adapters(self):
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", ini)
        self.assertIn("norecursedirs = release", ini)
        self.assertNotIn("norecursedirs = generic", ini)
        workflow = (ROOT / ".github/workflows/generic-class-test-layout.yml").read_text()
        self.assertIn("--collect-only -q tests/generic/classes", workflow)

    def test_referenced_source_paths_stay_at_repo_root(self):
        for path in ("src/game/runtime/simulator.py", "src/game/policy.py",
                     "data/forever/catalogue/items_2026-09-29.sqlite"):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).exists())


if __name__ == "__main__":
    unittest.main()

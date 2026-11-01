"""Layout-only regression contract for the moved Paladin mechanics tests."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
PALADIN = ROOT / "tests" / "mechanics" / "paladin"
MOVED = (
    "test_paladin_analytic_gearing_v01125.py",
    "test_paladin_base_mana_source_v011464.py",
    "test_paladin_fury_absorb_v011466.py",
    "test_paladin_real_item_pool_v01132.py",
    "test_paladin_slot_field_v01128.py",
    "test_paladin_source_coefficients_v011465.py",
    "test_paladin_source_fidelity_v011463.py",
    "test_paladin_spell_modifiers.py",
    "test_paladin_sqlite_runtime_v0114843.py",
    "test_paladin_weapon_budget_v01148114.py",
)


class PaladinMechanicsLayout(unittest.TestCase):
    def test_paladin_modules_moved_without_stale_files(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = PALADIN / name
                self.assertTrue(path.is_file())
                source = path.read_text()
                nodes = ast.parse(source, filename=str(path))
                self.assertTrue(any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("test_") for n in ast.walk(nodes)
                ))
                self.assertNotIn("__file__", source)
                self.assertNotIn("from tests.", source)

    def test_pytest_collection_contract(self):
        config = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", config)
        self.assertIn("norecursedirs = release", config)
        self.assertNotIn("norecursedirs = mechanics", config)

    def test_targeted_ci_workflow_uses_new_path(self):
        workflow = (ROOT / ".github/workflows/paladin-mechanics-test-layout.yml").read_text()
        self.assertIn("tests/mechanics/paladin", workflow)
        self.assertIn("--collect-only", workflow)


if __name__ == "__main__":
    unittest.main()

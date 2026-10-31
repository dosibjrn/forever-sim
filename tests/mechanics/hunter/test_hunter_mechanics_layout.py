"""Repository layout contract for the Hunter mechanics tests (not gameplay PASS)."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
HUNTER = ROOT / "tests" / "mechanics" / "hunter"
MOVED = (
    "test_forever_hunter_bm_post20_v0114885.py",
    "test_forever_hunter_fidelity_v0114860.py",
    "test_forever_hunter_fixed_point_v0114863.py",
    "test_forever_hunter_items_v0114861.py",
    "test_forever_hunter_mm_post20_v0114886.py",
    "test_forever_hunter_pet_families_v0114892.py",
    "test_forever_hunter_pet_focus_v0114888.py",
    "test_forever_hunter_post20_v0114878.py",
    "test_forever_hunter_post20_v0114879.py",
    "test_forever_hunter_summon_hawk_v0114893.py",
    "test_forever_hunter_survival_melee_trap_v0114894.py",
    "test_forever_hunter_survival_post20_v0114887.py",
    "test_forever_hunter_v0114858.py",
    "test_hunter_l21_l40_closure_v0114895.py",
)


class HunterMechanicsLayout(unittest.TestCase):
    def test_all_modules_relocated_and_syntactically_valid(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = HUNTER / name
                self.assertTrue(path.is_file())
                source = path.read_text()
                nodes = ast.parse(source, filename=str(path))
                self.assertTrue(any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("test_") for n in ast.walk(nodes)
                ))
                self.assertNotIn("__file__", source)
                self.assertNotIn("from tests.", source)

    def test_normal_discovery_includes_hunter_but_excludes_release(self):
        config = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", config)
        self.assertIn("norecursedirs = release", config)
        self.assertNotIn("norecursedirs = mechanics", config)

    def test_ci_collection_contract_present(self):
        yml = (ROOT / ".github" / "workflows" / "hunter-mechanics-test-layout.yml").read_text()
        self.assertIn("tests/mechanics/hunter", yml)
        self.assertIn("--collect-only", yml)


if __name__ == "__main__":
    unittest.main()

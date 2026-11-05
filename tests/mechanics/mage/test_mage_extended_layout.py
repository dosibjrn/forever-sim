"""Layout contract for second batch of source-preserving Mage tests."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
MAGE = ROOT / "tests" / "mechanics" / "mage"
MOVED = (
    "test_forever_mage_engine_modularity_v011468.py",
    "test_forever_mage_real_gear_runtime.py",
    "test_forever_mage_rotation_fidelity_v01143.py",
    "test_mage_blizzard_aoe_optin_v0114876.py",
    "test_mage_class_model_generic_search_v0114868.py",
    "test_mage_contact_pushback_v0114873.py",
    "test_mage_event_sample_authority_v0114877.py",
    "test_mage_listener_route_output.py",
    "test_mage_per_level_fixed_point_v0114849.py",
    "test_mage_real_gear_catalogue_v01130.py",
    "test_mage_root_leeway_profile_v0114619.py",
    "test_mage_server_profile_v0114612.py",
    "test_mage_wand_fidelity_v0114873.py",
)


class MageExtendedLayout(unittest.TestCase):
    def test_source_preserving_files_are_in_mage_group(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                p = MAGE / name
                self.assertTrue(p.is_file())
                source = p.read_text()
                nodes = ast.parse(source, filename=str(p))
                self.assertTrue(any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("test_") for n in ast.walk(nodes)
                ))
                self.assertNotIn("from tests.", source)
                self.assertNotIn("Path(__file__).resolve()", source)

    def test_current_ci_checks_mage_layout_and_pytest_discovery(self):
        workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text()
        self.assertIn("tests/mechanics/mage/test_mage_extended_layout.py", workflow)
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", ini)
        self.assertNotIn("norecursedirs = mechanics", ini)


if __name__ == "__main__":
    unittest.main()

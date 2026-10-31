"""Source-preserving generic combat runtime test group structure contract."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "tests" / "generic" / "runtime"
MOVED = (
    "test_generic_auto_attack_g24.py",
    "test_generic_combo_points_g26.py",
    "test_generic_energy_g25.py",
    "test_generic_event_runtime_g07.py",
    "test_generic_event_trigger_g31.py",
    "test_generic_heal_recovery_g12.py",
    "test_generic_incoming_mitigation_g28.py",
    "test_generic_rage_g27.py",
    "test_generic_timed_summon_g36.py",
    "test_generic_multi_actor_g34.py",
    "test_generic_totem_emitter_g42.py",
    "test_generic_talent_modifier_g13.py",
)


class GenericRuntimeLayout(unittest.TestCase):
    def test_all_original_test_modules_moved_without_source_rewrite(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                path = RUNTIME / name
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

    def test_default_test_collection_still_includes_this_group(self):
        config = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", config)
        self.assertIn("norecursedirs = release", config)
        self.assertNotIn("norecursedirs = generic", config)
        self.assertIn("--collect-only -q tests/generic/runtime",
            (ROOT / ".github/workflows/generic-runtime-test-layout.yml").read_text())

    def test_source_paths_referenced_from_repo_root_are_not_moved(self):
        self.assertTrue((ROOT / "src/game/runtime/simulator.py").is_file())
        self.assertTrue((ROOT / "src/game/runtime/state.py").is_file())
        self.assertTrue((ROOT / "src/game/policy.py").is_file())


if __name__ == "__main__":
    unittest.main()

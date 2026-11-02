"""Verify maintenance regression modules moved without breaking their CLI consumers."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE = ROOT / "tests" / "maintenance"
MODULES = (
    "test_root_launcher_relocation.py",
    "test_root_launcher_phase2b.py",
    "test_release_suite_layout.py",
    "test_sqlite_sidecar_git_hygiene.py",
)

class MaintenanceTestLayout(unittest.TestCase):
    def test_moved_modules_only_in_maintenance_directory(self):
        for name in MODULES:
            with self.subTest(module=name):
                old = ROOT / "tests" / name
                new = MAINTENANCE / name
                self.assertFalse(old.exists(), f"stale test path: {old}")
                self.assertTrue(new.is_file(), f"missing moved test: {new}")
                source = new.read_text()
                self.assertIn("ROOT = Path(__file__).resolve().parents[2]", source)
                ast.parse(source, filename=str(new))

    def test_current_ci_does_not_reference_old_test_locations(self):
        workflows = ROOT / ".github" / "workflows"
        for workflow in workflows.glob("*.yml"):
            text = workflow.read_text()
            for name in MODULES:
                with self.subTest(workflow=workflow.name, module=name):
                    self.assertNotIn(f"tests/{name}", text)

    def test_default_pytest_collection_still_includes_maintenance(self):
        config = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", config)
        self.assertIn("norecursedirs = release", config)
        self.assertNotIn("norecursedirs = maintenance", config)
        self.assertTrue((ROOT / "tests/release").is_dir())


if __name__ == "__main__":
    unittest.main()

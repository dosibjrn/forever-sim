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
    "test_manual_exact_pr_head_workflow.py",
    "test_wf_coverage_sample_wrappers.py",
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

    def test_wf243_heldout_fixture_lives_in_test_fixtures(self):
        old = ROOT / "fixtures" / "wf243_heldout_feral_l20.json"
        new = ROOT / "tests" / "fixtures" / "wf243_heldout_feral_l20.json"
        self.assertFalse(old.exists(), f"stale root-level fixture: {old}")
        self.assertTrue(new.is_file(), f"missing immutable test fixture: {new}")
        for consumer in (
            ROOT / "tools" / "wf243_joint_multi_pull_replay.py",
            ROOT / "tests" / "test_wf243_source_joint_repeated_pulls.py",
        ):
            source = consumer.read_text()
            self.assertIn("tests/fixtures/wf243_heldout_feral_l20.json", source)
            self.assertNotIn(
                "fixtures/wf243_heldout_feral_l20.json",
                source.replace("tests/fixtures/wf243_heldout_feral_l20.json", ""),
            )

    def test_p1_policy_has_one_static_config_home(self):
        old = ROOT / "gate_config" / "p1_scenario_applicability_v1.json"
        new = ROOT / "config" / "gates" / "p1_scenario_applicability_v1.json"
        self.assertFalse(old.exists(), f"stale policy location: {old}")
        self.assertTrue(new.is_file(), f"missing scenario policy: {new}")
        workflow = (ROOT / ".github" / "workflows"
                    / "p1-native-validator-contract.yml").read_text()
        self.assertIn("config/gates/p1_scenario_applicability_v1.json", workflow)
        self.assertNotIn("gate_config/", workflow)
        for consumer in (
            ROOT / "tools" / "p1_native_source_inventory.py",
            ROOT / "tools" / "wf_gate_p1_live.py",
        ):
            content = consumer.read_text()
            self.assertIn("p1_scenario_applicability_v1.json", content)
            self.assertNotIn("gate_config", content)

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

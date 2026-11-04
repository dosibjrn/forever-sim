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
    "test_import_feral_p7_archives.py",
    "test_audit_feral_p7_holdout.py",
    "test_recovered_feral_p7_raw.py",
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

    def test_source_capture_and_audit_regressions_are_grouped(self):
        """Preserve direct-CLI repo root and fast-suite entry after relocation."""
        names = (
            "test_wowhead_capture_i5prep_v0114830.py",
            "test_wowhead_capture_entrypoint_v0114831.py",
            "test_wowhead_capture_import_v0114837.py",
            "test_wowhead_abilities_capture_g39.py",
        )
        target = ROOT / "tests" / "integration" / "source"
        for name in names:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                moved = target / name
                self.assertTrue(moved.is_file(), f"missing source integration test: {moved}")
                ast.parse(moved.read_text(encoding="utf-8"), filename=str(moved))
        for name in ("test_wowhead_capture_entrypoint_v0114831.py",):
            source = (target / name).read_text(encoding="utf-8")
            self.assertIn("Path(__file__).resolve().parents[3]", source)
        from tools.validate_fast import TESTS
        self.assertIn(
            "tests/integration/source/test_wowhead_capture_i5prep_v0114830.py", TESTS
        )
        self.assertNotIn("tests/test_wowhead_capture_i5prep_v0114830.py", TESTS)

    def test_obsolete_nine_class_acquisition_audit_has_no_live_entrypoint(self):
        """The retired trainer/learned-spell audit cannot gate production."""
        self.assertFalse((ROOT / "tools/audit_source_acquisition_gate.py").exists())
        self.assertFalse((ROOT / "tests/integration/source/test_audit_source_acquisition_cli.py").exists())


    def test_wf243_heldout_fixture_lives_in_test_fixtures(self):
        old = ROOT / "fixtures" / "wf243_heldout_feral_l20.json"
        new = ROOT / "tests" / "fixtures" / "wf243_heldout_feral_l20.json"
        self.assertFalse(old.exists(), f"stale root-level fixture: {old}")
        self.assertTrue(new.is_file(), f"missing immutable test fixture: {new}")
        self.assertFalse((ROOT / "tools" / "wf243_joint_multi_pull_replay.py").exists())
        source_module = (ROOT / "src" / "v2" / "source_multi_pull_joint.py").read_text()
        self.assertIn("def policy_from_record(", source_module)
        policy_consumers = (
            ROOT / "tools" / "wf282_source_role_heldout_benchmark.py",
            ROOT / "tools" / "wf298_druid_l20_verified_delta.py",
            ROOT / "tests" / "test_wf243_source_joint_repeated_pulls.py",
            ROOT / "tests" / "test_wf245_policy_frontier.py",
        )
        for consumer in policy_consumers:
            source = consumer.read_text()
            self.assertIn("from src.v2.source_multi_pull_joint import policy_from_record", source)
        fixture_consumers = (
            ROOT / "tools" / "wf282_source_role_heldout_benchmark.py",
            ROOT / "tools" / "wf298_druid_l20_verified_delta.py",
            ROOT / "tests" / "test_wf243_source_joint_repeated_pulls.py",
            ROOT / "tests" / "test_wf245_policy_frontier.py",
        )
        for consumer in fixture_consumers:
            source = consumer.read_text()
            self.assertIn("tests/fixtures/wf243_heldout_feral_l20.json", source)
            self.assertNotIn(
                "fixtures/wf243_heldout_feral_l20.json",
                source.replace("tests/fixtures/wf243_heldout_feral_l20.json", ""),
            )

    def test_retired_p1_gate_and_native_diagnostic_stack_is_gone(self):
        """P1 has no active acceptance runner or separate native diagnostic stack."""
        for relative in (
            "tools/wf_gate_p1_live.py",
            "tools/wf_p1_native_effects.py",
            "src/engine_client/native_p1_effect_probe.py",
            "config/gates/p1_scenario_applicability_v1.json",
            ".github/workflows/p1-native-validator-contract.yml",
            "tests/test_wf466_p1_live.py",
            "tests/test_wf469_p1_alignment.py",
            "tests/test_wf470_p1_scope.py",
            "tests/test_wf472_p1_gate_nonimpact.py",
            "tests/gates/test_wf_p1_native_blackbox.py",
            "integrations/mythicsim-rust/tests/test_native_p1_effect_probe.py",
        ):
            self.assertFalse((ROOT / relative).exists(), f"retired P1 path remains: {relative}")

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


    def test_source_profile_contract_is_grouped_and_manually_runnable(self):
        """Retain the shared source-profile helper regression; P1/P2 acceptance tests are retired."""
        names = (
            "test_wf35_product_spec_profile_contract.py",
        )
        workflow = (ROOT / ".github/workflows/manual-exact-pr-head.yml").read_text()
        for name in names:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                target = ROOT / "tests" / "gates" / name
                self.assertTrue(target.is_file())
                ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
                self.assertIn(f"tests/gates/{name}", workflow)
                self.assertNotIn(f"tests/{name}", workflow)
        for retired in (
            "test_wf34_acquisition_snapshot_binding.py",
            "test_wf34_p1_acquisition_ledger_fail_closed.py",
            "test_wf34_p1_client_acquisition_proof.py",
        ):
            self.assertFalse((ROOT / "tests/gates" / retired).exists())
            self.assertNotIn(retired, workflow)
        p2 = (ROOT / "tests/gates/test_wf35_product_spec_profile_contract.py").read_text()
        self.assertIn("ROOT = Path(__file__).resolve().parents[2]", p2)



    def test_maintenance_workflow_collects_every_module(self):
        """Adding a maintenance test must not require manual CI allowlist edits."""
        workflow = (ROOT / ".github/workflows/maintenance-evidence-tests.yml").read_text()
        command = workflow.split("run: >-", 1)[-1]
        self.assertIn("python -m pytest -q", command)
        self.assertIn("          tests/maintenance\n", command)
        self.assertNotIn("tests/maintenance/test_", command)
        # The cross-directory targeted contracts are deliberately kept.
        for selected in (
            "tests/test_prio_discrete_stat_sensitivity.py",
            "tests/test_wf380_legacy_bonus_talent_budget.py",
            "tests/mechanics/druid/test_druid_mechanics_layout.py",
            "tests/mechanics/hunter/test_hunter_mechanics_layout.py",
            "tests/mechanics/mage/test_mage_extended_layout.py",
            "tests/mechanics/paladin/test_paladin_mechanics_layout.py",
        ):
            self.assertIn(selected, command)


if __name__ == "__main__":
    unittest.main()

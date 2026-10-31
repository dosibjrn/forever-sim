"""Guard exact Druid-test directory membership and normal pytest discovery."""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[3]
DRUID = ROOT / "tests" / "mechanics" / "druid"
MOVED = (
    "test_druid_70170_schema_v0114890.py",
    "test_druid_balance_mana_weights_v0114854.py",
    "test_druid_bear_closure_v0114897.py",
    "test_druid_bear_recovery_v0114857.py",
    "test_druid_berserk_v0114721.py",
    "test_druid_blood_frenzy_v0114719.py",
    "test_druid_cat_closure_v0114896.py",
    "test_druid_cat_swipe_v0114716.py",
    "test_druid_catalogue_i5_v0114838.py",
    "test_druid_clearcasting_level_gate_v011481002.py",
    "test_druid_closure_v0114899.py",
    "test_druid_defense_avoidance_v0114812.py",
    "test_druid_feral_profile_publication_v0114862.py",
    "test_druid_incoming_rage_v0114615.py",
    "test_druid_incoming_rage_v011469.py",
    "test_druid_incoming_rage_v01148113.py",
    "test_druid_independent_validator_v0114620.py",
    "test_druid_lacerate_v0114718.py",
    "test_druid_natural_reaction_v0114714.py",
    "test_druid_per_level_fixed_point_v0114848.py",
    "test_druid_primal_bite_v0114613.py",
    "test_druid_reference_builds_v0114883.py",
    "test_druid_rejuvenation_bear_recovery_v0114864.py",
    "test_druid_shared_form_recovery_cycle_v0114898.py",
    "test_druid_spell_modifiers.py",
    "test_druid_thick_hide_v0114715.py",
    "test_forever_druid_weapon_v0114614.py",
)


class DruidMechanicsLayout(unittest.TestCase):
    def test_existing_modules_moved_without_stale_duplicates(self):
        for name in MOVED:
            with self.subTest(name=name):
                self.assertFalse((ROOT / "tests" / name).exists())
                p = DRUID / name
                self.assertTrue(p.is_file())
                source = p.read_text()
                nodes = ast.parse(source, filename=str(p))
                self.assertTrue(any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("test_") for n in ast.walk(nodes)
                ))
                self.assertNotIn("__file__", source)
                self.assertNotIn("from tests.", source)

    def test_normal_pytest_collection_still_includes_druid(self):
        ini = (ROOT / "pytest.ini").read_text()
        self.assertIn("testpaths = tests", ini)
        self.assertIn("norecursedirs = release", ini)
        self.assertNotIn("norecursedirs = mechanics", ini)

    def test_ci_collects_moved_group(self):
        workflow = (ROOT / ".github/workflows/druid-mechanics-test-layout.yml").read_text()
        self.assertIn("tests/mechanics/druid", workflow)
        self.assertIn("--collect-only", workflow)


if __name__ == "__main__":
    unittest.main()

import copy
import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "p73_preflight.py"
spec = importlib.util.spec_from_file_location("p73_preflight", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class P73PreflightTests(unittest.TestCase):
    def setUp(self):
        self.ref = {"raid":{"parties":[{"players":[{
            "talentsString":"5532220115501351--505",
            "equipment":[{"id":n} for n in range(16)],
            "rotation":{"priorityList":[{"action":n} for n in range(10)]}
        }]}]},"simOptions":{"iterations":10000}}

    def candidate(self):
        out = copy.deepcopy(self.ref)
        module.player(out)["talentsString"] = "alternate"
        return out

    def test_reference(self):
        self.assertEqual(module.validate_reference(self.ref)["reference_dps"], 728.1936126415858)

    def test_talent_only(self):
        module.validate_candidate(self.ref, self.candidate())

    def test_reference_seeding_rejected(self):
        with self.assertRaises(AssertionError):
            module.validate_candidate(self.ref, self.ref)

    def test_gear_mutation_rejected(self):
        c = self.candidate()
        module.player(c)["equipment"][0]["id"] = 999
        with self.assertRaises(AssertionError):
            module.validate_candidate(self.ref, c)

    def test_apl_mutation_rejected(self):
        c = self.candidate()
        module.player(c)["rotation"]["priorityList"].reverse()
        with self.assertRaises(AssertionError):
            module.validate_candidate(self.ref, c)

    def test_encounter_mutation_rejected(self):
        c = self.candidate()
        c["simOptions"]["iterations"] = 100
        with self.assertRaises(AssertionError):
            module.validate_candidate(self.ref, c)

if __name__ == "__main__":
    unittest.main()

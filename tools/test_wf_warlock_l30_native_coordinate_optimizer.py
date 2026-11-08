import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wf_warlock_l30_native_coordinate_optimizer import (
    choose_diverse_apls, proposal_key, run_search,
)


class AutomaticNativeSearchTests(unittest.TestCase):
    def test_candidate_identity_has_every_optimization_dimension(self):
        row = {"talents": "t1", "pet": "Succubus", "gear": "native_dps",
               "apl": [{"action": {"castSpell": {"spellId": {"spellId": 7}}}}]}
        ref = proposal_key(row)
        for axis, value in (("talents", "t2"), ("pet", "Imp"),
                            ("gear", "native_max_hp"), ("apl", [])):
            altered = dict(row)
            altered[axis] = value
            self.assertNotEqual(ref, proposal_key(altered), axis)

    def test_native_apl_search_not_a_fixed_handwritten_seven(self):
        apls = [
            (str(spell), [{"action": {"castSpell": {"spellId": {"spellId": spell}}}}])
            for spell in (15, 27, 45, 63)
        ]
        selected = choose_diverse_apls(apls, limit=4, rng=__import__("random").Random(42))
        self.assertEqual(len(selected), 4)
        self.assertEqual({name for name, _ in selected}, {"15", "27", "45", "63"})

    def test_all_incomplete_is_ci_failure_not_false_success(self):
        request = {"raid": {"parties": [{"players": [{
            "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": {
                "spellId": 1}}}}]}
        }]}]}}
        domain = {
            "gear": {"native_dps": request, "native_max_hp": request},
            "apl": [], "apls": [
                ("native_alt", [{"action": {"castSpell": {"spellId": {"spellId": 2}}}}])],
            "talents": [{"talents": "222-0-0", "label": "from_source"}],
            "pets": ["Succubus", "Imp"],
            "audit": {},
        }
        failed = {"status": "INCOMPLETE", "confirmed_kills": 0, "error": "native refused"}
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wf_warlock_l30_native_coordinate_optimizer.evaluate",
                       return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "ZERO_SUCCESSFUL_100_MOB_RUNS"):
                    run_search(Path("/rust-native"), domain, Path(tmp), budget=4, seed=1093)


if __name__ == "__main__":
    unittest.main()

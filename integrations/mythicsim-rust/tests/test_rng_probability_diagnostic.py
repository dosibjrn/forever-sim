"""TDD for an isolated, non-scoring patched-Rust RNG probability diagnostic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rng_probability_diagnostic import instrument_engine, replay_failed_gear_requests


RNG = """impl BalancedRng {
    fn proc(&mut self, p: f64, key: &str) -> bool {
        assert!(p.is_finite() && (0.0..=1.0).contains(&p),
            "balanced RNG: probability must be finite and in [0,1]");
        true
    }
}
"""
MELEE = """fn foo(&mut self, spell: usize) {
    if self.proc(self.physical_crit_chance(spell), "Physical Crit Roll") {
        println!("crit");
    }
}
"""


class RngDiagnosticContract(unittest.TestCase):
    def test_instrument_only_diagnostic_copy_and_capture_spell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src/core/fight").mkdir(parents=True)
            (root / "src/core/rng.rs").write_text(RNG)
            (root / "src/core/fight/melee.rs").write_text(MELEE + MELEE.replace("fn foo", "fn bar"))
            instrument_engine(root)
            rng = (root / "src/core/rng.rs").read_text()
            melee = (root / "src/core/fight/melee.rs").read_text()
            self.assertIn("RNG_PROBABILITY_DIAGNOSTIC", rng)
            self.assertIn("RNG_PHYSICAL_CRIT_DIAGNOSTIC", melee)
            self.assertIn("spell={:?}", melee)
            self.assertEqual(2, melee.count("RNG_PHYSICAL_CRIT_DIAGNOSTIC"))
            self.assertIn("self.proc(chance, \"Physical Crit Roll\")", melee)
            with self.assertRaisesRegex(AssertionError, "already instrumented|exactly once"):
                instrument_engine(root)

    def test_replay_preserves_exact_request_and_never_records_paid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_dir = root / "gear-probe/profiles/druid__feral_cat"
            request_dir.mkdir(parents=True)
            request = {"simOptions": {"iterations": 10, "randomSeed": "2710"}, "raid": {}}
            (request_dir / "gear_attempt_000.request.json").write_text(json.dumps(request))
            failures = [{
                "request_path": "profiles/druid__feral_cat/gear_attempt_000.request.json",
                "category": "RUST_BALANCED_RNG_PROBABILITY",
                "rng_replay": {"seed": 2710, "iterations": 10},
            }]
            (root / "gear-probe/gear_probe.json").write_text(json.dumps({
                "rows": [{"profile_id": "druid/feral_cat", "native_failures": failures}]
            }))
            seen = []
            def runner(command, **kwargs):
                import subprocess
                payload = json.loads(Path(command[command.index("--request") + 1]).read_text())
                seen.append((payload, kwargs["env"]["WOWSIM_RNG_MODE"]))
                return subprocess.CompletedProcess(command, 101, "", (
                    'RNG_PHYSICAL_CRIT_DIAGNOSTIC spell=12 chance=1.23\n'
                    'RNG_PROBABILITY_DIAGNOSTIC label="Physical Crit Roll" p=1.23\n'
                    'balanced RNG: probability must be finite and in [0,1]\n'
                ))
            out = root / "diagnostics"
            summary = replay_failed_gear_requests(root / "gear-probe", out, "diagnostic-binary",
                                                   runner=runner)
            self.assertEqual(1, len(summary["replays"]))
            entry = summary["replays"][0]
            self.assertEqual("DIAGNOSTIC_NOT_PAID", entry["accounting"])
            self.assertEqual(1.23, entry["invalid_probability"])
            self.assertEqual(12, entry["spell_id"])
            self.assertEqual("Physical Crit Roll", entry["label"])
            self.assertEqual([(request, "balanced")], seen)
            self.assertEqual(request, json.loads((request_dir / "gear_attempt_000.request.json").read_text()))
            self.assertNotIn("native_paid", entry)


if __name__ == "__main__":
    unittest.main()

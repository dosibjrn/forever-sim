"""TDD: extreme physical crit thresholds must preserve stochastic semantics."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rng_extreme_probability_fix import patch_engine, verify_fixed_replays

SOURCE = """            RandomRequest::Bernoulli(p) => {
                let value = match self {
                    SimRng::Balanced(rng) => rng.proc(p,label),
                    _ if p>=1.0 => true,
                    _ if p<=0.0 => false,
                    _ => matches!(self.sample(RandomRequest::Uniform01,label),
                        RandomOutcome::Float(x) if x < p),
                };
                RandomOutcome::Bool(value)
            }
"""


class ExtremeProbabilityContract(unittest.TestCase):
    def test_bounded_policy_precedes_balanced_quota_without_hiding_nan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"src/core").mkdir(parents=True)
            (root/"src/core/rng.rs").write_text(SOURCE)
            patch_engine(root)
            text=(root/"src/core/rng.rs").read_text()
            self.assertLess(text.index("_ if p>=1.0 => true"),
                            text.index("SimRng::Balanced(rng) => rng.proc(p,label)"))
            self.assertLess(text.index("_ if p<=0.0 => false"),
                            text.index("SimRng::Balanced(rng) => rng.proc(p,label)"))
            self.assertIn("wf_l60_rng_extreme_tests",text)
            self.assertIn("f64::NAN",text)
            with self.assertRaisesRegex(AssertionError,"already|expected"):
                patch_engine(root)

    def test_fixed_replay_uses_real_evaluator_but_never_paid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            gear=root/"gear"
            (gear/"profiles/druid__feral_cat").mkdir(parents=True)
            request={"simOptions":{"iterations":10,"randomSeed":"2710"},"raid":{}}
            path=gear/"profiles/druid__feral_cat/gear_attempt_000.request.json"
            path.write_text(json.dumps(request))
            (gear/"gear_probe.json").write_text(json.dumps({"rows":[{
                "profile_id":"druid/feral_cat",
                "native_failures":[{
                    "category":"RUST_BALANCED_RNG_PROBABILITY",
                    "request_path":"profiles/druid__feral_cat/gear_attempt_000.request.json",
                    "rng_replay":{"seed":2710,"iterations":10}
                }]
            }]}))
            seen=[]
            def native(binary, candidate, iterations, seed, mode, deadline):
                seen.append((copy.deepcopy(candidate),iterations,seed,mode))
                return 555.0, {}, 0.05, "native-sha"
            summary=verify_fixed_replays(gear,root/"out","mock-binary",evaluator=native)
            self.assertEqual(1,len(summary["replays"]))
            self.assertEqual("DIAGNOSTIC_NOT_PAID",summary["replays"][0]["accounting"])
            self.assertEqual(555.0,summary["replays"][0]["native_score"])
            self.assertEqual([(request,10,2710,"balanced")],seen)
            self.assertNotIn("native_paid",summary["replays"][0])


if __name__=="__main__":
    unittest.main()

"""Regression checks for native Rust rotation search contract (fake CLI only)."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "rotation_search.py"
spec = importlib.util.spec_from_file_location("rotation_search", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RotationSearchTests(unittest.TestCase):
    def test_digest_stable_and_average(self):
        self.assertEqual(module.digest({"a":1,"b":2}), module.digest({"b":2,"a":1}))
        self.assertEqual(module.average_dps({"result":{"raidMetrics":{"dps":{"avg":42.5}}}}),42.5)

    def test_expired_deadline_never_starts_native(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TimeoutError):
                module.simulate(pathlib.Path("/nonexistent"), {}, 1, tmp, "candidate_x",
                                deadline=time.monotonic()-0.001)

    def test_timeout_clamped_to_remaining_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = pathlib.Path(tmp)/"slow-engine"
            fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(3)\n")
            fake.chmod(0o755)
            deadline=time.monotonic()+0.2
            before=time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                module.simulate(fake, {}, 1, tmp, "candidate_x", deadline=deadline)
            self.assertLess(time.monotonic()-before, 1.5)

    def test_search_is_diagnostic_and_writes_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            fake=root/"fake-engine"
            fake.write_text("""#!/usr/bin/env python3
import json,sys
args=sys.argv
req=json.load(open(args[args.index('--request')+1]))
rot=req['raid']['parties'][0]['players'][0]['rotation']['priorityList']
json.dump({'result':{'raidMetrics':{'dps':{'avg':float(rot[0]['id'])}}}},
          open(args[args.index('--outfile')+1],'w'))
""")
            fake.chmod(0o755)
            req={"raid":{"parties":[{"players":[{"rotation":{"priorityList":[{"id":1},{"id":2},{"id":3},{"id":4}]}}]}]},"simOptions":{"iterations":1}}
            inp=root/"request.json";inp.write_text(json.dumps(req))
            out=root/"out"
            p=subprocess.run([sys.executable,str(SCRIPT),"--binary",str(fake),"--request",str(inp),
                              "--output",str(out),"--seconds","3","--screen-iterations","1",
                              "--holdout-iterations","1"],capture_output=True,text=True,timeout=8)
            self.assertEqual(p.returncode,0,p.stderr)
            report=json.loads((out/"search_report.json").read_text())
            self.assertEqual(report["status"],"DIAGNOSTIC_ONLY_P7_2_NOT_CERTIFIED")
            self.assertLessEqual(report["elapsed_seconds"],3)
            frozen=json.loads((out/"frozen_stochastic_holdout.json").read_text())
            self.assertNotEqual(frozen["request"]["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"],
                                req["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"])
            self.assertEqual(frozen["request"]["simOptions"]["iterations"],1)

if __name__=="__main__":
    unittest.main()

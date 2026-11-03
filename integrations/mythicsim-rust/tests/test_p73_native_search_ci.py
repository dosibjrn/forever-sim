"""P7.3 native talent-search contract tests (fake engine for end-to-end CI)."""
import copy, importlib.util, json, random, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from talent_schema_druid import parse,encode,points,validate,legal_add
from p73_talent_search_v2 import random_build, edit_neighbors

class TalentSearchContractTests(unittest.TestCase):
    def test_reference_is_source_legal(self):
        s="5532220115501351--505"
        r=parse(s)
        self.assertEqual(51,points(r))
        self.assertTrue(validate(r))
        self.assertEqual(s,encode(r))

    def test_random_cold_source_legal(self):
        for seed in range(300):
            s=encode(random_build(random.Random(seed)))
            self.assertTrue(validate(parse(s)))
            self.assertNotEqual(s,"5532220115501351--505")

    def test_mutations_remain_source_legal(self):
        rng=random.Random(343)
        cur=random_build(rng)
        for _ in range(100):
            cur=edit_neighbors(cur,rng)
            self.assertTrue(validate(cur))

    def test_moonkin_and_insect_are_mandatory_with_frozen_apl(self):
        r=parse("5532220115501351--505")
        r[0][15]=0
        self.assertFalse(validate(r))
        r=parse("5532220115501351--505")
        r[0][8]=0
        self.assertFalse(validate(r))

    def test_native_runner_passes_required_typed_rng_mode(self):
        import time
        from unittest.mock import patch
        import p73_talent_search_v2 as search

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            request.write_text(json.dumps({
                "simOptions": {"iterations": 10, "randomSeed": "42"}}))
            seen = []

            def fake_run(command, **kwargs):
                seen.append((command, kwargs))
                Path(command[command.index("--outfile") + 1]).write_text(json.dumps({
                    "result": {"raidMetrics": {"dps": {"avg": 730.0}}}}))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(search.subprocess, "run", fake_run):
                score, _output, _elapsed, _sha = search.run(
                    root / "engine", json.loads(request.read_text()), 1, 42,
                    "balanced", time.monotonic() + 5.0)
            self.assertEqual(730.0, score)
            command, kwargs = seen[0]
            self.assertEqual("balanced", command[command.index("--rng-mode") + 1])
            self.assertNotIn("WOWSIM_RNG_MODE", kwargs.get("env", {}))

    def test_native_cli_contract_and_frozen_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            binary=root/"fake_engine"
            binary.write_text("""#!/usr/bin/env python3
import json,sys
argv=sys.argv
mode=argv[argv.index('--rng-mode')+1]
if mode not in ('balanced','stochastic'): sys.exit(2)
req=json.load(open(argv[argv.index('--request')+1]))
ranks=req['raid']['parties'][0]['players'][0]['talentsString']
value=650+sum(int(v) for v in ranks if v.isdigit())+int(ranks[0])
out={'result':{'raidMetrics':{'dps':{'avg':float(value)}}}}
json.dump(out,open(argv[argv.index('--outfile')+1],'w'))
""")
            binary.chmod(0o755)
            reference={'raid':{'parties':[{'players':[{
                'talentsString':'5532220115501351--505',
                'equipment':{'items':[{'id':i} for i in range(16)]},
                'rotation':{'priorityList':[{'action':i} for i in range(10)]}
            }]}]},'simOptions':{'iterations':10000,'randomSeed':'1179706472'}}
            inputfile=root/'reference.json'
            inputfile.write_text(json.dumps(reference))
            output=root/'out'
            done=subprocess.run([sys.executable,str(ROOT/'p73_talent_search_v2.py'),
                '--binary',str(binary),'--reference',str(inputfile),'--outdir',str(output),
                '--seconds','6.0','--screen-iterations','2','--holdout-iterations','1000','--rng-mode','balanced'],
                capture_output=True,text=True,timeout=12)
            self.assertEqual(done.returncode,0,done.stderr)
            report=json.loads((output/'report.json').read_text())
            self.assertEqual(report['status'],'NATIVE_RUST_P73_DIAGNOSTIC_NOT_2D_CAUSAL_PASS')
            self.assertLessEqual(report['elapsed_s'],6.0)
            self.assertGreater(report['paid_count'],0)
            self.assertEqual(report['winner_selection'],'best_balanced_screen')
            self.assertEqual(report['screen_rng_mode'],'balanced')
            self.assertEqual(report['paid_stochastic_finalists'],0)
            self.assertEqual(report['rerank_finalists'],0)
            self.assertIsNone(report['best_reranked'])
            self.assertFalse((output/'reranked_finalists.json').exists())
            self.assertFalse(report['live_2d_causal_trace_exists'])
            frozen=json.loads((output/'frozen_winner_request.json').read_text())
            self.assertEqual(frozen['raid']['parties'][0]['players'][0]['equipment'],
                             reference['raid']['parties'][0]['players'][0]['equipment'])
            self.assertEqual(frozen['raid']['parties'][0]['players'][0]['rotation'],
                             reference['raid']['parties'][0]['players'][0]['rotation'])

if __name__=='__main__':unittest.main()

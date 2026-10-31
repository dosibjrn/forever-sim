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

    def test_stock_rng_cannot_masquerade_as_balanced(self):
        """The mock ignores WOWSIM_RNG_MODE like the original unpatched Rust CLI."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            binary=root/"fake_engine"
            binary.write_text("""#!/usr/bin/env python3
import json,sys
args=sys.argv
req=json.load(open(args[args.index('--request')+1]))
json.dump({'result':{'raidMetrics':{'dps':{'avg':725.0}}}},
          open(args[args.index('--outfile')+1],'w'))
""")
            binary.chmod(0o755)
            request={'raid':{'parties':[{'players':[{
                'talentsString':'5532220115501351--505',
                'equipment':{'items':[{'id':i} for i in range(16)]},
                'rotation':{'priorityList':[{'action':i} for i in range(10)]}
            }]}]},'simOptions':{'iterations':10000,'randomSeed':'1179706472'}}
            input_file=root/'reference.json'
            input_file.write_text(json.dumps(request))
            completed=subprocess.run([
                sys.executable,str(ROOT/'p73_talent_search_v2.py'),
                '--binary',str(binary),'--reference',str(input_file),
                '--outdir',str(root/'out'),'--seconds','6',
                '--rng-mode','balanced','--holdout-iterations','1000'
            ],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(completed.returncode,0)
            self.assertIn('BALANCED_RNG_NOT_VERIFIED',completed.stderr)

    def test_native_cli_contract_and_frozen_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            binary=root/"fake_engine"
            binary.write_text("""#!/usr/bin/env python3
import json,sys
argv=sys.argv
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
                '--seconds','6.0','--screen-iterations','2','--holdout-iterations','1000','--rng-mode','stochastic'],
                capture_output=True,text=True,timeout=12)
            self.assertEqual(done.returncode,0,done.stderr)
            report=json.loads((output/'report.json').read_text())
            self.assertEqual(report['status'],'NATIVE_RUST_P73_DIAGNOSTIC_NOT_2D_CAUSAL_PASS')
            self.assertLessEqual(report['elapsed_s'],6.0)
            self.assertGreater(report['paid_count'],0)
            self.assertGreater(report['rerank_finalists'],0)
            self.assertEqual(report['best_reranked']['rerank_iterations'],10000)
            self.assertTrue((output/'reranked_finalists.json').exists())
            self.assertFalse(report['live_2d_causal_trace_exists'])
            frozen=json.loads((output/'frozen_winner_request.json').read_text())
            self.assertEqual(frozen['raid']['parties'][0]['players'][0]['equipment'],
                             reference['raid']['parties'][0]['players'][0]['equipment'])
            self.assertEqual(frozen['raid']['parties'][0]['players'][0]['rotation'],
                             reference['raid']['parties'][0]['players'][0]['rotation'])

if __name__=='__main__':unittest.main()

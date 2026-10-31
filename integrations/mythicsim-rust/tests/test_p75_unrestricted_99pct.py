"""WF679: 99% unrestricted-vs-fixed Druid DPS rule and Balance legality."""
import math
import inspect
import random
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p75_unrestricted_search import (
    one_percent_floor,within_one_percent,process_numeric_pass,random_talents,mutate_talents,require_paid_spec_coverage,main
)
from talent_schema_druid import validate,points

class UnrestrictedNinetyNinePercentTests(unittest.TestCase):
    def test_mean_dps_floor_exact_and_boundary(self):
        best=813.6215750677441
        floor=one_percent_floor(best)
        self.assertAlmostEqual(floor,805.4853593170667,places=8)
        self.assertTrue(within_one_percent(best,best))
        self.assertTrue(within_one_percent(floor,best))
        self.assertFalse(within_one_percent(floor-.001,best))
        self.assertFalse(within_one_percent(753.082727124166,best))
        self.assertFalse(within_one_percent(float("nan"),best))
        with self.assertRaises(ValueError):one_percent_floor(float("nan"))
    def test_nonfinite_native_dps_cannot_count_as_paid_or_complete_holdout(self):
        from p75_unrestricted_search import (
            require_finite_native_dps, paid_candidate_record, paid_rerank_record
        )
        req={"raid":{"parties":[{"players":[{
            "equipment":{"items":[]},"talentsString":"","rotation":{"priorityList":[]}
        }]}]}}
        self.assertEqual(require_finite_native_dps(0.0,"holdout"),0.0)
        self.assertEqual(require_finite_native_dps(813.5,"screen"),813.5)
        for invalid in (float("nan"), float("inf"), -float("inf"), -0.01, True):
            with self.subTest(invalid=str(invalid)):
                for stage in ("screen","probe","rerank","holdout"):
                    with self.assertRaisesRegex(ValueError,"INVALID_NATIVE_DPS:"+stage):
                        require_finite_native_dps(invalid,stage)
                with self.assertRaisesRegex(ValueError,"INVALID_NATIVE_DPS:screen"):
                    paid_candidate_record("cat",req,invalid,"balanced",0.1)
                with self.assertRaisesRegex(ValueError,"INVALID_NATIVE_DPS:rerank"):
                    paid_rerank_record("cat",req,invalid,1234,1800)

    def test_unrestricted_coverage_requires_successfully_paid_native_screen_per_spec(self):
        # CLI --specs is a request, not evidence that all four forms were
        # actually simulated. Attempts can fail legality/native before payment.
        specs=["cat","balance","bear","resto"]
        paid=[{"spec":"cat"},{"spec":"cat"},{"spec":"balance"},{"spec":"bear"}]
        with self.assertRaisesRegex(RuntimeError,"BLOCKED.*resto"):
            require_paid_spec_coverage(specs,paid)
        paid.append({"spec":"resto"})
        self.assertEqual(require_paid_spec_coverage(specs,paid),
                         {"cat":2,"balance":1,"bear":1,"resto":1})
        self.assertEqual(require_paid_spec_coverage(["cat"],[{"spec":"cat"}]),
                         {"cat":1})
        with self.assertRaisesRegex(RuntimeError,"BLOCKED.*cat"):
            require_paid_spec_coverage(["cat"],[])

    def test_numeric_gate_is_unverified_without_accepted_comparator(self):
        # A standalone search without an independently accepted compatible
        # fixed-spec result cannot self-certify P7.5 by clearing only the
        # external 811-DPS floor. Paired CI assesses its own comparator.
        self.assertIsNone(process_numeric_pass(900.0, None))
        self.assertFalse(process_numeric_pass(810.0, 850.0))
        self.assertFalse(process_numeric_pass(811.1, 900.0))
        self.assertTrue(process_numeric_pass(848.8, 850.0))
        self.assertFalse(process_numeric_pass(float("nan"), 850.0))

    def test_native_cli_report_never_self_certifies_process_p75(self):
        # Caller-provided --benchmark-source cannot establish an accepted
        # comparable P7.1-P7.4 prior or live 2D/native causal integration.
        from p75_unrestricted_search import native_report_numeric_verdict
        self.assertEqual(native_report_numeric_verdict(850.0,850.0),
                         {"process_numeric_pass":None,
                          "native_numeric_diagnostic_pass":True})
        self.assertEqual(native_report_numeric_verdict(810.0,850.0),
                         {"process_numeric_pass":None,
                          "native_numeric_diagnostic_pass":False})
        self.assertEqual(native_report_numeric_verdict(850.0,None),
                         {"process_numeric_pass":None,
                          "native_numeric_diagnostic_pass":None})
        self.assertIn("**native_report_numeric_verdict(holdout,a.benchmark_dps)",
                      inspect.getsource(main))

    def test_balance_search_has_valid_signature_without_reference_seeding(self):
        rng=random.Random(679)
        for _ in range(30):
            ranks=random_talents(rng,"balance")
            self.assertEqual(points(ranks),51)
            self.assertEqual(ranks[0][8],1)
            self.assertEqual(ranks[0][15],1)
            self.assertTrue(validate(ranks))
            child=mutate_talents(rng,ranks,"balance")
            self.assertTrue(validate(child))
    def test_other_specs_not_forced_into_moonkin(self):
        rng=random.Random(679)
        for spec in ("cat","bear","resto"):
            ranks=random_talents(rng,spec)
            self.assertEqual(points(ranks),51)
            self.assertTrue(validate(ranks,moonkin=False,insect=False))
    def test_all_specs_preserve_identical_saved_reference_geometry(self):
        # P7 requires one pinned encounter AND one target geometry. A Bear
        # candidate cannot gain front-facing rage while Balance is evaluated
        # at a different 15yd range; those DPS values are incomparable.
        from p75_unrestricted_search import source_template, player, MODES
        def fixture(spec, **geometry):
            return {"raid":{"parties":[{"players":[{
                MODES[spec]:{},
                "rotation":{"priorityList":[]},
                **geometry,
            }]}]}}
        # Explicit geometry must survive a cross-spec template conversion.
        saved=fixture("cat",distanceFromTarget=7,inFrontOfTarget=False)
        balance=fixture("balance",distanceFromTarget=15,inFrontOfTarget=True)
        fixtures={spec:fixture(spec,distanceFromTarget=30,inFrontOfTarget=True)
                  for spec in MODES}
        for spec in MODES:
            with self.subTest(spec=spec):
                result=source_template(saved,spec,fixtures,balance)
                self.assertEqual(player(result).get("distanceFromTarget"),7)
                self.assertIs(player(result).get("inFrontOfTarget"),False)
        # The actual saved 811-DPS Cat request omits both fields. Do not
        # invent spec-dependent geometry for that case either.
        implicit=fixture("cat")
        for spec in MODES:
            with self.subTest(implicit_spec=spec):
                result=source_template(implicit,spec,fixtures,balance)
                self.assertNotIn("distanceFromTarget",player(result))
                self.assertNotIn("inFrontOfTarget",player(result))

    def test_all_specs_preserve_saved_personal_buffs_and_consumables(self):
        # Same source/encounter includes player-level consumables and buffs,
        # not merely raid-level buffs and target geometry. A cross-spec
        # comparison must not silently inject different per-spec loadouts.
        from p75_unrestricted_search import source_template, player, MODES
        def fixture(spec, buffs, consumables):
            return {"raid":{"parties":[{"players":[{
                MODES[spec]:{},
                "rotation":{"priorityList":[]},
                "buffs":buffs,
                "consumables":consumables,
            }]}]}}
        saved=fixture("cat",{"pinned":"saved-buff"},{"pinned":"saved-consume"})
        balance=fixture("balance",{"pinned":"balance-buff"},{"pinned":"balance-consume"})
        fixtures={spec:fixture(spec,{"pinned":spec+"-buff"},
                              {"pinned":spec+"-consume"}) for spec in MODES}
        for spec in MODES:
            with self.subTest(spec=spec):
                result=source_template(saved,spec,fixtures,balance)
                self.assertEqual(player(result)["buffs"],player(saved)["buffs"])
                self.assertEqual(player(result)["consumables"],player(saved)["consumables"])
                self.assertEqual(result["raid"],source_template(saved,spec,fixtures,balance)["raid"])

    def test_paid_native_ledger_retains_replayable_request_and_rng_provenance(self):
        # Previously paid.json held only an opaque key + DPS. The actual
        # scored gear/talents/APL/encounter could not be independently
        # reconstructed or audited, even with the pinned Rust executable.
        import copy
        import json
        from p75_unrestricted_search import paid_candidate_record, key
        req={"encounter":{"duration":120},
             "raid":{"parties":[{"players":[{
                 "equipment":{"items":[{"id":100,"enchant":1508}]},
                 "talentsString":"source-legal-test-fixture",
                 "rotation":{"priorityList":[{"action":"cast","spellId":42}]},
             }]}]}}
        expected=copy.deepcopy(req)
        record=paid_candidate_record("cat",req,812.5,"stochastic_fallback",0.3)
        self.assertEqual(record["candidate_request"],expected)
        self.assertEqual(record["key"],key("cat",expected))
        self.assertEqual(record["screen_mode"],"stochastic_fallback")
        self.assertEqual(json.loads(json.dumps(record))["candidate_request"],expected)
        req["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]=999
        self.assertEqual(record["candidate_request"],expected,
                         "Paid evidence must not alias a mutable candidate")
        src=inspect.getsource(main)
        self.assertIn("record=paid_candidate_record(spec,q,dps,screen_mode,elapsed)",src)
        self.assertIn('"candidate_request":copy.deepcopy(q)',src)
        for field in ("search_rng_seed","screen_rng_seed","stochastic_probe_seed",
                      "rerank_seed","holdout_seed","screen_iterations",
                      "stochastic_probe_iterations","rerank_iterations"):
            self.assertIn('"'+field+'":',src)

    def test_paid_screen_survives_failed_stochastic_probe(self):
        # Every completed native screen evaluation is paid evidence even if
        # its optional follow-up stochastic probe throws or times out.
        # The ledger append must precede that probe (not be skipped by the
        # enclosing exception handler). This is a fail-closed wiring check
        # on the actual production entry point, not a helper-only test.
        src=inspect.getsource(main)
        screen=src.index("record=paid_candidate_record(spec,q,dps,screen_mode,elapsed)")
        append=src.index("paid.append(record)")
        probe=src.index('run(a.binary,q,140,seed+554433,"stochastic",end_screen)')
        self.assertLess(screen,append)
        self.assertLess(append,probe,
                        "A failed paid stochastic probe must not erase a completed screen result")
        self.assertEqual(src.count("paid.append(record)"),1)

    def test_paid_evidence_is_persisted_before_holdout(self):
        # A failed/expired holdout must not erase hundreds of paid screen
        # evaluations and stochastic finalist reranks from the artifact.
        import json
        import tempfile
        from p75_unrestricted_search import persist_paid_search_evidence
        paid=[{"key":"screen-1","candidate_request":{"encounter":{"duration":120}}}]
        reranks=[{"key":"rerank-1","rerank_dps":800.0,"seed":100005,"iterations":1800}]
        errors=[{"stage":"native","error":"test"}]
        rejections=[{"category":"enchant_slot"}]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            persist_paid_search_evidence(out,paid,reranks,errors,rejections,
                                         "HOLDOUT_NOT_VERIFIED")
            for name,expected in (("paid.json",paid),("rerank.json",reranks),
                                  ("failures.json",errors),
                                  ("legality_rejections.json",rejections)):
                self.assertEqual(json.loads((out/name).read_text()),expected)
            status=json.loads((out/"search_evidence_stage.json").read_text())
            self.assertEqual(status["stage"],"HOLDOUT_NOT_VERIFIED")
            self.assertEqual(status["paid_screen_records"],1)
            self.assertEqual(status["paid_rerank_records"],1)
            paid[0]["key"]="changed"
            self.assertEqual(json.loads((out/"paid.json").read_text())[0]["key"],
                             "screen-1")
        src=inspect.getsource(main)
        self.assertLess(src.index('persist_paid_search_evidence(a.outdir,paid,rerank_paid'),
                        src.index('if not reranked:'))
        self.assertLess(src.index('persist_paid_search_evidence(a.outdir,paid,rerank_paid'),
                        src.index('holdout,output,_,_=run('),
                        "Raw paid evidence must survive a holdout timeout")
        self.assertIn('"HOLDOUT_COMPLETE"',src)

    def test_paid_rerank_ledger_replays_all_finalist_evaluations(self):
        # The previous paid.json only recorded screen/probe DPS; stochastic
        # finalist rerank scores that actually selected the winner vanished.
        # A rerank is another paid native evaluation, not free metadata.
        import copy
        import json
        from p75_unrestricted_search import paid_rerank_record, key
        req={"encounter":{"duration":120},
             "raid":{"parties":[{"players":[{
                 "equipment":{"items":[{"id":100,"enchant":1508}]},
                 "talentsString":"source-legal-test-fixture",
                 "rotation":{"priorityList":[{"action":"cast","spellId":42}]},
             }]}]}}
        expected=copy.deepcopy(req)
        record=paid_rerank_record("cat",req,812.75,105123,1800)
        self.assertEqual(record["candidate_request"],expected)
        self.assertEqual(record["key"],key("cat",expected))
        self.assertEqual(record["rerank_dps"],812.75)
        self.assertEqual(record["rng_mode"],"stochastic")
        self.assertEqual(record["seed"],105123)
        self.assertEqual(record["iterations"],1800)
        self.assertEqual(json.loads(json.dumps(record))["candidate_request"],expected)
        req["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]=999
        self.assertEqual(record["candidate_request"],expected)
        src=inspect.getsource(main)
        self.assertIn("rerank_paid.append(paid_rerank_record(",src)
        self.assertIn('("rerank.json",rerank_paid)',src)
        self.assertIn('"rerank_paid_records":len(rerank_paid)',src)

    def test_gear_swaps_do_not_carry_old_item_enchants(self):
        # A legal new item may not accept the enchant from the old item.
        # Previously 50% gear mutations retained that enchant and were
        # rejected before native scoring; ring/trinket de-dup did likewise.
        from p75_unrestricted_search import set_candidate_item, build
        gear=[{"id":100,"enchant":1508},{"id":200,"enchant":77}]
        set_candidate_item(gear,0,101)
        self.assertEqual(gear[0],{"id":101})
        set_candidate_item(gear,1,200)
        self.assertEqual(gear[1],{"id":200,"enchant":77})
        set_candidate_item(gear,1,201)
        self.assertEqual(gear[1],{"id":201})
        src=inspect.getsource(build)
        self.assertIn("set_candidate_item(gear,j,pick_gear",src)
        self.assertIn("set_candidate_item(gear,j,ids[j])",src)

    def test_cold_enchants_require_actual_item_slot_legality(self):
        from p75_unrestricted_search import source_valid_reference_enchant
        from p74_gear_validation import RejectedGear
        saved_items=[{"id":100+i} for i in range(16)]
        saved_items[0]["enchant"]=1508
        saved={"raid":{"parties":[{"players":[{"equipment":{"items":saved_items}}]}]}}
        class FakeValidator:
            def item(self,slot,item_id,enchant_id):
                if enchant_id==1508:
                    raise RejectedGear("enchant_slot","only original saved pair is replayed")
                if enchant_id==999:
                    raise RejectedGear("source_missing","not a legitimate exception")
                return {}
        validator=FakeValidator()
        self.assertTrue(source_valid_reference_enchant(validator,saved,0,100,1508))
        self.assertFalse(source_valid_reference_enchant(validator,saved,0,200,1508))
        self.assertFalse(source_valid_reference_enchant(validator,saved,0,100,999))
        self.assertTrue(source_valid_reference_enchant(validator,saved,0,200,77))
        self.assertFalse(source_valid_reference_enchant(validator,saved,0,200,0))

    def test_candidate_enchants_are_validated_not_silently_replaced_by_reference_defaults(self):
        # WF684 used a validator whose reference enchants were stripped, then
        # called validate(ids) without candidate enchants. This could accept
        # arbitrary source-illegal enchant/item pairs after a gear mutation.
        from p75_unrestricted_search import validate_candidate_gear
        from p74_gear_validation import RejectedGear
        import copy
        original=[{"id":100+i} for i in range(16)]
        original[0]["enchant"]=1508
        saved={"raid":{"parties":[{"players":[{"equipment":{"items":original}}]}]}}
        class FakeValidator:
            def __init__(self):self.last=None;self.error_category="enchant_slot"
            def item(self,slot,item_id,enchant_id=None):
                if slot==0 and enchant_id==1508:
                    raise RejectedGear(self.error_category,"reference enchant metadata mismatch")
                return {}
            def validate(self,ids,enchants=None):
                self.last=(list(ids),list(enchants) if enchants is not None else None)
                if enchants is None:
                    raise RuntimeError("candidate enchants were not provided")
                if ids[0]!=100 and enchants[0]==1508:
                    raise RejectedGear("enchant_slot","saved enchant on unrelated item")
                return []
        validator=FakeValidator()
        gear=copy.deepcopy(original)
        evidence=validate_candidate_gear(validator,saved,gear)
        self.assertEqual(validator.last[1][0],0)
        self.assertEqual(evidence["actual_enchants"][0],1508)
        self.assertEqual(evidence["reference_pair_exceptions"][0]["item_id"],100)
        gear[0]["id"]=200
        with self.assertRaises(RejectedGear):
            validate_candidate_gear(validator,saved,gear)
        gear[0]["enchant"]=0
        evidence=validate_candidate_gear(validator,saved,gear)
        self.assertEqual(validator.last[1][0],0)
        self.assertEqual(evidence["reference_pair_exceptions"],[])
        gear=copy.deepcopy(original)
        validator.error_category="source_missing"
        with self.assertRaises(RejectedGear):
            validate_candidate_gear(validator,saved,gear)

    def test_illegal_cat_talents_fail_closed_with_python_optimized(self):
        # Production validation must not rely on Python assert: -O removes it.
        # Force the source validator to reject a proposed allocation.
        import subprocess
        script = (
            "import random,sys\n"
            "from unittest.mock import patch\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "from p75_unrestricted_search import random_talents\n"
            "with patch('p75_unrestricted_search.validate',return_value=False):\n"
            "    try: random_talents(random.Random(679),'cat')\n"
            "    except ValueError: pass\n"
            "    else: raise RuntimeError('illegal talents passed with -O')\n"
        )
        result = subprocess.run(
            [sys.executable, "-O", "-c", script, str(ROOT)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_rejects_nonfinite_and_out_of_range_search_budgets(self):
        # A cold search must not silently receive an unbounded deadline.
        # Run the real entry point; rejection must precede reading any file.
        import subprocess
        script=ROOT/"p75_unrestricted_search.py"
        args=[sys.executable,str(script)]
        for name in ("binary","reference","balance-reference","catalogue","fixtures","outdir","engine-items","engine-enchants"):
            args.extend(("--"+name,"/no/such/path"))
        for seconds in ("nan","inf","-inf","301","15","-1"):
            with self.subTest(seconds=seconds):
                p=subprocess.run(args+[f"--seconds={seconds}"],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(p.returncode,0)
                self.assertIn("finite and within (15, 300]",p.stderr,
                              "Budget validation must run before any file I/O: "+p.stderr)

    def test_cold_budget_begins_before_reference_and_gear_preparation(self):
        # Regression: prior WF684 started the 300s clock only after
        # loading the reference and constructing the source/Rust gear pools.
        src=inspect.getsource(main)
        self.assertLess(src.index("t0=time.monotonic();deadline=t0+a.seconds"),
                        src.index("reference=json.loads"))
        self.assertLess(src.index("t0=time.monotonic();deadline=t0+a.seconds"),
                        src.index("catalogue_pools(a.catalogue,validator)"))
    def test_runner_fails_when_saved_feral_external_floor_is_missed(self):
        src=inspect.getsource(main)
        self.assertIn('"external_reference_mean_pass":holdout>=FERAL_SAVED_REFERENCE_DPS',src)
        self.assertIn('if not report["external_reference_mean_pass"]:',src)
        self.assertIn('if report["within_1pct_of_fixed_spec"] is False:',src)
    def test_paired_ci_cannot_self_certify_unaccepted_fixed_cat(self):
        # A newly searched Cat is a same-encounter native diagnostic, not
        # independently ACCEPTED strongest compatible P7.1-P7.4 evidence.
        # A green diagnostic must never set the PROCESS P7.5 flag true.
        workflow=(ROOT.parents[1]/".github/workflows/wf677-unrestricted-p75.yml").read_text()
        self.assertIn("'process_numeric_pass':None",workflow)
        self.assertIn("'native_paired_numeric_diagnostic_pass':numeric_pass",workflow)
        self.assertIn("'comparator_status':'BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED'",workflow)
        self.assertNotIn("'process_numeric_pass':numeric_pass",workflow)

    def test_paired_ci_enforces_external_reference_and_relative_floor(self):
        workflow=(ROOT.parents[1]/".github/workflows/wf677-unrestricted-p75.yml").read_text()
        self.assertIn("external_pass=f>=reference",workflow)
        self.assertIn("relative_pass=f>=floor",workflow)
        self.assertIn("numeric_pass=relative_pass and external_pass",workflow)
        self.assertIn("if not numeric_pass:raise SystemExit",workflow)

    def test_native_report_pins_binary_and_all_source_fixture_hashes(self):
        # A same-encounter cross-spec comparison is not auditable if it only
        # identifies the saved Cat request, but not the actual Rust executable
        # and the other per-spec action/consumable templates.
        src=inspect.getsource(main)
        self.assertIn('"engine_binary_sha256":sha256(a.binary)',src)
        self.assertIn('"balance_reference_sha256":sha(balance_reference)',src)
        self.assertIn('"source_fixture_sha256":{spec:sha(req) for spec,req in fixtures.items()}',src)

    def test_paired_ci_rejects_cross_source_artifact_splicing(self):
        # Execute the REAL workflow's compare predicate on synthetic report
        # artifacts, rather than only asserting the presence of source text.
        import json,subprocess,tempfile,textwrap,copy
        workflow=(ROOT.parents[1]/".github/workflows/wf677-unrestricted-p75.yml").read_text()
        section=workflow.split("      - name: Report native fixed-Cat",1)[1]
        code=textwrap.dedent(section.split("          python3 - <<'PY'\n",1)[1].split("\n          PY",1)[0])
        cat={"winner_dps":820.0,"winner_spec":"cat","searched_specs":["cat"],
             "elapsed_s":270.0,"holdout_iterations":4000,"paid_per_spec":{"cat":1},
             "feral_saved_reference_dps":811.0237260012982}
        free=dict(cat,winner_dps=830.0,searched_specs=["cat","balance","bear","resto"],\n                  paid_per_spec={"cat":1,"balance":1,"bear":1,"resto":1})
        for field in ("feral_saved_reference_sha256","reference_encounter_sha256",
                      "catalogue_sha256","pinned_rust_items_sha256",
                      "pinned_rust_enchants_sha256","engine_binary_sha256",
                      "balance_reference_sha256"):
            cat[field]=free[field]="same-source-hash"
        cat["source_fixture_sha256"]=free["source_fixture_sha256"]={"cat":"a","balance":"b","bear":"c","resto":"d"}
        # Reports with matching input hashes can still conceal distinct
        # effective winner worlds; compare actual winner.json payloads too.
        shared_world={"encounter":{"duration":120},
                      "simOptions":{"randomSeed":77},
                      "raid":{"buffs":{"raid":True},"parties":[{"players":[{
                          "buffs":{"mark":True},"consumables":{"flask":True},
                          "distanceFromTarget":0,
                          "equipment":{"items":[]},"talentsString":"test",
                          "rotation":{"priorityList":[]},"feralCatDruid":{}
                      }]}]}}
        winners={"cat":copy.deepcopy(shared_world),
                 "unrestricted":copy.deepcopy(shared_world)}
        def execute(tmp):
            for name,data in (("cat",cat),("unrestricted",free)):
                dest=tmp/"results"/("wf684-"+name+"-evidence")
                dest.mkdir(parents=True,exist_ok=True)
                (dest/"report.json").write_text(json.dumps(data))
                (dest/"winner.json").write_text(json.dumps(winners[name]))
            return subprocess.run([sys.executable,"-c",code],cwd=tmp,capture_output=True,text=True,timeout=10)
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d)
            self.assertEqual(execute(tmp).returncode,0,"Matching native reports should compare successfully")
            free["paid_per_spec"]["resto"]=0\n            self.assertNotEqual(execute(tmp).returncode,0,"Must reject advertised but unscored Resto")\n            free["paid_per_spec"]["resto"]=1\n            p=winners["unrestricted"]["raid"]["parties"][0]["players"][0]
            p["buffs"]["mark"]=False
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject changed player buffs")
            p["buffs"]["mark"]=True
            p["distanceFromTarget"]=15
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject changed target geometry")
            p["distanceFromTarget"]=0
            winners["unrestricted"]["encounter"]["duration"]=130
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject changed encounter")
            winners["unrestricted"]["encounter"]["duration"]=120
            winners["unrestricted"]["raid"]["buffs"]["raid"]=False
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject changed raid buffs")
            winners["unrestricted"]["raid"]["buffs"]["raid"]=True
            winners["unrestricted"]["simOptions"]["randomSeed"]=99
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject changed runtime options")
            winners["unrestricted"]["simOptions"]["randomSeed"]=77
            free["engine_binary_sha256"]="different-rust-executable"
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject different Rust binaries")
            free["engine_binary_sha256"]="same-source-hash"
            free["source_fixture_sha256"]={**cat["source_fixture_sha256"],"cat":"different-apl-source"}
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject mixed per-spec APL sources")
            free["source_fixture_sha256"]=cat["source_fixture_sha256"]
            free["holdout_iterations"]=999
            self.assertNotEqual(execute(tmp).returncode,0,"Must reject sub-1000 stochastic holdout")

if __name__=="__main__":
    unittest.main()

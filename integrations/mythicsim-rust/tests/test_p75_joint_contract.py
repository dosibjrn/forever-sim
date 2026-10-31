"""WF678 P7.5 cold joint search: source-lawful candidate generation contracts."""
import copy
import json
import random
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p75_joint_search import make_candidate, candidate_key, player, parse, validate
from apl_mutation import mutate_apl
REFERENCE=ROOT.parent.parent/"docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"

class JointSearchContracts(unittest.TestCase):
    def setUp(self):
        self.reference=json.loads(REFERENCE.read_text())
        self.pools={i:[100000+100*i+j for j in range(1,9)] for i in range(16)}
        self.names={v:f"slot{i}/item{j}" for i,vs in self.pools.items()
                    for j,v in enumerate(vs)}
    def test_independent_cold_initialization(self):
        r=random.Random(678)
        saved=candidate_key(self.reference)
        for _ in range(20):
            q=make_candidate(self.reference,self.pools,r,item_names=self.names)
            p=player(q);ids=[x["id"] for x in p["equipment"]["items"]]
            self.assertNotEqual(saved,candidate_key(q))
            self.assertEqual(51,sum(map(sum,parse(p["talentsString"]))))
            self.assertTrue(validate(parse(p["talentsString"])))
            self.assertNotEqual(ids[10],ids[11])
            self.assertNotEqual(ids[12],ids[13])
            self.assertEqual(q["encounter"],self.reference["encounter"])
            self.assertEqual(q["raid"]["debuffs"],self.reference["raid"]["debuffs"])
    def test_reference_identity_is_not_a_legal_rejection(self):
        # A cold search cannot warm-start from reference. But the result,
        # if independently rediscovered, must remain a legal candidate key.
        key=candidate_key(self.reference)
        self.assertEqual(key,candidate_key(copy.deepcopy(self.reference)))
        q=copy.deepcopy(self.reference)
        self.assertEqual(key,candidate_key(q))

    def test_cli_rejects_short_holdout_before_opening_assets(self):
        from unittest import mock
        from p75_joint_search import main
        argv=['p75_joint_search.py','--binary','missing_engine',
              '--reference','missing_reference','--catalogue','missing_db',
              '--engine-items','missing_items','--engine-enchants','missing_enchants',
              '--outdir','not-created-for-invalid-holdout',
              '--holdout-iterations','999']
        with mock.patch('sys.argv',argv),self.assertRaises(SystemExit) as ctx:
            main()
        self.assertEqual(2,ctx.exception.code)

    def test_cli_rejects_nonfinite_or_overbudget_time_before_assets(self):
        # PROCESS v2.10 allows at most 300s cold end-to-end. NaN/inf
        # bypass ordinary <=0 checks and could create an unbounded run.
        from unittest import mock
        from p75_joint_search import main
        for seconds in ("nan", "inf", "301", "1e309"):
            with self.subTest(seconds=seconds):
                argv=['p75_joint_search.py','--binary','missing_engine',
                      '--reference','missing_reference','--catalogue','missing_db',
                      '--engine-items','missing_items','--engine-enchants','missing_enchants',
                      '--outdir','not-created-for-invalid-time',
                      '--seconds',seconds]
                with mock.patch('sys.argv',argv),self.assertRaises(SystemExit) as ctx:
                    main()
                self.assertEqual(2,ctx.exception.code)

    def test_apl_grammar_is_expressive_and_spell_id_safe(self):
        import copy
        ref_actions=self.reference["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        snapshot=copy.deepcopy(ref_actions)
        def spell_key(action):
            spell=action.get("action",{}).get("castSpell",{}).get("spellId")
            return json.dumps(spell,sort_keys=True) if spell else None
        source={spell_key(a) for a in ref_actions}-{None}
        r=random.Random(678125)
        generated=[mutate_apl(None,ref_actions,r,cold=True) for _ in range(80)]
        self.assertTrue(any(len(actions)!=len(ref_actions) for actions in generated),
                        "Source-legal APL action insertion/deletion must be reachable")
        source_conditions={json.dumps(a["action"].get("condition"),sort_keys=True)
                           for a in ref_actions}
        self.assertTrue(any(any(json.dumps(a["action"].get("condition"),sort_keys=True)
                                not in source_conditions for a in actions)
                            for actions in generated),
                        "APL must create or modify predicates, not only reorder them")
        for actions in generated:
            self.assertTrue(any("castSpell" in x["action"] and
                                "condition" not in x["action"] for x in actions))
            self.assertTrue({spell_key(a) for a in actions}-{None} <= source)
        self.assertEqual(snapshot,ref_actions,"Mutations must never modify their source corpus")

    def test_generic_apl_grammar_on_other_class_corpus(self):
        # No Balance-specific spell or expression: generic class/gate adapter.
        corpus=[{"action":{"castSpell":{"spellId":{"spellId":12345}}}},
                {"action":{"castSpell":{"spellId":{"spellId":23456}},
                           "condition":{"cmp":{"lhs":{"currentEnergy":{}},
                                               "op":"OpGe",
                                               "rhs":{"const":{"val":"40"}}}}}}]
        r=random.Random(501)
        for _ in range(40):
            actions=mutate_apl(corpus,corpus,r,cold=True)
            self.assertTrue(2<=len(actions)<=20)
            self.assertTrue(any("castSpell" in a["action"]
                                and "condition" not in a["action"] for a in actions))
            self.assertTrue({a["action"]["castSpell"]["spellId"]["spellId"]
                             for a in actions}<= {12345,23456})

    def test_candidate_enchant_legality_uses_actual_candidate_not_reference(self):
        # A reference head enchant is deliberately wrong for the head slot.
        # The same item without that enchant must be legal. A candidate
        # validator must not silently substitute the saved reference enchant.
        from p74_gear_validation import GearValidator, RejectedGear, SLOTS, RUST_TYPES, ARMOR
        v = GearValidator.__new__(GearValidator)
        v.rows = {}
        v.engine = {}
        v.allowed = {}
        v.enchants = {777: {"type": "EnchantTypeWeapon"}}
        v.ref_items = []
        v.professions = set()
        v.phase = None
        v.cache = {}
        ids = list(range(1000, 1016))
        for idx, (iid, slot) in enumerate(zip(ids, SLOTS)):
            source_slot = "one_hand" if slot == "weapon" else slot
            v.rows[iid] = {"slot": source_slot, "required_level": 60,
                           "armor_type": "cloth" if slot in ARMOR else "",
                           "name": f"Test item {iid}", "source_url": None,
                           "weapon_hands": 1, "profession": None, "phase": None}
            v.engine[iid] = {"type": RUST_TYPES[slot], "name": f"Test item {iid}",
                             "scaling_options": [1],
                             "hand_type": "HandTypeOneHand",
                             "ranged_weapon_type": "RangedWeaponTypeIdol"}
            v.ref_items.append({"id": iid, "enchant": 777 if idx == 0 else 0})
        with self.assertRaises(RejectedGear) as old:
            v.validate(ids)
        self.assertEqual(old.exception.category, "enchant_slot")
        # Candidate has removed the saved head enchant; this must be legal.
        no_enchants = v.validate(ids, [0] * 16)
        self.assertEqual(no_enchants[0]["enchant"], 0)
        # Re-check with the illegal enchant, including after a cached success.
        with self.assertRaises(RejectedGear) as bad:
            v.validate(ids, [777] + [0] * 15)
        self.assertEqual(bad.exception.category, "enchant_slot")

    def test_ci_watches_all_native_search_dependencies(self):
        # PR #25 must rerun native evidence if a shared validator, source
        # fixture, or Rust gear/talent dependency changes without a direct
        # edit to p75_joint_search.py. Both push and PR path filters matter.
        workflow=(ROOT.parent.parent/".github/workflows/wf678-p75-pr.yml").read_text()
        dependencies=(
            "integrations/mythicsim-rust/p73_talent_search_v2.py",
            "integrations/mythicsim-rust/p74_gear_search.py",
            "integrations/mythicsim-rust/p74_gear_validation.py",
            "integrations/mythicsim-rust/tests/test_p74_gear_search_ci.py",
            "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json",
            "data/forever/catalogue/items_2026-09-29.sqlite",
        )
        for dependency in dependencies:
            with self.subTest(dependency=dependency):
                self.assertEqual(
                    2,workflow.count("      - '"+dependency+"'"),
                    f"WF678 must watch {dependency} for both push and PR events")

    def test_ci_runs_exact_pr_head_not_synthetic_merge_ref(self):
        # On pull_request, actions/checkout defaults to refs/pull/N/merge.
        # A successful CI then proves the synthetic merge tree, NOT the
        # advertised PR HEAD. Pin both contracts and native evidence jobs
        # to the exact source head and assert the checked-out SHA.
        workflow=(ROOT.parent.parent/".github/workflows/wf678-p75-pr.yml").read_text()
        exact_ref="          ref: ${{ github.event.pull_request.head.sha || github.sha }}"
        self.assertEqual(
            2, workflow.count(exact_ref),
            "Both WF678 jobs must checkout the exact PR head (or push SHA)")
        self.assertEqual(
            2, workflow.count("      - name: Verify exact checkout head"),
            "Both jobs must independently assert their source revision")

    def test_one_axis_neighborhood(self):
        r=random.Random(679)
        parent=make_candidate(self.reference,self.pools,r,item_names=self.names)
        for _ in range(40):
            q=make_candidate(self.reference,self.pools,r,elite=parent,item_names=self.names)
            p=player(q);ids=[x["id"] for x in p["equipment"]["items"]]
            self.assertTrue(validate(parse(p["talentsString"])))
            self.assertNotEqual(ids[10],ids[11])
            self.assertNotEqual(ids[12],ids[13])
            self.assertEqual(q["encounter"],self.reference["encounter"])

if __name__=="__main__":unittest.main()

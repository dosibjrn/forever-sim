"""P7.4 gear-only source request invariants."""
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p74_preflight import preflight,player
from p74_gear_search import source_enchant_pools
from p74_gear_validation import RejectedGear
REFERENCE=ROOT.parent.parent/"docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
class P74Tests(unittest.TestCase):
    def setUp(self):
        self.reference=json.loads(REFERENCE.read_text())
    def test_saved_reference(self):
        self.assertEqual(16,len(player(self.reference)["equipment"]["items"]))
        self.assertIn("reference_sha256",preflight(self.reference))
    def test_gear_only(self):
        alt=copy.deepcopy(self.reference)
        player(alt)["equipment"]["items"][0]["id"]+=1
        self.assertEqual(16,len(preflight(self.reference,alt)["candidate_ids"]))
    def test_independent_reference_rediscovery_is_legal(self):
        # The initializer must not seed reference gear, but a cold search can
        # independently generate it and run an ordinary candidate validation.
        result=preflight(self.reference,self.reference)
        self.assertEqual(16,len(result["candidate_ids"]))
    def test_enchant_is_equipment_and_other_metadata_remains_fixed(self):
        changed=copy.deepcopy(self.reference)
        first=player(changed)["equipment"]["items"][0]
        first["enchant"]=int(first.get("enchant",0))+1
        self.assertEqual(16,len(preflight(self.reference,changed)["candidate_ids"]))
        changed["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["gem"]="new"
        with self.assertRaises(ValueError):
            preflight(self.reference,changed)

    def test_source_enchants_are_not_restricted_to_reference(self):
        class Validator:
            enchants={100: {},200: {}}
            def item(self,idx,iid,enchant_id):
                if enchant_id==200 and idx!=0:
                    raise RejectedGear("enchant_slot","not admitted for this slot")
        pools={i:[i+1000] for i in range(16)}
        options=source_enchant_pools(Validator(),pools)
        self.assertEqual([None,100,200],options[0])
        self.assertEqual([None,100],options[1])

    def test_native_authoritative_enchants_are_forwarded_without_python_filter(self):
        class Validator:
            enchants={100: {},200: {}}
            def item(self,*args):
                raise AssertionError("native mode must not run Python enchant legality")
        pools={i:[i+1000] for i in range(16)}
        options=source_enchant_pools(
            Validator(),pools,native_authoritative=True)
        self.assertEqual([None,100,200],options[0])
        self.assertEqual([None,100,200],options[15])

    def test_freeze_talents_rotation_and_encounter(self):
        for mutation in ["talents","rotation","encounter"]:
            with self.subTest(mutation=mutation):
                alt=copy.deepcopy(self.reference)
                player(alt)["equipment"]["items"][0]["id"]+=1
                if mutation=="talents":player(alt)["talentsString"]="different"
                if mutation=="rotation":player(alt)["rotation"]["priorityList"]=[]
                if mutation=="encounter":alt["encounter"]["duration"]=88
                with self.assertRaises(ValueError):preflight(self.reference,alt)
if __name__=="__main__":unittest.main()

"""P7.4 gear-only source request invariants."""
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p74_preflight import preflight,player
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

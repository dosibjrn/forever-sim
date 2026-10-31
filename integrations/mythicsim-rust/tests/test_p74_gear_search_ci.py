"""WF670 P7.4 source + pinned Rust item contracts; no real engine required."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from p74_preflight import preflight,player
from p74_gear_validation import GearValidator, RejectedGear, RUST_TYPES, SLOTS
from p74_gear_search import candidate_pool, simulate, NativeFailure

REFERENCE=ROOT.parent.parent/"docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"

class P74GearSearchContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.sqlite=root/"items.sqlite"
        self.engine=root/"items.jsonl"
        self.enchants=root/"enchants.jsonl"
        self.ref=json.loads(REFERENCE.read_text())
        # Preserve real talents, APL, enchants and all 16 equipment positions.
        self.original=[x["id"] for x in player(self.ref)["equipment"]["items"]]
        ids=[]
        for idx,slot in enumerate(SLOTS):
            ids.append((idx,100000+idx,slot))
            ids.append((idx,self.original[idx],slot))
        conn=sqlite3.connect(self.sqlite)
        conn.execute("""CREATE TABLE items(
            item_id INTEGER PRIMARY KEY, name TEXT, slot TEXT, required_level INTEGER,
            armor_type TEXT, weapon_hands INTEGER, spell_power REAL,
            intellect REAL, hit REAL, crit REAL, spirit REAL, source_url TEXT)""")
        conn.execute("CREATE TABLE item_class_eligibility (item_id INTEGER, class_id INTEGER)")
        eng=[]
        for idx,item_id,slot in ids:
            srcslot="two_hand" if slot=="weapon" else slot
            conn.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (item_id,f"Item {item_id}",srcslot,60,"cloth",2 if slot=="weapon" else 0,12,5,1,1,2,f"https://wowhead.com/forever/item={item_id}"))
            eng.append({"id":item_id,"name":f"Item {item_id}","type":RUST_TYPES[slot],
                        "scaling_options":{"0":{"stats":{}}},
                        "hand_type":"HandTypeTwoHand" if slot=="weapon" else "HandTypeUnknown",
                        "ranged_weapon_type":"RangedWeaponTypeIdol" if slot=="relic" else "",
                        "unique":False,"limit_category":0,"class_allowlist":[]})
        conn.commit()
        conn.close()
        self.rows=eng
        self._save_engine()
        enc_types={}
        for idx,item in enumerate(player(self.ref)["equipment"]["items"]):
            if item.get("enchant"):
                enc_types.setdefault(int(item["enchant"]),set()).add(RUST_TYPES[SLOTS[idx]])
        self.enchants.write_text("".join(
            json.dumps({"effect_id":eid,"type":sorted(types)[0],"extra_types":sorted(types)[1:]})+"\n"
            for eid,types in sorted(enc_types.items())))
        self.validator=GearValidator(self.sqlite,self.engine,self.enchants,self.ref)
    def tearDown(self):
        self.validator.close()
        self.tmp.cleanup()
    def _save_engine(self):
        self.engine.write_text("".join(json.dumps(row)+"\n" for row in self.rows))
    def _alt_ids(self):
        return [100000+i for i in range(16)]
    def test_pinned_source_rust_intersection(self):
        x=self.validator.validate(self._alt_ids())
        self.assertEqual(16,len(x))
        self.assertEqual(16,len(self.validator.audit(self._alt_ids())["items"]))
        pool,exclusions=candidate_pool(self.validator,2)
        self.assertEqual(16,len(pool))
        self.assertEqual(2,len(pool[0]))
    def test_missing_engine_item_not_admitted(self):
        self.validator.engine.pop(100000)
        with self.assertRaisesRegex(RejectedGear,"absent from pinned engine"):
            self.validator.validate(self._alt_ids())
    def test_wrong_engine_slot_not_admitted(self):
        self.validator.engine[100000]["type"]="ItemTypeNeck"
        with self.assertRaises(RejectedGear) as ctx:
            self.validator.validate(self._alt_ids())
        self.assertEqual("engine_wrong_slot",ctx.exception.category)
    def test_duplicate_ring_and_trinket_rejected(self):
        for i,j in ((10,11),(12,13)):
            with self.subTest(positions=(i,j)):
                ids=self._alt_ids();ids[j]=ids[i]
                with self.assertRaises(RejectedGear) as ctx:self.validator.validate(ids)
                self.assertEqual("duplicate_equip",ctx.exception.category)
    def test_unique_equip_category_rejected_across_ids(self):
        self.validator.engine[100010]["limit_category"]=57
        self.validator.engine[100011]["limit_category"]=57
        with self.assertRaises(RejectedGear) as ctx:self.validator.validate(self._alt_ids())
        self.assertEqual("unique_category",ctx.exception.category)
    def test_wrong_profession_and_phase_fail_closed(self):
        self.validator.engine[100000]["required_profession"]="Alchemy"
        with self.assertRaises(RejectedGear) as ctx:self.validator.validate(self._alt_ids())
        self.assertEqual("profession",ctx.exception.category)
        self.validator.engine[100000].pop("required_profession")
        self.validator.engine[100000]["required_phase"]=7
        with self.assertRaises(RejectedGear) as ctx:self.validator.validate(self._alt_ids())
        self.assertEqual("phase_unverified",ctx.exception.category)
    def test_missing_enchant_rejected(self):
        slot=0
        enc=player(self.ref)["equipment"]["items"][slot]["enchant"]
        self.validator.enchants.pop(enc)
        with self.assertRaises(RejectedGear) as ctx:self.validator.validate(self._alt_ids())
        self.assertEqual("engine_enchant_missing",ctx.exception.category)
    def test_independent_saved_reference_rediscovery_is_allowed(self):
        # A reference item set is never injected as a cold-search seed.
        # Should it be generated spontaneously, legality and fixed-dimension
        # validation must not reject it for being identical to reference.
        self.assertEqual(16,len(preflight(self.ref,self.ref)["candidate_ids"]))

    def test_frozen_talents_and_apl_even_after_gear_change(self):
        req=copy.deepcopy(self.ref)
        for i,x in enumerate(player(req)["equipment"]["items"]):x["id"]=self._alt_ids()[i]
        self.assertEqual(16,len(preflight(self.ref,req)["candidate_ids"]))
        player(req)["talentsString"]="0--0"
        with self.assertRaises(ValueError):preflight(self.ref,req)
    def test_native_errors_include_stdout_when_stderr_empty(self):
        tmp=Path(self.tmp.name)
        fake=tmp/"engine"
        fake.write_text("#!/bin/sh\necho 'unknown_item: no item with id 999'\nexit 2\n")
        fake.chmod(0o755)
        with self.assertRaises(NativeFailure) as ctx:
            simulate(fake,self.ref,"balanced",10,11,time.monotonic()+1)
        self.assertEqual("unknown_item",ctx.exception.category)
        self.assertIn("999",str(ctx.exception))
    def test_strict_seconds_deadline(self):
        tmp=Path(self.tmp.name)
        fake=tmp/"slow"
        fake.write_text("#!/bin/sh\nsleep 2\n")
        fake.chmod(0o755)
        start=time.monotonic()
        with self.assertRaises(TimeoutError):
            simulate(fake,self.ref,"balanced",10,11,start+0.25)
        self.assertLess(time.monotonic()-start,0.9)

if __name__=="__main__":unittest.main()

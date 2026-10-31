#!/usr/bin/env python3
"""Pinned-engine/source gear admission for native P7.4 (fail closed, no winner exceptions).

The Forever catalogue proposes item IDs; the Rust engine data are the
authoritative identity, slot, scaling and supported-item source for native runs.
This checks *recorded* restrictions, not undocumented game phase/faction rules.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

SLOTS = ("head","neck","shoulder","back","chest","wrist","hands","waist",
         "legs","feet","finger","finger","trinket","trinket","weapon","relic")
RUST_TYPES = {
    "head":"ItemTypeHead", "neck":"ItemTypeNeck",
    "shoulder":"ItemTypeShoulder", "back":"ItemTypeBack",
    "chest":"ItemTypeChest", "wrist":"ItemTypeWrist",
    "hands":"ItemTypeHands", "waist":"ItemTypeWaist",
    "legs":"ItemTypeLegs", "feet":"ItemTypeFeet",
    "finger":"ItemTypeFinger", "trinket":"ItemTypeTrinket",
    "weapon":"ItemTypeWeapon", "relic":"ItemTypeRanged",
}
SOURCE_SLOTS = {"weapon":("one_hand","main_hand","two_hand"),
                "relic":("relic",)}
ARMOR = frozenset({"head","shoulder","chest","wrist","hands","waist","legs","feet"})

class RejectedGear(ValueError):
    def __init__(self, category, message, *, slot=None, item_id=None):
        super().__init__(message)
        self.category, self.slot, self.item_id = category, slot, item_id

def sha256(path):
    with open(path,"rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def read_jsonl(path, key='id'):
    p=Path(path)
    if not p.is_file() or p.stat().st_size<100:
        raise ValueError(f"PINNED_ENGINE_DATA_MISSING_OR_LFS_POINTER:{p}")
    out={}
    with p.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():continue
            row=json.loads(line)
            iid=int(row[key])
            if iid in out:raise ValueError(f"DUPLICATE_PINNED_ENGINE_ITEM:{iid}")
            out[iid]=row
    if not out:raise ValueError(f"EMPTY_PINNED_ENGINE_DATA:{p}")
    return out

def _norm(s):
    return " ".join(str(s or "").casefold().split())

class GearValidator:
    def __init__(self, catalogue, rust_items, rust_enchants, reference):
        self.catalogue=Path(catalogue)
        self.rust_items=Path(rust_items)
        self.rust_enchants=Path(rust_enchants)
        self.connection=sqlite3.connect(f"file:{self.catalogue.resolve()}?mode=ro",uri=True)
        self.connection.row_factory=sqlite3.Row
        if self.connection.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise ValueError("SOURCE_CATALOGUE_CORRUPT")
        self.engine=read_jsonl(self.rust_items)
        self.enchants=read_jsonl(self.rust_enchants, key="effect_id")
        self.rows={int(r["item_id"]):dict(r) for r in self.connection.execute("SELECT * FROM items")}
        self.allowed={}
        for r in self.connection.execute("SELECT item_id,class_id FROM item_class_eligibility"):
            self.allowed.setdefault(int(r[0]),set()).add(int(r[1]))
        self.reference=reference
        self.ref_items=reference["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        self.professions={str(reference["raid"]["parties"][0]["players"][0].get(x,"")).lower()
                          for x in ("profession1","profession2")}
        self.phase=reference.get("phase")
        self.cache={}

    def close(self):
        self.connection.close()

    def item(self, idx, iid, enchant_id=None):
        # Existing P7.4 callers default to the saved reference enchant.
        # Joint P7.5 must pass the *actual* candidate enchant (including 0).
        if enchant_id is None:
            enchant_id=self.ref_items[idx].get("enchant",0)
        try:
            enchant_id=int(enchant_id or 0)
        except (TypeError,ValueError) as exc:
            raise RejectedGear("invalid_enchant",f"Invalid enchant {enchant_id!r}") from exc
        if enchant_id<0:
            raise RejectedGear("invalid_enchant",f"Negative enchant {enchant_id}")
        key=(idx,int(iid),enchant_id)
        if key in self.cache:return self.cache[key]
        slot=SLOTS[idx]
        def reject(kind,details):
            raise RejectedGear(kind,details,slot=slot,item_id=int(iid))
        r=self.rows.get(int(iid))
        if r is None:reject("source_missing",f"item {iid} absent from source SQLite")
        expected=SOURCE_SLOTS.get(slot,(slot,))
        if r["slot"] not in expected:reject("source_wrong_slot",f"{iid}: {r['slot']} expected {expected}")
        if r["required_level"] is None:
            reject("required_level_unverified",f"{iid}: source level not known")
        if int(r["required_level"])>60:reject("level",f"{iid}: level {r['required_level']}>60")
        if idx in range(10) and slot in ARMOR and r["armor_type"] not in ("","misc","cloth","leather"):
            reject("armor_proficiency",f"{iid}: druid cannot use {r['armor_type']}")
        if int(iid) in self.allowed and 11 not in self.allowed[int(iid)]:
            reject("source_class",f"{iid}: class restriction excludes druid")
        e=self.engine.get(int(iid))
        if e is None:reject("engine_missing",f"{iid}: absent from pinned engine items.jsonl")
        if e.get("type")!=RUST_TYPES[slot]:
            reject("engine_wrong_slot",f"{iid}: engine type {e.get('type')} expected {RUST_TYPES[slot]}")
        if _norm(r.get("name"))!=_norm(e.get("name")):
            reject("identity_mismatch",f"{iid}: catalogue {r.get('name')!r} != Rust {e.get('name')!r}")
        if not e.get("scaling_options"):
            reject("engine_no_scaling",f"{iid}: pinned Rust new_item requires base scaling")
        allows=e.get("class_allowlist") or []
        if allows and "ClassDruid" not in allows:
            reject("engine_class",f"{iid}: Rust class allowlist excludes druid: {allows}")
        if slot=="weapon":
            if e.get("hand_type") not in ("HandTypeOneHand","HandTypeMainHand",
                                         "HandTypeTwoHand","HandTypeUnknown"):
                reject("engine_weapon_hand",f"{iid}: unusable mainhand {e.get('hand_type')}")
            if r["weapon_hands"] not in (0,1,2):
                reject("source_weapon_hand",f"{iid}: unknown weapon hands {r['weapon_hands']}")
            if e.get("weapon_type")=="WeaponTypeShield":
                reject("shield",f"{iid}: shield is not a druid mainhand")
        if slot=="relic":
            # Go/Rust maps idol/libram/totem into ItemTypeRanged.
            weapon_type=e.get("ranged_weapon_type") or ""
            if weapon_type not in ("RangedWeaponTypeIdol","RangedWeaponTypeUnknown",""):
                reject("engine_relic_type",f"{iid}: not a druid relic: {weapon_type}")
        if slot in ARMOR:
            typ=e.get("armor_type","")
            if typ not in ("","ArmorTypeUnknown","ArmorTypeCloth","ArmorTypeLeather"):
                reject("engine_armor",f"{iid}: engine armor restriction {typ}")
        for field in ("required_profession","profession"):
            val=e.get(field) or r.get(field)
            if val and str(val).lower() not in self.professions:
                reject("profession",f"{iid}: recorded {field} requirement {val}")
        for field in ("phase","required_phase"):
            val=e.get(field) or r.get(field)
            if val and (self.phase is None or str(val)!=str(self.phase)):
                reject("phase_unverified",f"{iid}: item requires phase {val}; scenario has {self.phase}")
        if enchant_id:
            enc=self.enchants.get(enchant_id)
            if enc is None:
                reject("engine_enchant_missing",f"{iid}: preserved enchant {enchant_id} absent from Rust")
            types=[str(enc.get("type") or ""),str(enc.get("enchant_type") or "")]
            types.extend(map(str,enc.get("extra_types") or []))
            # Do not silently ignore a known, explicit nonmatching slot restriction.
            typed=[t for t in types if t and t not in ("EnchantTypeUnknown","ItemTypeUnknown")]
            if typed:
                valid={RUST_TYPES[slot], "EnchantType"+RUST_TYPES[slot].removeprefix("ItemType")}
                if slot=="weapon":valid.add("EnchantTypeWeapon")
                if not any(t in valid or t.endswith("All") or t.endswith("Any") for t in typed):
                    reject("enchant_slot",f"{iid}: enchant {enchant_id} targets {typed}, not {slot}")
        info={"slot":slot,"index":idx,"id":int(iid),"name":r["name"],
              "source_url":r.get("source_url"),"engine_type":e.get("type"),
              "engine_hand_type":e.get("hand_type"),"unique":bool(e.get("unique")),
              "limit_category":int(e.get("limit_category") or 0),
              "engine_effect_count":len(e.get("item_effects") or []),
              "enchant":enchant_id}
        self.cache[key]=info
        return info

    def validate(self, ids, enchants=None):
        if len(ids)!=16:raise RejectedGear("slot_count","Must supply 16 equipment IDs")
        if any(not isinstance(i,int) or i<=0 for i in ids):
            raise RejectedGear("invalid_id","Every item ID must be positive integer")
        if len(set(ids))!=16:
            raise RejectedGear("duplicate_equip","A single item ID cannot occupy two slots")
        if enchants is None:
            enchants=[item.get("enchant",0) for item in self.ref_items]
        if len(enchants)!=16:
            raise RejectedGear("enchant_count","Must supply 16 candidate enchant values")
        entries=[self.item(i,item,enchants[i]) for i,item in enumerate(ids)]
        categories=[v["limit_category"] for v in entries if v["limit_category"]>0]
        conflicts=[c for c,n in Counter(categories).items() if n>1]
        if conflicts:
            raise RejectedGear("unique_category",f"Duplicate engine limit_category: {conflicts}")
        return entries

    def audit(self,ids,enchants=None):
        return {"items":self.validate(ids,enchants),
                "source_catalogue_sha256":sha256(self.catalogue),
                "rust_items_sha256":sha256(self.rust_items),
                "rust_enchants_sha256":sha256(self.rust_enchants),
                "verified_dimensions":["source item identity/level/slot/class",
                    "pinned Rust item identity/scaling/slot/class/hand/armor",
                    "known enchant existence/slot", "item duplication and Rust limit_category"],
                "unverified_dimensions":["unrecorded faction/phase/profession rules",
                    "full semantic parity of every item effect and proc",
                    "live Go/Rust causal agreement"]}

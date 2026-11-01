"""GameIR-independent P1 expected-ability inventory from canonical spell SQLite.

This is a validation INPUT, not a combat implementation and not PASS evidence.
Sourced level hints are CANDIDATES, not proof a player learned the spell.
Ranks, non-combat source entities, pets, autoattacks and explicitly declared
scenario non-impact are separated without checking any Python combat action.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/forever/catalogue/forever_abilities.sqlite"
SCENARIO = "current_solo_leveling_100mob_v1"
CLASSES = frozenset(("druid", "hunter", "mage", "paladin", "priest",
                     "rogue", "shaman", "warlock", "warrior"))


def _waivers(root: Path, class_key: str, level: int, scenario: str) -> dict[int, dict]:
    document = json.loads((root / "gate_config/p1_scenario_applicability_v1.json").read_text())
    if document.get("schema") != "wf_p1_scenario_applicability_v1":
        raise ValueError("UNKNOWN_P1_SCENARIO_POLICY")
    if scenario not in {x["id"] for x in document["scenarios"]}:
        raise ValueError("UNKNOWN_P1_SCENARIO:" + scenario)
    selected = {}
    for r in document["records"]:
        if (r["class_key"] == class_key and r["scenario_id"] == scenario
                and r["min_level"] <= level <= r["max_level"]):
            if r["decision"] != "DOES_NOT_AFFECT_SIM" or int(r["spell_id"]) in selected:
                raise ValueError("INVALID_OR_DUPLICATE_NONIMPACT")
            selected[int(r["spell_id"])] = r
    return selected


def _rank_order(row: dict) -> tuple:
    return (int(row.get("rank_hint") or 0), int(row.get("level_hint") or 0))


def inventory(class_key: str, level: int, *, root: Path = ROOT,
              scenario: str = SCENARIO, db_path: Path | None = None) -> dict:
    cls = class_key.lower().strip()
    if cls not in CLASSES or not 1 <= int(level) <= 60:
        raise ValueError("INVALID_CLASS_OR_LEVEL")
    level = int(level)
    db_path = Path(db_path or SOURCE)
    if not db_path.is_file():
        raise ValueError("CANONICAL_SPELL_SQLITE_UNAVAILABLE")
    waivers = _waivers(root, cls, level, scenario)
    from src.game.data.forever.source_action_scope import classify_indexed_ability

    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(
            "SELECT spell_id,name,level_hint,rank_hint,source_url,raw_listview_json "
            "FROM spell_index WHERE class_key=? AND kind='abilities' ORDER BY spell_id",
            (cls,))]
        auto_spell_ids = set()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name="
                      "'verified_native_class_scenarios'").fetchone():
            for row in db.execute(
                "SELECT auto_json FROM verified_native_class_scenarios WHERE class_key=?",
                (cls,)):
                obj = json.loads(row["auto_json"])
                if type(obj.get("spell_id")) is int:
                    auto_spell_ids.add(obj["spell_id"])
        pet_spell_ids = set()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name="
                      "'companion_skill_source_facts'").fetchone():
            pet_spell_ids = {int(x["spell_id"]) for x in db.execute(
                "SELECT spell_id FROM companion_skill_source_facts "
                "WHERE class_key=? AND min_level<=?", (cls, level))}

    if not rows:
        raise ValueError("CLASS_SOURCE_INDEX_EMPTY:" + cls)
    # Source listview sometimes contains a passive/rune/pet entity, not a
    # player ability. Never fake it as a missing Rust cast action.
    qualified = []
    separately = []
    for row in rows:
        sid = int(row["spell_id"])
        level_hint = row["level_hint"]
        if level_hint is not None and int(level_hint) > level:
            continue
        kind = classify_indexed_ability(row, row["raw_listview_json"])["role"]
        rec = {"spell_id": sid, "name": row["name"],
               "level_hint": level_hint, "rank": row["rank_hint"],
               "source_url": row["source_url"]}
        if sid in waivers:
            w = waivers[sid]
            if w["name"] != row["name"]:
                raise ValueError("NONIMPACT_SOURCE_ID_NAME_MISMATCH:" + str(sid))
            separately.append({**rec, "status": "NOT_RELEVANT_TO_SIMULATION",
                               "reason": w["reason"]})
        elif kind in ("SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP",
                      "ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE",
                      "EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET"):
            separately.append({**rec, "status": "NOT_A_PROVEN_CASTABLE_ACTION",
                               "source_role": kind})
        elif sid in auto_spell_ids:
            separately.append({**rec, "status": "NATIVE_AUTO_ATTACK",
                               "channel": "native_melee_or_ranged_auto"})
        elif sid in pet_spell_ids:
            separately.append({**rec, "status": "PET_ACTION",
                               "channel": "native_pet_action"})
        elif level_hint is None:
            separately.append({**rec, "status": "ACQUISITION_UNRESOLVED"})
        else:
            qualified.append({**rec, "status": "POTENTIALLY_AVAILABLE_AT_LEVEL_NOT_PROVEN_LEARNED"})
    # Highest known source rank within a named family. An equal-level/rank
    # ambiguity stays visible, not artificially collapsed to one spell ID.
    grouped = {}
    for row in qualified:
        key = row["name"].strip().casefold()
        top = grouped.get(key, [])
        if not top or _rank_order(row) > _rank_order(top[0]):
            grouped[key] = [row]
        elif _rank_order(row) == _rank_order(top[0]):
            top.append(row)
    ranked = sorted((r for group in grouped.values() for r in group),
                    key=lambda r: (r["name"].casefold(),r["spell_id"]))
    # Lower ranks are represented but not required as independent effect
    # tests for this highest-rank P1 scope.
    kept = {r["spell_id"] for r in ranked}
    separately.extend({**r, "status": "LOWER_RANK_NOT_REQUIRED_IN_P1"}
                      for r in qualified if r["spell_id"] not in kept)
    return {"class": cls, "level": level, "scenario": scenario,
            "candidate_count": len(ranked), "candidates": ranked,
            "separate_count": len(separately),
            "separate": sorted(separately,key=lambda r:r["spell_id"]),
            "source_only": True, "game_ir_required": False,
            "effects_tested": 0, "p1_certified": False}

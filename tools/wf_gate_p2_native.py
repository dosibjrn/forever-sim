#!/usr/bin/env python3
"""Selected-Rust native P2 rank probes.

This is an executable adapter slice, not a P2 gate PASS and not an M1 recorder.
It reads source rank/tier facts directly from the canonical SQLite snapshot,
serializes by the pinned Rust FOREVER_TREES layout, and exercises the selected
forever-engine prepare --request path. No GameIR imports or Python talent-layout
fallbacks are permitted here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/forever/catalogue/forever_abilities.sqlite"
SOURCE_TABLE = "checkpoint_talent_source_positions"
TREE_ORDER = ("balance", "feral", "restoration")
TREE_LAYOUT_CONSTANTS = {
    "balance": "FOREVER_BALANCE",
    "feral": "FOREVER_FERAL_COMBAT",
    "restoration": "FOREVER_RESTORATION",
}
SOURCE_TREE_ALIASES = {
    "balance": "balance",
    "feral": "feral",
    "feral_combat": "feral",
    "feral-combat": "feral",
    "restoration": "restoration",
}
LAYOUT_CALL_RE = re.compile(
    r'\b(talent|new_talent)\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*\)'
)


class NativeP2Error(RuntimeError):
    """A fail-closed source, layout, or native-execution error."""


def _tree_key(value: str) -> str:
    key = str(value).strip().lower()
    try:
        return SOURCE_TREE_ALIASES[key]
    except KeyError as exc:
        raise NativeP2Error(f"P2_NATIVE_UNKNOWN_SOURCE_TREE:{value}") from exc


def load_source_positions(db_path: Path | str = DEFAULT_DB, level: int = 60) -> tuple[dict[str, Any], str]:
    """Read and validate the canonical source-position JSON without importing GameIR."""
    db = Path(db_path).resolve()
    if not db.is_file():
        raise NativeP2Error(f"P2_NATIVE_SOURCE_DB_MISSING:{db}")
    uri = db.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (SOURCE_TABLE,),
        ).fetchone()
        if not exists:
            raise NativeP2Error("P2_NATIVE_SOURCE_POSITION_TABLE_MISSING")
        rows = conn.execute(
            f"""SELECT class_key,source_build,min_level,source_sha256,source_json
                FROM {SOURCE_TABLE} WHERE class_key=? AND min_level<=?""",
            ("druid", int(level)),
        ).fetchall()
    if len(rows) != 1:
        raise NativeP2Error(f"P2_NATIVE_SOURCE_POSITION_SCOPE_ROWS:{len(rows)}")
    class_key, build, min_level, digest, raw = rows[0]
    raw = str(raw)
    actual_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if actual_digest != digest:
        raise NativeP2Error("P2_NATIVE_SOURCE_POSITION_SHA_MISMATCH")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NativeP2Error("P2_NATIVE_SOURCE_POSITION_JSON_INVALID") from exc
    if (
        data.get("schema") != "forever_source_talent_positions_v1"
        or data.get("class_key") != "druid"
        or data.get("source_build") != build
        or not data.get("source_generated")
        or not str(data.get("source_url", "")).startswith("https://")
        or int(data.get("min_level", -1)) != int(min_level)
        or int(min_level) > int(level)
    ):
        raise NativeP2Error("P2_NATIVE_SOURCE_POSITION_SCOPE_MISMATCH")
    per_row = int(data.get("points_per_row", 0))
    if per_row < 1:
        raise NativeP2Error("P2_NATIVE_INVALID_TIER_RULE")
    catalogue = data.get("talents")
    if not isinstance(catalogue, list) or not catalogue:
        raise NativeP2Error("P2_NATIVE_SOURCE_TALENT_INVENTORY_MISSING")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in catalogue:
        tid = str(entry.get("talent_id", ""))
        if not tid or tid in by_id:
            raise NativeP2Error(f"P2_NATIVE_DUPLICATE_OR_EMPTY_TALENT_ID:{tid}")
        row = int(entry.get("row", -1))
        col = int(entry.get("column", -1))
        cap = int(entry.get("max_rank", 0))
        if (
            not 0 <= row <= 6
            or not 0 <= col <= 3
            or not 1 <= cap <= 5
            or int(entry.get("points_required", -1)) != row * per_row
            or not str(entry.get("source_url", "")).startswith("https://")
        ):
            raise NativeP2Error(f"P2_NATIVE_INVALID_SOURCE_POSITION:{tid}")
        _tree_key(str(entry.get("tree_key", "")))
        deps = entry.get("requires", [])
        if not isinstance(deps, list) or len(deps) > 1:
            raise NativeP2Error(f"P2_NATIVE_INVALID_PREREQUISITES:{tid}")
        by_id[tid] = entry
    for tid, entry in by_id.items():
        for dep in entry.get("requires", []):
            if dep not in by_id:
                raise NativeP2Error(f"P2_NATIVE_UNKNOWN_PREREQUISITE:{tid}:{dep}")
            parent = by_id[dep]
            if (
                _tree_key(parent["tree_key"]) != _tree_key(entry["tree_key"])
                or int(parent["row"]) >= int(entry["row"])
            ):
                raise NativeP2Error(f"P2_NATIVE_NON_EARLIER_PREREQUISITE:{tid}:{dep}")
    rank_l0 = data.get("rank_l0", {})
    if not isinstance(rank_l0, dict) or set(rank_l0) - set(by_id):
        raise NativeP2Error("P2_NATIVE_UNKNOWN_SOURCE_RANK_L0")
    for tid, observation in rank_l0.items():
        cap = int(by_id[tid]["max_rank"])
        if (
            not str(observation.get("source_url", "")).startswith("https://")
            or not observation.get("context_uncertainty")
            or not observation.get("features")
        ):
            raise NativeP2Error(f"P2_NATIVE_RANK_L0_PROVENANCE_MISSING:{tid}")
        for feature in observation["features"]:
            values = feature.get("rank_values", [])
            if (
                not feature.get("domain")
                or not feature.get("target")
                or not feature.get("condition")
                or not isinstance(values, list)
                or not 1 <= len(values) <= cap
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value < 0
                    for value in values
                )
            ):
                raise NativeP2Error(f"P2_NATIVE_INVALID_RANK_L0_FEATURE:{tid}")
    data["_source_sha256"] = actual_digest
    data["_source_db"] = str(db)
    return data, actual_digest


def parse_druid_rust_layout(engine_root: Path | str) -> dict[str, list[dict[str, Any]]]:
    """Parse the selected engine's actual FOREVER_TREES; never use the legacy Python schema."""
    root = Path(engine_root).resolve()
    path = root / "src/classes/druid/prepare.rs"
    if not path.is_file():
        raise NativeP2Error(f"P2_NATIVE_RUST_LAYOUT_SOURCE_MISSING:{path}")
    source = path.read_text(encoding="utf-8")

    size_match = re.search(
        r"const\s+TALENT_TREE_SIZES\s*:\s*\[usize\s*;\s*3\]\s*=\s*\[(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]",
        source,
    )
    if not size_match:
        raise NativeP2Error("P2_NATIVE_RUST_TREE_SIZES_MISSING")
    expected_sizes = tuple(int(x) for x in size_match.groups())

    trees_match = re.search(
        r"pub\(crate\)\s+const\s+FOREVER_TREES\s*:\s*\[\s*&\[LayoutTalent\]\s*;\s*3\s*\]\s*=\s*\[(.*?)\];",
        source,
        re.S,
    )
    if not trees_match:
        raise NativeP2Error("P2_NATIVE_FOREVER_TREES_MISSING")
    tree_refs = re.findall(r"FOREVER_[A-Z_]+", trees_match.group(1))
    expected_refs = [
        "FOREVER_BALANCE",
        "FOREVER_FERAL_COMBAT",
        "FOREVER_RESTORATION",
    ]
    if tree_refs != expected_refs:
        raise NativeP2Error(f"P2_NATIVE_FOREVER_TREE_ORDER_MISMATCH:{tree_refs}")

    layout: dict[str, list[dict[str, Any]]] = {}
    all_fields: set[str] = set()
    for tree_key, constant in TREE_LAYOUT_CONSTANTS.items():
        array_match = re.search(
            rf"const\s+{constant}\s*:\s*&\[LayoutTalent\]\s*=\s*&\[(.*?)\];",
            source,
            re.S,
        )
        if not array_match:
            raise NativeP2Error(f"P2_NATIVE_LAYOUT_ARRAY_MISSING:{constant}")
        entries = []
        for kind, field, name, max_rank in LAYOUT_CALL_RE.findall(array_match.group(1)):
            if field in all_fields:
                raise NativeP2Error(f"P2_NATIVE_DUPLICATE_RUST_LAYOUT_FIELD:{field}")
            all_fields.add(field)
            entries.append({
                "field": field,
                "name": name,
                "max_rank": int(max_rank),
                "kind": kind,
            })
        if len(entries) != expected_sizes[TREE_ORDER.index(tree_key)]:
            raise NativeP2Error(
                f"P2_NATIVE_LAYOUT_SIZE_MISMATCH:{tree_key}:{len(entries)}:"
                f"{expected_sizes[TREE_ORDER.index(tree_key)]}"
            )
        layout[tree_key] = entries
    return layout


def validate_source_layout(
    source_data: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[str]]]:
    """Require source tree/row order to agree with the selected Rust layout."""
    by_field = {
        tree: {entry["field"]: entry for entry in entries}
        for tree, entries in layout.items()
    }
    source_by_id = {entry["talent_id"]: entry for entry in source_data["talents"]}
    for source in source_data["talents"]:
        tree = _tree_key(source["tree_key"])
        tid = source["talent_id"]
        native = by_field[tree].get(tid)
        if native is None:
            raise NativeP2Error(f"P2_NATIVE_MISSING_RUST_LAYOUT:{tree}:{tid}")
        if int(native["max_rank"]) != int(source["max_rank"]):
            raise NativeP2Error(
                f"P2_NATIVE_RANK_CAP_MISMATCH:{tid}:"
                f"source={source['max_rank']}:rust={native['max_rank']}"
            )
    order_receipts: dict[str, dict[str, list[str]]] = {}
    for tree in TREE_ORDER:
        source_order = [
            entry["talent_id"] for entry in sorted(
                (entry for entry in source_data["talents"]
                 if _tree_key(entry["tree_key"]) == tree),
                key=lambda item: (int(item["row"]), int(item["column"]), item["talent_id"]),
            )
        ]
        rust_order = [
            entry["field"] for entry in layout[tree]
            if entry["field"] in source_by_id
        ]
        if source_order != rust_order:
            raise NativeP2Error(
                f"P2_NATIVE_SOURCE_RUST_TREE_ORDER_MISMATCH:{tree}:"
                f"source={source_order}:rust={rust_order}"
            )
        order_receipts[tree] = {"source_order": source_order, "rust_order": rust_order}
    return order_receipts


def build_source_legal_witness(
    source_data: dict[str, Any],
    talent_id: str,
    rank: int,
    level: int = 60,
    bonus_points: int = 0,
) -> dict[str, int]:
    """Build a minimum legal witness from source row/tier/prerequisite facts."""
    by_id = {entry["talent_id"]: entry for entry in source_data["talents"]}
    if talent_id not in by_id:
        raise NativeP2Error(f"P2_NATIVE_SOURCE_TALENT_MISSING:{talent_id}")
    target = by_id[talent_id]
    rank = int(rank)
    if not 1 <= rank <= int(target["max_rank"]):
        raise NativeP2Error(f"P2_NATIVE_TARGET_RANK_OUT_OF_RANGE:{talent_id}:{rank}")
    allocation: dict[str, int] = {}
    per_row = int(source_data["points_per_row"])

    def lower_points(entry: dict[str, Any]) -> int:
        tree = _tree_key(entry["tree_key"])
        row = int(entry["row"])
        return sum(
            points
            for tid, points in allocation.items()
            if _tree_key(by_id[tid]["tree_key"]) == tree
            and int(by_id[tid]["row"]) < row
        )

    def add(tid: str, wanted: int, active: set[str]) -> None:
        entry = by_id.get(tid)
        if entry is None:
            raise NativeP2Error(f"P2_NATIVE_SOURCE_PREREQUISITE_MISSING:{tid}")
        cap = int(entry["max_rank"])
        if wanted < 0 or wanted > cap:
            raise NativeP2Error(f"P2_NATIVE_SOURCE_RANK_OUT_OF_RANGE:{tid}:{wanted}")
        if allocation.get(tid, 0) >= wanted:
            return
        if tid in active:
            raise NativeP2Error(f"P2_NATIVE_SOURCE_PREREQUISITE_CYCLE:{tid}")
        active.add(tid)
        for dep in entry.get("requires", []):
            add(dep, int(by_id[dep]["max_rank"]), active)
        required = int(entry["points_required"])
        while lower_points(entry) < required:
            tree = _tree_key(entry["tree_key"])
            row = int(entry["row"])
            candidates = [
                candidate for candidate in source_data["talents"]
                if _tree_key(candidate["tree_key"]) == tree
                and int(candidate["row"]) < row
                and allocation.get(candidate["talent_id"], 0) < int(candidate["max_rank"])
            ]
            candidates.sort(key=lambda item: (
                int(item["row"]), int(item["column"]), item["talent_id"]
            ))
            if not candidates:
                raise NativeP2Error(
                    f"P2_NATIVE_NO_TIER_WITNESS:{tid}:required={required}:"
                    f"actual={lower_points(entry)}"
                )
            filler = candidates[0]["talent_id"]
            add(filler, allocation.get(filler, 0) + 1, active)
        allocation[tid] = wanted
        active.remove(tid)

    add(talent_id, rank, set())
    budget = max(0, int(level) - 9) + int(bonus_points)
    spent = sum(allocation.values())
    if spent > budget:
        raise NativeP2Error(
            f"P2_NATIVE_POINT_BUDGET_EXCEEDED:{talent_id}:{spent}>{budget}"
        )
    for tid, points in allocation.items():
        entry = by_id[tid]
        for dep in entry.get("requires", []):
            if allocation.get(dep, 0) < int(by_id[dep]["max_rank"]):
                raise NativeP2Error(f"P2_NATIVE_PREREQUISITE_NOT_MET:{tid}:{dep}")
        if lower_points(entry) < int(entry["points_required"]):
            raise NativeP2Error(f"P2_NATIVE_TIER_NOT_MET:{tid}")
        if points > int(entry["max_rank"]):
            raise NativeP2Error(f"P2_NATIVE_RANK_CAP_EXCEEDED:{tid}")
    return allocation


def build_source_legal_rank_pair(
    source_data: dict[str, Any],
    talent_id: str,
    rank: int,
    level: int = 60,
    bonus_points: int = 0,
) -> tuple[dict[str, int], dict[str, int]]:
    after = build_source_legal_witness(source_data, talent_id, rank, level, bonus_points)
    before = dict(after)
    if rank == 1:
        before.pop(talent_id, None)
    else:
        before[talent_id] = int(rank) - 1
    return before, after


def serialize_source_allocation(
    source_data: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
    allocation: dict[str, int],
) -> str:
    """Serialize using exact Rust tree order and field positions."""
    by_id = {entry["talent_id"]: entry for entry in source_data["talents"]}
    positions = {
        tree: {entry["field"]: (index, int(entry["max_rank"]))
               for index, entry in enumerate(entries)}
        for tree, entries in layout.items()
    }
    values = {tree: [0] * len(layout[tree]) for tree in TREE_ORDER}
    for tid, raw_rank in allocation.items():
        if tid not in by_id:
            raise NativeP2Error(f"P2_NATIVE_ALLOCATION_UNKNOWN_SOURCE_TALENT:{tid}")
        source = by_id[tid]
        tree = _tree_key(source["tree_key"])
        found = positions[tree].get(tid)
        if found is None:
            raise NativeP2Error(f"P2_NATIVE_MISSING_RUST_LAYOUT:{tree}:{tid}")
        index, rust_cap = found
        rank = int(raw_rank)
        if rank < 0 or rank > rust_cap:
            raise NativeP2Error(f"P2_NATIVE_RUST_RANK_OUT_OF_RANGE:{tid}:{rank}")
        if rank > int(source["max_rank"]):
            raise NativeP2Error(f"P2_NATIVE_SOURCE_RANK_OUT_OF_RANGE:{tid}:{rank}")
        values[tree][index] = rank
    segments = ["".join(str(value) for value in values[tree]).rstrip("0") for tree in TREE_ORDER]
    nonempty = [index for index, segment in enumerate(segments) if segment]
    if not nonempty:
        raise NativeP2Error("P2_NATIVE_EMPTY_TALENT_ALLOCATION")
    return "-".join(segments[: max(nonempty) + 1])


def _git_output(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise NativeP2Error(f"P2_NATIVE_GIT_COMMAND_FAILED:{' '.join(args)}:{proc.stderr.strip()}")
    return proc.stdout.strip()


def verify_selected_engine_pin(engine_root: Path | str) -> str:
    engine = Path(engine_root).resolve()
    engine_sha = _git_output(["git", "rev-parse", "HEAD"], engine)
    gitlink = _git_output(
        ["git", "ls-tree", "HEAD", "integrations/mythicsim-rust/engine"],
        ROOT,
    )
    fields = gitlink.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise NativeP2Error("P2_NATIVE_SELECTED_ENGINE_GITLINK_MISSING")
    pinned_sha = fields[2]
    if engine_sha != pinned_sha:
        raise NativeP2Error(
            f"P2_NATIVE_SELECTED_ENGINE_PIN_MISMATCH:{engine_sha}!={pinned_sha}"
        )
    return engine_sha


def _run_prepare(
    binary: Path,
    engine_root: Path,
    tree: str,
    build: str,
    scenario: str,
) -> tuple[dict[str, Any], str]:
    fixture_name = "cat.request.json" if tree == "feral" else "balance.request.json"
    fixture = engine_root / "tests/classes/druid/prepare" / fixture_name
    if not fixture.is_file():
        raise NativeP2Error(f"P2_NATIVE_REQUEST_FIXTURE_MISSING:{fixture}")
    try:
        request = json.loads(fixture.read_text(encoding="utf-8"))
        player = request["raid"]["parties"][0]["players"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise NativeP2Error(f"P2_NATIVE_REQUEST_FIXTURE_INVALID:{fixture}") from exc
    if player.get("class") != "ClassDruid":
        raise NativeP2Error(f"P2_NATIVE_REQUEST_FIXTURE_CLASS_MISMATCH:{fixture}")
    player["talentsString"] = build
    with tempfile.TemporaryDirectory(prefix="forever-p2-native-") as tmp:
        temp = Path(tmp)
        request_path = temp / "request.json"
        output_path = temp / "prepared.json"
        request_path.write_text(json.dumps(request, separators=(",", ":")), encoding="utf-8")
        command = [
            str(binary), "prepare", "--request", str(request_path),
            "--outfile", str(output_path),
        ]
        proc = subprocess.run(command, text=True, capture_output=True, check=False, timeout=60)
        if proc.returncode != 0:
            raise NativeP2Error(
                f"P2_NATIVE_PREPARE_FAILED:{scenario}:"
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        if not output_path.is_file():
            raise NativeP2Error(f"P2_NATIVE_PREPARE_OUTPUT_MISSING:{scenario}")
        raw = output_path.read_bytes()
        try:
            prepared = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NativeP2Error(f"P2_NATIVE_PREPARE_OUTPUT_INVALID:{scenario}") from exc
        if not isinstance(prepared.get("player"), dict):
            raise NativeP2Error(f"P2_NATIVE_PREPARE_PLAYER_MISSING:{scenario}")
        return prepared, hashlib.sha256(raw).hexdigest()


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _stat_value(prepared: dict[str, Any], wanted: str) -> float:
    stats = prepared["player"].get("stats", {})
    target = _normalized_key(wanted)
    for key, value in stats.items():
        if _normalized_key(key) == target and isinstance(value, (int, float)):
            return float(value)
    raise NativeP2Error(f"P2_NATIVE_PREPARED_STAT_MISSING:{wanted}")


def _contains_spell_id(value: Any, spell_id: int) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _normalized_key(key) == "spellid" and item == spell_id:
                return True
            if _contains_spell_id(item, spell_id):
                return True
    elif isinstance(value, list):
        return any(_contains_spell_id(item, spell_id) for item in value)
    return False


def _contains_moonkin_aura(prepared: dict[str, Any]) -> bool:
    auras = prepared["player"].get("auras", [])
    return "moonkin form" in json.dumps(auras, sort_keys=True).lower()


def _source_observation(source_data: dict[str, Any], talent_id: str, rank: int) -> dict[str, Any]:
    observation = source_data.get("rank_l0", {}).get(talent_id)
    if not observation:
        raise NativeP2Error(f"P2_NATIVE_CHECKPOINT_SOURCE_L0_MISSING:{talent_id}")
    if not any(len(feature.get("rank_values", [])) >= rank
               for feature in observation["features"]):
        raise NativeP2Error(f"P2_NATIVE_CHECKPOINT_SOURCE_L0_RANK_MISSING:{talent_id}:{rank}")
    return observation


def _probe_predatory_strikes(
    source_data: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
    engine_root: Path,
    binary: Path,
    engine_sha: str,
    rank: int,
    level: int,
) -> dict[str, Any]:
    observation = _source_observation(source_data, "predatory_strikes", rank)
    before_alloc, after_alloc = build_source_legal_rank_pair(
        source_data, "predatory_strikes", rank, level
    )
    before_build = serialize_source_allocation(source_data, layout, before_alloc)
    after_build = serialize_source_allocation(source_data, layout, after_alloc)
    before, before_sha = _run_prepare(binary, engine_root, "feral", before_build, f"p2-predatory-{rank}-before")
    after, after_sha = _run_prepare(binary, engine_root, "feral", after_build, f"p2-predatory-{rank}-after")

    matching = [
        feature for feature in observation["features"]
        if ("attack_power" in str(feature["domain"]).lower()
            or "attack_power" in str(feature["target"]).lower())
        and len(feature.get("rank_values", [])) >= rank
    ]
    if not matching:
        raise NativeP2Error("P2_NATIVE_PREDATORY_ATTACK_POWER_SOURCE_EFFECT_MISSING")
    expected_delta = 0.0
    for feature in matching:
        values = feature["rank_values"]
        current = float(values[rank - 1])
        previous = float(values[rank - 2]) if rank > 1 else 0.0
        delta = current if ("per_rank" in str(feature["domain"]).lower()
                           or "increment" in str(feature["domain"]).lower()) else current - previous
        if "per_level" in str(feature["domain"]).lower() or "per_level" in str(feature["target"]).lower():
            delta *= level
        expected_delta += delta
    actual_delta = (
        _stat_value(after, "AttackPower") - _stat_value(before, "AttackPower")
    )
    passed = math.isclose(actual_delta, expected_delta, rel_tol=0.0, abs_tol=1e-6)
    return {
        "talent_id": "predatory_strikes",
        "rank": rank,
        "status": "PASS" if passed else "FAIL",
        "executor": "selected_rust_forever_engine_prepare",
        "engine_sha": engine_sha,
        "source_sha256": source_data["_source_sha256"],
        "source_url": observation["source_url"],
        "source_context_uncertainty": observation["context_uncertainty"],
        "source_features": observation["features"],
        "before_talents_string": before_build,
        "after_talents_string": after_build,
        "before_prepared_sha256": before_sha,
        "after_prepared_sha256": after_sha,
        "observed": {
            "stat": "AttackPower",
            "before": _stat_value(before, "AttackPower"),
            "after": _stat_value(after, "AttackPower"),
            "actual_delta": actual_delta,
            "expected_delta_from_checkpoint_source_l0": expected_delta,
        },
    }


def _probe_moonkin_form(
    source_data: dict[str, Any],
    layout: dict[str, list[dict[str, Any]]],
    engine_root: Path,
    binary: Path,
    engine_sha: str,
    level: int,
) -> dict[str, Any]:
    observation = _source_observation(source_data, "moonkin_form", 1)
    before_alloc, after_alloc = build_source_legal_rank_pair(
        source_data, "moonkin_form", 1, level
    )
    before_build = serialize_source_allocation(source_data, layout, before_alloc)
    after_build = serialize_source_allocation(source_data, layout, after_alloc)
    before, before_sha = _run_prepare(binary, engine_root, "balance", before_build, "p2-moonkin-before")
    after, after_sha = _run_prepare(binary, engine_root, "balance", after_build, "p2-moonkin-after")
    before_aura = _contains_moonkin_aura(before)
    after_aura = _contains_moonkin_aura(after)
    before_spell = _contains_spell_id(before["player"].get("spells", []), 24858)
    after_spell = _contains_spell_id(after["player"].get("spells", []), 24858)
    passed = not before_aura and after_aura and not before_spell and after_spell
    return {
        "talent_id": "moonkin_form",
        "rank": 1,
        "status": "PASS" if passed else "FAIL",
        "executor": "selected_rust_forever_engine_prepare",
        "engine_sha": engine_sha,
        "source_sha256": source_data["_source_sha256"],
        "source_url": observation["source_url"],
        "source_context_uncertainty": observation["context_uncertainty"],
        "source_features": observation["features"],
        "before_talents_string": before_build,
        "after_talents_string": after_build,
        "before_prepared_sha256": before_sha,
        "after_prepared_sha256": after_sha,
        "observed": {
            "aura_absent_before_present_after": not before_aura and after_aura,
            "spell_24858_absent_before_present_after": not before_spell and after_spell,
        },
    }


def run_smoke(
    engine_root: Path | str,
    binary: Path | str,
    source_db: Path | str = DEFAULT_DB,
    level: int = 60,
) -> dict[str, Any]:
    engine_root = Path(engine_root).resolve()
    binary = Path(binary).resolve()
    if not binary.is_file():
        raise NativeP2Error(f"P2_NATIVE_ENGINE_BINARY_MISSING:{binary}")
    engine_sha = verify_selected_engine_pin(engine_root)
    source_data, source_sha = load_source_positions(source_db, level)
    layout = parse_druid_rust_layout(engine_root)
    source_rust_tree_order = validate_source_layout(source_data, layout)

    rank_results = [
        _probe_predatory_strikes(source_data, layout, engine_root, binary, engine_sha, rank, level)
        for rank in (1, 2, 3)
    ]
    rank_results.append(
        _probe_moonkin_form(source_data, layout, engine_root, binary, engine_sha, level)
    )
    pass_count = sum(result["status"] == "PASS" for result in rank_results)
    return {
        "scope": "NATIVE_P2_RANK_PROBE_DIAGNOSTIC_NOT_GATE",
        "class": "druid",
        "level": int(level),
        "source_build": source_data["source_build"],
        "source_sha256": source_sha,
        "selected_engine_sha": engine_sha,
        "production_engine": "msim",
        "source_rust_tree_order": source_rust_tree_order,
        "rank_results": rank_results,
        "pass_count": pass_count,
        "applicable_probe_count": len(rank_results),
        "p2_gate_acceptance": False,
        "m1_recording": False,
        "next_integration": "wire per-rank receipts into wf_gate_p2_live.py and the P2 validator; expand beyond these four source-backed probes",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--level", type=int, default=60)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_smoke(args.engine_root, args.binary, args.source_db, args.level)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if report["pass_count"] != report["applicable_probe_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

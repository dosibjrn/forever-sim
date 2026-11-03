"""Selected-Rust Druid talent rank-pair diagnostic for the P2 gate.

This module deliberately does not implement talent legality or effect semantics.
It serializes an already source-validated rank pair against the exact selected
Rust engine layout, then asks that engine to execute both requests with an
explicit deterministic balanced RNG mode.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from enum import Enum
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NATIVE_INTEGRATION = _REPO_ROOT / "integrations" / "mythicsim-rust"
if str(_NATIVE_INTEGRATION) not in sys.path:
    sys.path.insert(0, str(_NATIVE_INTEGRATION))

import p73_talent_search_v2 as _native_runner


class NativeP2ProbeError(RuntimeError):
    """The selected engine layout or a source rank pair cannot be serialized."""


class NativeRngMode(str, Enum):
    BALANCED = "balanced"


_TREE_ARRAYS = (
    ("balance", "FOREVER_BALANCE"),
    ("feral", "FOREVER_FERAL_COMBAT"),
    ("restoration", "FOREVER_RESTORATION"),
)
_ENTRY = re.compile(
    r'(?:new_talent|talent)\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(\d+)\s*\)\s*,?'
)


def parse_native_druid_layout(engine_root: str | Path) -> dict[str, list[dict[str, object]]]:
    """Read the talent order/rank caps from the selected Rust source itself."""
    root = Path(engine_root)
    source_path = root / "src" / "classes" / "druid" / "prepare.rs"
    if not source_path.is_file():
        raise NativeP2ProbeError(f"NATIVE_DRUID_LAYOUT_SOURCE_MISSING:{source_path}")
    source = source_path.read_text(encoding="utf-8")

    tree_decl = re.search(
        r"FOREVER_TREES\s*:\s*\[\s*&\[\s*LayoutTalent\s*\]\s*;\s*3\s*\]"
        r"\s*=\s*\[(.*?)\]\s*;",
        source,
        re.S,
    )
    if tree_decl is None:
        raise NativeP2ProbeError("NATIVE_DRUID_TREE_ORDER_DECLARATION_MISSING")
    declared_order = re.findall(r"FOREVER_[A-Z_]+", tree_decl.group(1))
    expected_order = [array_name for _, array_name in _TREE_ARRAYS]
    if declared_order != expected_order:
        raise NativeP2ProbeError(
            "NATIVE_DRUID_TREE_ORDER_MISMATCH:"
            + ",".join(declared_order)
            + "!="
            + ",".join(expected_order)
        )

    layout: dict[str, list[dict[str, object]]] = {}
    all_fields: set[str] = set()
    for tree_key, array_name in _TREE_ARRAYS:
        match = re.search(
            rf"const\s+{array_name}\s*:\s*&\[\s*LayoutTalent\s*\]"
            rf"\s*=\s*&\[(.*?)\]\s*;",
            source,
            re.S,
        )
        if match is None:
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_ARRAY_MISSING:{array_name}")
        body = re.sub(r"(?m)//.*$", "", match.group(1))
        entries = list(_ENTRY.finditer(body))
        residue = _ENTRY.sub("", body)
        residue = re.sub(r"[\s,]+", "", residue)
        if residue:
            raise NativeP2ProbeError(
                f"NATIVE_DRUID_TALENT_ARRAY_PARSE_INCOMPLETE:{array_name}:{residue[:80]}"
            )
        parsed: list[dict[str, object]] = []
        for entry in entries:
            field, name, max_rank = entry.groups()
            if field in all_fields:
                raise NativeP2ProbeError(f"NATIVE_DRUID_DUPLICATE_TALENT_FIELD:{field}")
            all_fields.add(field)
            parsed.append(
                {"field": field, "name": name, "max_rank": int(max_rank)}
            )
        if not parsed:
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_ARRAY_EMPTY:{array_name}")
        layout[tree_key] = parsed
    return layout


def encode_native_druid_talents(
    selection: Mapping[str, int], engine_root: str | Path
) -> str:
    """Encode source talent IDs using the selected Rust engine's field order."""
    if not isinstance(selection, Mapping):
        raise NativeP2ProbeError("SOURCE_TALENT_SELECTION_NOT_A_MAPPING")
    layout = parse_native_druid_layout(engine_root)
    fields: dict[str, tuple[int, int, int]] = {}
    arrays: list[list[int]] = []
    for tree_index, (tree_key, entries) in enumerate(layout.items()):
        arrays.append([0] * len(entries))
        for index, entry in enumerate(entries):
            fields[str(entry["field"])] = (
                tree_index,
                index,
                int(entry["max_rank"]),
            )

    for talent_id, raw_rank in selection.items():
        if type(raw_rank) is not int:
            raise NativeP2ProbeError(f"SOURCE_TALENT_RANK_NOT_INTEGER:{talent_id}")
        rank = raw_rank
        if rank < 0:
            raise NativeP2ProbeError(f"SOURCE_TALENT_RANK_NEGATIVE:{talent_id}:{rank}")
        if rank == 0:
            continue
        if talent_id not in fields:
            raise NativeP2ProbeError(f"NATIVE_TALENT_ID_UNMAPPED:{talent_id}")
        tree_index, index, max_rank = fields[talent_id]
        if rank > max_rank:
            raise NativeP2ProbeError(
                f"NATIVE_TALENT_RANK_EXCEEDS_CAP:{talent_id}:{rank}>{max_rank}"
            )
        arrays[tree_index][index] = rank

    return "-".join("".join(str(rank) for rank in tree) for tree in arrays)


def _druid_player(request: dict) -> dict:
    try:
        player = request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeP2ProbeError("NATIVE_DRUID_REQUEST_PLAYER_PATH_MISSING") from exc
    if player.get("class") != "ClassDruid":
        raise NativeP2ProbeError(
            f"NATIVE_P2_REQUEST_NOT_DRUID:{player.get('class')!r}"
        )
    if not isinstance(request.get("simOptions"), dict):
        raise NativeP2ProbeError("NATIVE_P2_REQUEST_SIM_OPTIONS_MISSING")
    return player


def _selection_delta(
    before: Mapping[str, int],
    after: Mapping[str, int],
    target_talent_id: str,
    target_rank: int,
) -> None:
    keys = set(before) | set(after)
    changed = {
        key for key in keys
        if int(before.get(key, 0)) != int(after.get(key, 0))
    }
    if changed != {target_talent_id}:
        raise NativeP2ProbeError(
            "NATIVE_P2_PAIR_CHANGES_MORE_THAN_TARGET:"
            + ",".join(sorted(changed))
        )
    if int(before.get(target_talent_id, 0)) != target_rank - 1:
        raise NativeP2ProbeError("NATIVE_P2_CONTROL_RANK_MISMATCH")
    if int(after.get(target_talent_id, 0)) != target_rank:
        raise NativeP2ProbeError("NATIVE_P2_CANDIDATE_RANK_MISMATCH")


def _prepare_request(binary_path: Path, request: dict) -> dict[str, object]:
    """Run the selected Rust prepare command on the exact paired request."""
    with tempfile.TemporaryDirectory(prefix="forever-p2-native-prepare-") as temp:
        temp_root = Path(temp)
        request_path = temp_root / "request.json"
        prepared_path = temp_root / "prepared.json"
        request_path.write_text(
            json.dumps(request, sort_keys=True), encoding="utf-8"
        )
        started = time.monotonic()
        completed = subprocess.run(
            [
                str(binary_path),
                "prepare",
                "--request",
                str(request_path),
                "--outfile",
                str(prepared_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        elapsed = time.monotonic() - started
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
            raise NativeP2ProbeError(
                f"NATIVE_PREPARE_REFUSED:{completed.returncode}:{detail}"
            )
        if not prepared_path.is_file():
            raise NativeP2ProbeError("NATIVE_PREPARE_OUTPUT_MISSING")
        prepared_bytes = prepared_path.read_bytes()
        try:
            prepared = json.loads(prepared_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NativeP2ProbeError("NATIVE_PREPARE_OUTPUT_INVALID_JSON") from exc
        if not isinstance(prepared, dict):
            raise NativeP2ProbeError("NATIVE_PREPARE_OUTPUT_NOT_OBJECT")
        return {
            "prepared_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
            "prepare_elapsed_seconds": float(elapsed),
            "prepared_top_level_keys": sorted(prepared),
        }


def run_native_rank_pair(
    *,
    binary: str | Path,
    engine_root: str | Path,
    scenario: str,
    before_selection: Mapping[str, int],
    after_selection: Mapping[str, int],
    target_talent_id: str,
    target_rank: int,
    rng_mode: NativeRngMode,
    iterations: int = 100,
    seed: int = 647003,
) -> dict[str, object]:
    """Run the same native Druid request with/without one source-legal rank.

    The balanced RNG mode is an explicit call argument, never an environment
    default. A PASS means the selected native simulator completed both gated
    requests and the rank increased the fixture's raid-DPS observable.
    """
    if rng_mode is not NativeRngMode.BALANCED:
        raise NativeP2ProbeError("NATIVE_P2_REQUIRES_EXPLICIT_BALANCED_RNG")
    if scenario not in {"balance", "cat"}:
        raise NativeP2ProbeError(f"NATIVE_P2_SCENARIO_UNSUPPORTED:{scenario}")
    if isinstance(iterations, bool) or int(iterations) < 1:
        raise NativeP2ProbeError("NATIVE_P2_ITERATIONS_INVALID")
    if isinstance(target_rank, bool) or int(target_rank) < 1:
        raise NativeP2ProbeError("NATIVE_P2_TARGET_RANK_INVALID")
    _selection_delta(before_selection, after_selection, target_talent_id, int(target_rank))

    binary_path = Path(binary)
    root = Path(engine_root)
    if not binary_path.is_file():
        return {
            "status": "BLOCKED",
            "reason": "SELECTED_RUST_BINARY_MISSING",
            "scenario": scenario,
            "rng_mode": rng_mode.value,
        }
    request_path = (
        root / "tests" / "classes" / "druid" / "prepare" / f"{scenario}.request.json"
    )
    if not request_path.is_file():
        return {
            "status": "BLOCKED",
            "reason": f"NATIVE_DRUID_REQUEST_FIXTURE_MISSING:{scenario}",
            "scenario": scenario,
            "rng_mode": rng_mode,
        }

    base_request = json.loads(request_path.read_text(encoding="utf-8"))
    _druid_player(base_request)
    before_string = encode_native_druid_talents(before_selection, root)
    after_string = encode_native_druid_talents(after_selection, root)
    if before_string == after_string:
        raise NativeP2ProbeError("NATIVE_P2_TALENT_STRINGS_IDENTICAL")

    def execute(talents_string: str) -> dict[str, object]:
        request = copy.deepcopy(base_request)
        _druid_player(request)["talentsString"] = talents_string
        request["simOptions"]["debugFirstIteration"] = False
        # The native runner writes iterations/seed and passes --rng-mode
        # explicitly to sim --request --gate.
        prepared_receipt = _prepare_request(binary_path, request)
        score, report, elapsed, payload_sha = _native_runner.run(
            str(binary_path),
            request,
            int(iterations),
            int(seed),
            rng_mode.value,
            time.monotonic() + 120.0,
        )
        if not isinstance(score, (int, float)):
            raise NativeP2ProbeError("NATIVE_P2_DPS_NOT_NUMERIC")
        return {
            "dps": float(score),
            "elapsed_seconds": float(elapsed),
            "request_sha256": str(payload_sha),
            "engine_identity": report.get("identity"),
            **prepared_receipt,
        }

    try:
        before = execute(before_string)
        after = execute(after_string)
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "reason": f"NATIVE_SIM_EXECUTION_FAILED:{type(exc).__name__}:{exc}",
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "talents_string_before": before_string,
            "talents_string_after": after_string,
            "rng_mode": rng_mode,
            "iterations": int(iterations),
            "seed": int(seed),
        }

    before_identity = before.get("engine_identity")
    after_identity = after.get("engine_identity")
    if not before_identity or not after_identity:
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_ENGINE_IDENTITY_MISSING",
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "before": before,
            "after": after,
            "rng_mode": rng_mode,
            "iterations": int(iterations),
            "seed": int(seed),
        }
    if before.get("request_sha256") == after.get("request_sha256"):
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_PAIRED_REQUEST_PAYLOADS_IDENTICAL",
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "before": before,
            "after": after,
            "rng_mode": rng_mode,
            "iterations": int(iterations),
            "seed": int(seed),
        }
    if before_identity != after_identity:
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_ENGINE_IDENTITY_CHANGED_BETWEEN_PAIRED_RUNS",
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "before": before,
            "after": after,
            "rng_mode": rng_mode,
            "iterations": int(iterations),
            "seed": int(seed),
        }

    delta = float(after["dps"]) - float(before["dps"])
    return {
        "status": "PASS" if delta > 1e-9 else "FAIL",
        "reason": "NATIVE_DPS_INCREASE_OBSERVED"
        if delta > 1e-9
        else "NATIVE_DPS_DID_NOT_INCREASE",
        "scenario": scenario,
        "target_talent_id": target_talent_id,
        "target_rank": int(target_rank),
        "talents_string_before": before_string,
        "talents_string_after": after_string,
        "before": before,
        "after": after,
        "delta_dps": delta,
        "rng_mode": rng_mode,
        "iterations": int(iterations),
        "seed": int(seed),
        "source_layout_sha256": hashlib.sha256(
            (root / "src" / "classes" / "druid" / "prepare.rs").read_bytes()
        ).hexdigest(),
        "accepted_for_p2": False,
    }

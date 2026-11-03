"""Selected-Rust Druid talent rank-pair client for P2 diagnostics.

This module does not implement talent legality or effect semantics. It encodes
proposed candidate pairs against the selected Rust layout and delegates
legality, preparation and execution to that engine with explicit balanced RNG.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
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
    r'(?P<kind>new_talent|talent)\(\s*"(?P<field>[^"]+)"\s*,\s*"(?P<name>[^"]+)"'
    r'\s*,\s*(?P<max_ranks>\d+)\s*\)\s*,?'
)
_NATIVE_LAYOUT_COMMAND_MISSING = "expected sim, prepare, bench, check or version"


def parse_native_druid_layout(engine_root: str | Path) -> dict[str, list[dict[str, object]]]:
    """Read native layout metadata for wire encoding only; never decide legality."""
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
        for position, entry in enumerate(entries):
            kind = entry.group("kind")
            field = entry.group("field")
            name = entry.group("name")
            max_ranks = int(entry.group("max_ranks"))
            if field in all_fields:
                raise NativeP2ProbeError(f"NATIVE_DRUID_DUPLICATE_TALENT_FIELD:{field}")
            all_fields.add(field)
            parsed.append({
                "position": position,
                "field": field,
                "name": name,
                "max_ranks": max_ranks,
                "in_proto": kind == "talent",
            })
        if not parsed:
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_ARRAY_EMPTY:{array_name}")
        layout[tree_key] = parsed
    return layout


def encode_native_druid_talents(
    selection: Mapping[str, int],
    engine_root: str | Path,
    *,
    layout: dict[str, list[dict[str, object]]] | None = None,
    binary: str | Path | None = None,
) -> str:
    """Encode candidate IDs using native layout metadata; native prepare decides legality."""
    if not isinstance(selection, Mapping):
        raise NativeP2ProbeError("SOURCE_TALENT_SELECTION_NOT_A_MAPPING")
    if layout is None:
        layout, _ = load_native_druid_layout(engine_root, binary=binary)
    # This is only a wire encoder. The selected Rust prepare path, not
    # Python, owns the talent rank ceiling and game-legality decision.
    fields: dict[str, tuple[int, int]] = {}
    arrays: list[list[int]] = []
    for tree_index, (tree_key, entries) in enumerate(layout.items()):
        arrays.append([0] * len(entries))
        for index, entry in enumerate(entries):
            fields[str(entry["field"])] = (tree_index, index)

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
        # The native talent-string wire format has one decimal digit per
        # position. Reject only values that cannot be represented on the wire;
        # a representable but illegal rank must reach native preparation.
        if rank > 9:
            raise NativeP2ProbeError(
                f"NATIVE_TALENT_RANK_NOT_SINGLE_DIGIT:{talent_id}:{rank}"
            )
        tree_index, index = fields[talent_id]
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

def _request_player(request: dict) -> dict:
    """Extract the request player without making a class/game-legality decision."""
    try:
        player = request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeP2ProbeError("NATIVE_REQUEST_PLAYER_PATH_MISSING") from exc
    if not isinstance(player, dict):
        raise NativeP2ProbeError("NATIVE_REQUEST_PLAYER_INVALID")
    if not isinstance(request.get("simOptions"), dict):
        raise NativeP2ProbeError("NATIVE_REQUEST_SIM_OPTIONS_MISSING")
    return player


def _json_object(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _native_layout_payload(
    payload: dict,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, str]]:
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_SCHEMA_VERSION_INVALID")
    if payload.get("class") != "druid":
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_CLASS_MISMATCH")
    source_revision = payload.get("source_revision")
    client_build = payload.get("client_build")
    if not isinstance(source_revision, str) or not source_revision.strip():
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_SOURCE_REVISION_MISSING")
    if not isinstance(client_build, str) or not client_build.strip():
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_CLIENT_BUILD_MISSING")
    trees = payload.get("trees")
    if not isinstance(trees, list) or len(trees) != len(_TREE_ARRAYS):
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_TREE_COUNT_INVALID")

    layout: dict[str, list[dict[str, object]]] = {}
    all_fields: set[str] = set()
    for tree_index, (tree_key, _array_name) in enumerate(_TREE_ARRAYS):
        tree = trees[tree_index]
        if not isinstance(tree, dict):
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_TREE_INVALID:{tree_index}")
        if tree.get("tree_index") != tree_index or tree.get("tree_key") != tree_key:
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_TREE_ORDER_INVALID:{tree_index}")
        entries = tree.get("talents")
        if not isinstance(entries, list) or not entries:
            raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_TREE_EMPTY:{tree_key}")
        parsed: list[dict[str, object]] = []
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_ENTRY_INVALID:{tree_key}:{position}")
            field = entry.get("field")
            name = entry.get("name")
            max_ranks = entry.get("max_ranks")
            in_proto = entry.get("in_proto")
            if type(entry.get("position")) is not int or entry.get("position") != position:
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_POSITION_INVALID:{tree_key}:{position}")
            if not isinstance(field, str) or not field.strip():
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_FIELD_MISSING:{tree_key}:{position}")
            if not isinstance(name, str) or not name.strip():
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_NAME_MISSING:{tree_key}:{position}")
            if type(max_ranks) is not int:
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_MAX_RANKS_TYPE_INVALID:{field}")
            if type(in_proto) is not bool:
                raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_PROTO_FLAG_INVALID:{field}")
            if field in all_fields:
                raise NativeP2ProbeError(f"NATIVE_DRUID_DUPLICATE_TALENT_FIELD:{field}")
            all_fields.add(field)
            parsed.append({
                "position": position,
                "field": field,
                "name": name,
                "max_ranks": max_ranks,
                "in_proto": in_proto,
            })
        layout[tree_key] = parsed
    return layout, {
        "source_revision": source_revision,
        "client_build": client_build,
    }


def load_native_druid_layout(
    engine_root: str | Path,
    *,
    binary: str | Path | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, str | None]]:
    """Prefer the selected binary's typed layout API; source parsing is legacy-only.

    The compatibility fallback is used only when the selected binary predates
    the read-only CLI command. It never decides rank legality; native prepare
    still receives and classifies every representable candidate.
    """
    root = Path(engine_root).resolve()
    if binary is None:
        return parse_native_druid_layout(root), {
            "source": "selected_rust_source_compatibility",
            "source_revision": None,
            "client_build": None,
        }
    binary_path = Path(binary).resolve()
    if not binary_path.is_file():
        return parse_native_druid_layout(root), {
            "source": "selected_rust_source_compatibility",
            "source_revision": None,
            "client_build": None,
        }
    try:
        completed = subprocess.run(
            [str(binary_path), "talent-layout", "--class", "druid"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_CLI_TIMEOUT") from exc
    except OSError as exc:
        raise NativeP2ProbeError(f"NATIVE_DRUID_TALENT_LAYOUT_CLI_EXEC_FAILED:{exc}") from exc
    if completed.returncode != 0:
        output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        if _NATIVE_LAYOUT_COMMAND_MISSING in output:
            return parse_native_druid_layout(root), {
                "source": "selected_rust_source_compatibility",
                "source_revision": None,
                "client_build": None,
            }
        raise NativeP2ProbeError(
            f"NATIVE_DRUID_TALENT_LAYOUT_CLI_FAILED:{completed.returncode}:{output[-500:]}"
        )
    payload = _json_object(completed.stdout or "")
    if payload is None:
        raise NativeP2ProbeError("NATIVE_DRUID_TALENT_LAYOUT_CLI_INVALID_JSON")
    layout, metadata = _native_layout_payload(payload)
    metadata["source"] = "native_cli"
    return layout, metadata


def prepare_native_request(
    *,
    binary: str | Path,
    request: dict,
    scenario: str,
    deadline: float,
) -> dict[str, object]:
    """Forward any class's candidate request to the selected prepare CLI.

    This shared P1/P2 transport validates only the request envelope. It does
    not whitelist classes or decide game legality; the result preserves the
    native PreparedV2 object or its structured refusal.
    """
    binary_path = Path(binary)
    if not binary_path.is_file():
        return {"status": "BLOCKED", "stage": "prepare",
                "reason": "SELECTED_RUST_BINARY_MISSING"}
    if not isinstance(scenario, str) or not scenario.strip() or len(scenario) > 200:
        raise NativeP2ProbeError("NATIVE_P2_SCENARIO_ID_INVALID")

    payload = copy.deepcopy(request)
    player = _request_player(payload)
    options = payload["simOptions"]
    if isinstance(options.get("iterations"), bool) or not isinstance(options.get("iterations"), int) or options["iterations"] < 1:
        raise NativeP2ProbeError("NATIVE_P2_PREPARE_ITERATIONS_INVALID")
    options["debugFirstIteration"] = False

    with tempfile.TemporaryDirectory(prefix="forever-native-p2-") as directory:
        request_path = Path(directory) / "request.json"
        prepared_path = Path(directory) / "prepared.json"
        request_path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_P2_PREPARE_DEADLINE_EXPIRED"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    str(binary_path), "prepare", "--request", str(request_path),
                    "--outfile", str(prepared_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.001, deadline - time.monotonic()),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": f"NATIVE_PREPARE_CLI_FAILED:{type(exc).__name__}:{exc}"}

        elapsed = round(time.monotonic() - started, 6)
        if completed.returncode != 0:
            refusal = _json_object(completed.stdout or "")
            if refusal is not None and refusal.get("prepared") is False:
                details = refusal.get("refusal")
                details = details if isinstance(details, dict) else {}
                code = details.get("code")
                status = (
                    # The Druid Rust preparation emits "talents" for
                    # invalid layout/rank input, not unsupported mechanics.
                    "INVALID" if code in {"request", "talents"}
                    else "ERROR" if code == "prepare_fault"
                    else "UNSUPPORTED"
                )
                return {
                    "status": status,
                    "stage": "prepare",
                    "reason": str(details.get("reason") or code or "NATIVE_PREPARE_REFUSED"),
                    "refusal": details,
                    "elapsed_seconds": elapsed,
                }
            return {
                "status": "ERROR",
                "stage": "prepare",
                "reason": "NATIVE_PREPARE_FAILED_WITHOUT_STRUCTURED_REFUSAL",
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-700:],
                "stderr_tail": (completed.stderr or "")[-700:],
                "elapsed_seconds": elapsed,
            }
        if not prepared_path.is_file():
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_MISSING",
                    "stdout_tail": (completed.stdout or "")[-700:],
                    "stderr_tail": (completed.stderr or "")[-700:],
                    "elapsed_seconds": elapsed}
        raw = prepared_path.read_bytes()
        try:
            prepared = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": f"NATIVE_PREPARE_OUTPUT_INVALID_JSON:{exc}",
                    "elapsed_seconds": elapsed}
        if (not isinstance(prepared, dict)
                or prepared.get("schema_version") != 2
                or prepared.get("contract") != "forever-prepared"):
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_CONTRACT_MISMATCH",
                    "elapsed_seconds": elapsed}
        reference = prepared.get("reference")
        prepared_player = prepared.get("player")
        if (not isinstance(reference, dict)
                or not isinstance(reference.get("engine_revision"), str)
                or not reference["engine_revision"].strip()
                or not isinstance(prepared_player, dict)
                or prepared_player.get("talents_string") != player.get("talentsString")
                or not isinstance(prepared_player.get("talents"), dict)):
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_IDENTITY_MISMATCH",
                    "elapsed_seconds": elapsed}
        return {
            "status": "PREPARED",
            "stage": "prepare",
            "engine_identity": reference["engine_revision"],
            "request_sha256": prepared.get("request_sha256"),
            "prepared_sha256": hashlib.sha256(raw).hexdigest(),
            "elapsed_seconds": elapsed,
            "prepared": prepared,
        }


def _compact_prepare_receipt(result: dict) -> dict[str, object]:
    keys = (
        "status", "stage", "reason", "engine_identity", "request_sha256",
        "prepared_sha256", "elapsed_seconds", "refusal", "returncode",
        "stdout_tail", "stderr_tail", "talent_layout_source",
        "talent_layout_source_revision", "talent_layout_client_build",
    )
    return {key: result[key] for key in keys if key in result}


def run_native_prepare_pair(
    *,
    binary: str | Path,
    engine_root: str | Path,
    scenario: str,
    before_selection: Mapping[str, int],
    after_selection: Mapping[str, int],
    target_talent_id: str,
    target_rank: int,
    timeout_seconds: float = 120.0,
    iterations: int = 1,
    seed: int = 647003,
) -> dict[str, object]:
    """Return structured selected-Rust PreparedV2 receipts for a rank pair.

    This is an execution adapter, not a legality validator or a P2 PASS.
    MythicSim Rust alone determines rank legality, point budgets and
    prerequisites. This adapter checks only the rank-pair request shape.
    """
    if scenario not in {"balance", "cat"}:
        raise NativeP2ProbeError(f"NATIVE_P2_SCENARIO_UNSUPPORTED:{scenario}")
    if isinstance(target_rank, bool) or type(target_rank) is not int or target_rank < 1:
        raise NativeP2ProbeError("NATIVE_P2_TARGET_RANK_INVALID")
    if isinstance(iterations, bool) or type(iterations) is not int or iterations < 1:
        raise NativeP2ProbeError("NATIVE_P2_ITERATIONS_INVALID")
    if isinstance(seed, bool) or type(seed) is not int:
        raise NativeP2ProbeError("NATIVE_P2_SEED_INVALID")
    if timeout_seconds <= 0:
        raise NativeP2ProbeError("NATIVE_P2_TIMEOUT_INVALID")
    _selection_delta(before_selection, after_selection, target_talent_id, target_rank)

    root = Path(engine_root)
    binary_path = Path(binary)
    if not binary_path.is_file():
        return {"status": "BLOCKED", "reason": "SELECTED_RUST_BINARY_MISSING",
                "accepted_for_p2": False}
    try:
        binary_path.resolve().relative_to(root.resolve())
    except ValueError:
        return {"status": "BLOCKED", "reason": "BINARY_NOT_FROM_SELECTED_ENGINE_ROOT",
                "accepted_for_p2": False}

    request_path = (
        root / "tests" / "classes" / "druid" / "prepare" / f"{scenario}.request.json"
    )
    if not request_path.is_file():
        return {"status": "BLOCKED",
                "reason": f"NATIVE_DRUID_REQUEST_FIXTURE_MISSING:{scenario}",
                "accepted_for_p2": False}
    base_request = json.loads(request_path.read_text(encoding="utf-8"))
    _druid_player(base_request)
    layout, layout_metadata = load_native_druid_layout(root, binary=binary_path)
    layout_receipt = {
        "talent_layout_source": layout_metadata.get("source"),
        "talent_layout_source_revision": layout_metadata.get("source_revision"),
        "talent_layout_client_build": layout_metadata.get("client_build"),
    }
    before_string = encode_native_druid_talents(
        before_selection, root, layout=layout
    )
    after_string = encode_native_druid_talents(
        after_selection, root, layout=layout
    )
    if before_string == after_string:
        raise NativeP2ProbeError("NATIVE_P2_TALENT_STRINGS_IDENTICAL")

    before_request = copy.deepcopy(base_request)
    after_request = copy.deepcopy(base_request)
    _druid_player(before_request)["talentsString"] = before_string
    _druid_player(after_request)["talentsString"] = after_string
    for request in (before_request, after_request):
        request["simOptions"]["iterations"] = int(iterations)
        request["simOptions"]["randomSeed"] = str(int(seed))
        request["simOptions"]["debugFirstIteration"] = False
    deadline = time.monotonic() + timeout_seconds
    before = prepare_native_request(
        binary=binary_path,
        request=before_request,
        scenario=f"native-p2-{scenario}-{target_talent_id}-{target_rank}-control",
        deadline=deadline,
    )
    after = prepare_native_request(
        binary=binary_path,
        request=after_request,
        scenario=f"native-p2-{scenario}-{target_talent_id}-{target_rank}-candidate",
        deadline=deadline,
    )
    before.update(layout_receipt)
    after.update(layout_receipt)
    if before.get("status") != "PREPARED" or after.get("status") != "PREPARED":
        # Native refusals are authoritative: never turn an INVALID talent
        # request or UNSUPPORTED mechanic into a generic missing-evidence
        # BLOCKED result. Preserve both individual native receipts below.
        statuses = {before.get("status"), after.get("status")}
        if not statuses <= {"PREPARED", "BLOCKED", "INVALID", "UNSUPPORTED", "ERROR"}:
            pair_status = "ERROR"
        else:
            pair_status = next(
                (status for status in ("ERROR", "INVALID", "UNSUPPORTED")
                 if status in statuses),
                "BLOCKED",
            )
        return {
            "status": pair_status,
            "reason": "NATIVE_P2_PREPARE_PAIR_NOT_READY",
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "before": _compact_prepare_receipt(before),
            "after": _compact_prepare_receipt(after),
            "accepted_for_p2": False,
        }
    if before.get("engine_identity") != after.get("engine_identity"):
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_ENGINE_IDENTITY_CHANGED_BETWEEN_PREPARE_PAIRS",
            "before": before,
            "after": after,
            "accepted_for_p2": False,
        }
    if not before.get("request_sha256") or before.get("request_sha256") == after.get("request_sha256"):
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_P2_PREPARED_REQUEST_HASHES_MISSING_OR_IDENTICAL",
            "before": before,
            "after": after,
            "accepted_for_p2": False,
        }

    before_player = before["prepared"]["player"]
    after_player = after["prepared"]["player"]
    before_rank = int(before_player["talents"].get(target_talent_id, 0))
    after_rank = int(after_player["talents"].get(target_talent_id, 0))
    if before_rank != int(target_rank) - 1 or after_rank != int(target_rank):
        return {
            "status": "BLOCKED",
            "reason": "NATIVE_P2_PREPARED_TALENT_RANK_MISMATCH",
            "before_rank": before_rank,
            "after_rank": after_rank,
            "before": before,
            "after": after,
            "accepted_for_p2": False,
        }
    return {
        "status": "PREPARED",
        "reason": "SELECTED_RUST_PREPARE_PAIR_EXECUTED",
        "target_talent_id": target_talent_id,
        "target_rank": int(target_rank),
        "talents_string_before": before_string,
        "talents_string_after": after_string,
        "before": _compact_prepare_receipt(before),
        "after": _compact_prepare_receipt(after),
        "_before_prepared": before["prepared"],
        "_after_prepared": after["prepared"],
        "engine_identity": before["engine_identity"],
        "source_layout_sha256": hashlib.sha256(
            (root / "src" / "classes" / "druid" / "prepare.rs").read_bytes()
        ).hexdigest(),
        **layout_receipt,
        "accepted_for_p2": False,
    }


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


def _simulate_prepared(
    *,
    binary_path: Path,
    prepared: dict,
    rng_mode: NativeRngMode,
    iterations: int,
    seed: int,
    deadline: float,
    allow_zero_dps_if_avg_absent: bool = False,
) -> dict[str, object]:
    """Execute one PreparedV2 input through the selected Rust simulator.

    Only the P1 no-action control opts in to the native empty-DPS report shape.
    The default remains strict for every P2/search caller.
    """
    with tempfile.TemporaryDirectory(prefix="forever-p2-native-sim-") as directory:
        root = Path(directory)
        prepared_path = root / "prepared.json"
        report_path = root / "report.json"
        prepared_payload = copy.deepcopy(prepared)
        sim_options = prepared_payload.get("sim")
        if not isinstance(sim_options, dict):
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_PREPARED_SIM_OPTIONS_MISSING"}
        sim_options["iterations"] = int(iterations)
        sim_options["seed"] = int(seed)
        prepared_bytes = json.dumps(
            prepared_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        prepared_path.write_bytes(prepared_bytes)
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_P2_SIM_DEADLINE_EXPIRED"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    str(binary_path), "sim", "--infile", str(prepared_path),
                    "--outfile", str(report_path), "--gate",
                    "--rng-mode", rng_mode.value,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.001, deadline - time.monotonic()),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "ERROR", "stage": "sim",
                    "reason": f"NATIVE_SIM_CLI_FAILED:{type(exc).__name__}:{exc}"}
        elapsed = round(time.monotonic() - started, 6)
        if completed.returncode != 0:
            refusal = _json_object(completed.stdout or "")
            # The selected Rust CLI reserves exit 3 for an explicit gate refusal.
            # A JSON object that merely contains "supported" is not enough:
            # malformed output, validation errors and faults must remain ERROR.
            if (
                completed.returncode == 3
                and refusal is not None
                and refusal.get("supported") is False
                and isinstance(refusal.get("reasons"), list)
                and bool(refusal["reasons"])
                and isinstance(refusal.get("refusals"), list)
                and bool(refusal["refusals"])
            ):
                return {
                    "status": "UNSUPPORTED",
                    "stage": "sim",
                    "reason": "NATIVE_PREPARED_GATE_REFUSED",
                    "coverage": refusal,
                    "elapsed_seconds": elapsed,
                }
            return {
                "status": "ERROR",
                "stage": "sim",
                "reason": "NATIVE_SIM_FAILED_WITHOUT_STRUCTURED_COVERAGE",
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-700:],
                "stderr_tail": (completed.stderr or "")[-700:],
                "elapsed_seconds": elapsed,
            }
        if not report_path.is_file():
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_SIM_REPORT_MISSING",
                    "elapsed_seconds": elapsed}
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
            zero_dps_due_to_absent_avg = False
            try:
                score = float(_native_runner.dps(report))
            except KeyError as exc:
                # The real protobuf-JSON report omits dps.avg when a fight
                # has zero damage. Permit that shape only for the P1 empty
                # control, and only when native reports every requested fight.
                if not allow_zero_dps_if_avg_absent or exc.args != ("avg",):
                    raise
                result = report.get("result") if isinstance(report, dict) else None
                raid_metrics = (
                    result.get("raidMetrics") if isinstance(result, dict) else None
                )
                dps_metric = (
                    raid_metrics.get("dps") if isinstance(raid_metrics, dict) else None
                )
                iterations_done = (
                    result.get("iterationsDone") if isinstance(result, dict) else None
                )
                if type(iterations_done) is not int or iterations_done != iterations:
                    raise ValueError("NATIVE_SIM_EMPTY_DPS_ITERATIONS_INCOMPLETE")
                if not isinstance(dps_metric, dict) or "avg" in dps_metric:
                    raise ValueError("NATIVE_SIM_EMPTY_DPS_REPORT_SHAPE_INVALID")
                score = 0.0
                zero_dps_due_to_absent_avg = True
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, OverflowError) as exc:
            return {"status": "ERROR", "stage": "sim",
                    "reason": f"NATIVE_SIM_REPORT_INVALID:{type(exc).__name__}:{exc}",
                    "elapsed_seconds": elapsed}
        if not math.isfinite(score):
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_SIM_DPS_NONFINITE",
                    "elapsed_seconds": elapsed}
        return {
            "status": "EXECUTED",
            "stage": "sim",
            "dps": score,
            "iterations_done": (
                report.get("result", {}).get("iterationsDone")
                if isinstance(report.get("result"), dict) else None
            ),
            "zero_dps_due_to_absent_avg": zero_dps_due_to_absent_avg,
            "elapsed_seconds": elapsed,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "prepared_input_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
            "engine_identity": report.get("identity"),
        }



def _native_pair_failure_status(*statuses: object) -> str:
    """Preserve terminal native outcomes when either side of a pair fails.

    PREPARED/EXECUTED are successful intermediate states. Unknown or malformed
    statuses fail closed as ERROR; native INVALID/UNSUPPORTED are never
    rewritten as a generic BLOCKED/missing-evidence result.
    """
    failures: list[str] = []
    for status in statuses:
        if status in ("PREPARED", "EXECUTED"):
            continue
        if not isinstance(status, str) or status not in {
            "BLOCKED", "INVALID", "UNSUPPORTED", "ERROR"
        }:
            return "ERROR"
        failures.append(status)
    for status in ("ERROR", "INVALID", "UNSUPPORTED", "BLOCKED"):
        if status in failures:
            return status
    return "BLOCKED"


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
    """Run a DPS-only diagnostic through explicit prepare then prepared sim.

    The balanced RNG mode is a required call argument, never an environment
    default. A positive DPS delta is diagnostic only; it is not a P2 PASS.
    """
    if rng_mode is not NativeRngMode.BALANCED:
        raise NativeP2ProbeError("NATIVE_P2_REQUIRES_EXPLICIT_BALANCED_RNG")
    if isinstance(iterations, bool) or int(iterations) < 1:
        raise NativeP2ProbeError("NATIVE_P2_ITERATIONS_INVALID")
    if isinstance(target_rank, bool) or int(target_rank) < 1:
        raise NativeP2ProbeError("NATIVE_P2_TARGET_RANK_INVALID")

    binary_path = Path(binary)
    root = Path(engine_root)
    pair = run_native_prepare_pair(
        binary=binary_path,
        engine_root=root,
        scenario=scenario,
        before_selection=before_selection,
        after_selection=after_selection,
        target_talent_id=target_talent_id,
        target_rank=int(target_rank),
    )
    if pair.get("status") != "PREPARED":
        return {
            **pair,
            "status": _native_pair_failure_status(pair.get("status")),
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "rng_mode": rng_mode.value,
            "iterations": int(iterations),
            "seed": int(seed),
            "accepted_for_p2": False,
        }

    deadline = time.monotonic() + 120.0
    before = _simulate_prepared(
        binary_path=binary_path,
        prepared=pair["_before_prepared"],
        rng_mode=rng_mode,
        iterations=int(iterations), seed=int(seed), deadline=deadline,
    )
    after = _simulate_prepared(
        binary_path=binary_path,
        prepared=pair["_after_prepared"],
        rng_mode=rng_mode,
        iterations=int(iterations), seed=int(seed), deadline=deadline,
    )
    if before.get("status") != "EXECUTED" or after.get("status") != "EXECUTED":
        return {
            "status": _native_pair_failure_status(
                before.get("status"), after.get("status")
            ),
            "reason": "NATIVE_P2_SIM_PAIR_NOT_EXECUTED",
            "scenario": scenario,
            "target_talent_id": target_talent_id,
            "target_rank": int(target_rank),
            "before": before,
            "after": after,
            "prepare_pair": {key: value for key, value in pair.items() if not key.startswith("_")},
            "rng_mode": rng_mode.value,
            "iterations": int(iterations),
            "seed": int(seed),
            "accepted_for_p2": False,
        }

    delta = float(after["dps"]) - float(before["dps"])
    return {
        "status": "PROBE_PASS" if delta > 1e-9 else "PROBE_FAIL",
        "reason": "NATIVE_DPS_INCREASE_OBSERVED"
        if delta > 1e-9
        else "NATIVE_DPS_DID_NOT_INCREASE",
        "scenario": scenario,
        "target_talent_id": target_talent_id,
        "target_rank": int(target_rank),
        "talents_string_before": pair["talents_string_before"],
        "talents_string_after": pair["talents_string_after"],
        "before": {
            "prepared": pair["before"],
            "simulation": before,
        },
        "after": {
            "prepared": pair["after"],
            "simulation": after,
        },
        "delta_dps": delta,
        "engine_identity": pair["engine_identity"],
        "source_layout_sha256": pair["source_layout_sha256"],
        "rng_mode": rng_mode.value,
        "iterations": int(iterations),
        "seed": int(seed),
        "accepted_for_p2": False,
    }

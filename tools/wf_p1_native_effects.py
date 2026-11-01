#!/usr/bin/env python3
"""P1 native MythicSim Rust behavioral diagnostic, NO GameIR dependency.

Runs real pinned MythicSim Rust 'sim' CLI twice. An existing source-native APL
cast is suppressed in the second request while EVERYTHING ELSE (character,
gear, talents, encounter, seed, spell tables) remains the same. This is an
available black-box diagnostic, not a claim that removing an APL entry holds
cast timing exactly constant; full P1 requires observed actual applicability
and optimizer use, as the approved PROCESS specifies.

This tool never registers, emulates, or implements any ability. The Rust
engine remains solely responsible for damage, heals, resources and auras.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.p1_native_source_inventory import inventory


def _player(req: dict) -> dict:
    try:
        return req["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("NATIVE_REQUEST_PLAYER_MISSING") from exc


def _spell_ids_in_apl(req: dict) -> list[int]:
    spells = []
    for row in _player(req).get("rotation", {}).get("priorityList", ()):
        cast = row.get("action", {}).get("castSpell", {})
        value = cast.get("spellId", {})
        if isinstance(value, dict) and type(value.get("spellId")) is int:
            spells.append(value["spellId"])
    return spells


def native_apl_pair(req: dict, spell_id: int) -> tuple[dict, dict]:
    """Only remove source-native castSpell APL entries, no invented action stub.

    Not a timed zero-effect ability: removing an APL action may change other
    spells' scheduling. Native direct spell-control is preferable when exposed.
    """
    if type(spell_id) is not int or spell_id <= 0:
        raise ValueError("INVALID_SOURCE_SPELL_ID")
    original = copy.deepcopy(req)
    control = copy.deepcopy(req)
    rotation = _player(control).get("rotation")
    if not isinstance(rotation, dict) or not isinstance(rotation.get("priorityList"), list):
        raise ValueError("NATIVE_APL_NOT_AVAILABLE")
    if spell_id not in _spell_ids_in_apl(req):
        raise ValueError("SPELL_NOT_IN_SOURCE_NATIVE_APL:" + str(spell_id))
    rotation["priorityList"] = [
        row for row in rotation["priorityList"]
        if (row.get("action", {}).get("castSpell", {}).get("spellId", {})
            .get("spellId") != spell_id)
    ]
    if len(rotation["priorityList"]) == len(_player(req)["rotation"]["priorityList"]):
        raise ValueError("NATIVE_APL_CONTROL_NOT_MUTATED")
    # No other input mutation is permitted.
    restored = copy.deepcopy(control)
    _player(restored)["rotation"]["priorityList"] = copy.deepcopy(
        _player(original)["rotation"]["priorityList"])
    if restored != original:
        raise ValueError("NATIVE_ABLATION_CHANGED_OTHER_INPUT_FIELDS")
    return original, control


def sha(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _run(binary: Path, req: dict, *, timeout_s: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="p1-native-") as directory:
        request_path = Path(directory) / "request.json"
        output_path = Path(directory) / "result.json"
        request_path.write_text(json.dumps(req, sort_keys=True, allow_nan=False))
        cp = subprocess.run([str(binary), "sim", "--request", str(request_path),
                             "--outfile", str(output_path), "--gate"],
                            capture_output=True, text=True, timeout=timeout_s)
        if cp.returncode != 0 or not output_path.is_file():
            raise ValueError("REAL_NATIVE_EXECUTION_FAILED:"
                             + cp.stderr[-700:] + ":exit=" + str(cp.returncode))
        data = json.loads(output_path.read_text())
    if data.get("identity", {}).get("engine") != "forever-engine":
        raise ValueError("NON_RUST_FOREVER_ENGINE_RESULT")
    if data.get("result", {}).get("iterationsDone", 0) < 1:
        raise ValueError("NATIVE_RESULT_DID_NOT_EXECUTE_FIGHTS")
    return data


def _measure(report: dict) -> dict[str, float]:
    """Read actual combat output; not fabricated cast counters or metadata."""
    result = report.get("result") or {}
    metrics = result.get("raidMetrics") or {}
    observed = {}
    for metric in ("dps", "hps", "dtps", "tps"):
        block = metrics.get(metric)
        if isinstance(block, dict) and type(block.get("avg")) in (int, float):
            v = float(block["avg"])
            if not math.isfinite(v):
                raise ValueError("NONFINITE_NATIVE_COMBAT_METRIC")
            observed[metric] = v
    if not observed:
        raise ValueError("REAL_NATIVE_COMBAT_METRICS_MISSING")
    return observed


def run_native(binary: Path, request: dict, *, class_key: str, level: int,
               spell_id: int, timeout_s: float = 30.,
               root: Path = ROOT, db_path: Path | None = None) -> dict:
    """Native diagnostic, with source-only test universe and zero GameIR use."""
    source = inventory(class_key, level, root=root, db_path=db_path)
    selected = {r["spell_id"]: r for r in source["candidates"]}
    other = {r["spell_id"]: r for r in source["separate"]}
    if spell_id in other:
        return {"status": other[spell_id]["status"], "spell_id": spell_id,
                "effect_observed": False, "p1_certified": False}
    if spell_id not in selected:
        raise ValueError("SOURCE_SPELL_NOT_IN_P1_CANDIDATES:" + str(spell_id))
    if not binary.is_file():
        raise FileNotFoundError("PINNED_RUST_ENGINE_BINARY_MISSING")
    baseline, no_action = native_apl_pair(request, spell_id)
    fixed_options = baseline.get("simOptions", {})
    if int(fixed_options.get("iterations") or 0) < 1:
        raise ValueError("NATIVE_REQUEST_NO_ITERATIONS")
    if not fixed_options.get("randomSeed"):
        raise ValueError("NATIVE_REQUEST_NO_PINNED_SEED")
    real = _run(binary, baseline, timeout_s=timeout_s)
    without = _run(binary, no_action, timeout_s=timeout_s)
    real_values = _measure(real)
    no_values = _measure(without)
    # A changed metric is a useful, fast real Rust black-box observation; it
    # alone is not proof that the action actually cast or is correctly tuned.
    diff = {k: {"with_action":real_values.get(k),
                "without_action":no_values.get(k)}
            for k in sorted(set(real_values)|set(no_values))
            if real_values.get(k) != no_values.get(k)}
    return {
        "class": class_key, "level": level, "spell_id": spell_id,
        "status": "NATIVE_APL_ABLATION_DIFFERENCE" if diff
                  else "NO_COMBAT_METRIC_DIFFERENCE",
        "native_executed": True,
        "effect_observed": bool(diff),
        "p1_certified": False,
        "proof_kind": "RUST_APL_ABLATION_DIAGNOSTIC_NOT_ISOLATED_P1",
        "engine_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "real_request_sha256": sha(baseline),
        "control_request_sha256": sha(no_action),
        "combat_metrics_delta": diff,
        "confounder": "Removing APL action does not preserve action timing; "
                      "a real direct-cast capability would allow the exact no-effect control",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--class", dest="class_key", required=True)
    p.add_argument("--level", type=int, required=True)
    p.add_argument("--spell-id", type=int, required=True)
    p.add_argument("--timeout-s", type=float, default=30.)
    args = p.parse_args(argv)
    try:
        report = run_native(args.binary.resolve(),
                            json.loads(args.request.read_text()),
                            class_key=args.class_key, level=args.level,
                            spell_id=args.spell_id, timeout_s=args.timeout_s)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0 if report.get("native_executed") else 2
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print("NOT_TESTED: " + type(exc).__name__ + ": " + str(exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

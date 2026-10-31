#!/usr/bin/env python3
"""Instrument a *separate* pinned Rust build to diagnose invalid crit thresholds.

This deliberately never changes the SHA-pinned optimizer binary. Diagnostic
scores are not paid candidates and are never eligible for promotion.
Apply AFTER wf652_apply_balanced.py, wf659_typed_rng.py and
wf660_boolean_migration.py, in a separate engine checkout.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


RNG_NEEDLE = '''        assert!(p.is_finite() && (0.0..=1.0).contains(&p),
            "balanced RNG: probability must be finite and in [0,1]");'''
RNG_REPLACEMENT = '''        if !p.is_finite() || !(0.0..=1.0).contains(&p) {
            eprintln!("RNG_PROBABILITY_DIAGNOSTIC label={:?} p={:?}", key, p);
        }
''' + RNG_NEEDLE
MELEE_NEEDLE = 'self.proc(self.physical_crit_chance(spell), "Physical Crit Roll")'
MELEE_REPLACEMENT = '''{
            let chance = self.physical_crit_chance(spell);
            if !chance.is_finite() || !(0.0..=1.0).contains(&chance) {
                eprintln!("RNG_PHYSICAL_CRIT_DIAGNOSTIC spell={:?} chance={:?}", spell, chance);
            }
            self.proc(chance, "Physical Crit Roll")
        }'''


def instrument_engine(root: Path) -> None:
    """Fail closed on unexpected engine source or accidental double-patching."""
    for relative, needle, replacement in [
        ("src/core/rng.rs", RNG_NEEDLE, RNG_REPLACEMENT),
        ("src/core/fight/melee.rs", MELEE_NEEDLE, MELEE_REPLACEMENT),
    ]:
        path = root / relative
        source = path.read_text()
        if source.count(needle) < 1 or replacement in source:
            raise AssertionError(f"{relative}: expected original at least once; already instrumented?")
        path.write_text(source.replace(needle, replacement))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_invalid_threshold(stderr: str) -> dict:
    crit = re.search(r"RNG_PHYSICAL_CRIT_DIAGNOSTIC spell=(\d+) chance=([^\s]+)", stderr)
    rng = re.search(r'RNG_PROBABILITY_DIAGNOSTIC label="([^"]+)" p=([^\s]+)', stderr)
    return {
        "spell_id": int(crit.group(1)) if crit else None,
        "physical_crit_chance": float(crit.group(2)) if crit else None,
        "label": rng.group(1) if rng else None,
        "invalid_probability": float(rng.group(2)) if rng else None,
    }


def replay_failed_gear_requests(gear_dir: Path, outdir: Path, binary,
                                *, runner=None) -> dict:
    """Replay each exact saved failed request and seed using diagnostic Rust.

    Never invokes the optimizer and never calls this a paid native evaluation.
    """
    native_runner = runner if runner is not None else subprocess.run
    outdir.mkdir(parents=True, exist_ok=True)
    evidence = json.loads((gear_dir / "gear_probe.json").read_text())
    results = []
    for row in evidence["rows"]:
        for failure in row.get("native_failures", []):
            if failure.get("category") != "RUST_BALANCED_RNG_PROBABILITY":
                continue
            request_path = gear_dir / failure["request_path"]
            frozen = json.loads(request_path.read_text())
            replay = failure["rng_replay"]
            payload = copy.deepcopy(frozen)
            payload["simOptions"]["iterations"] = replay["iterations"]
            payload["simOptions"]["randomSeed"] = str(replay["seed"])
            slug = row["profile_id"].replace("/", "__")
            basename = Path(failure["request_path"]).stem
            stderr_path = outdir / f"{slug}__{basename}.stderr.txt"
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                request_file = tmpdir / "exact_request.json"
                output_file = tmpdir / "native_output.json"
                request_file.write_text(json.dumps(payload, separators=(",", ":")))
                cmd = [str(binary), "sim", "--request", str(request_file),
                       "--outfile", str(output_file), "--gate"]
                try:
                    completed = native_runner(
                        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                        text=True, timeout=20.0,
                        env=dict(os.environ, WOWSIM_RNG_MODE="balanced", RUST_BACKTRACE="0"))
                    stderr = completed.stderr or ""
                    exit_code = completed.returncode
                except subprocess.TimeoutExpired as exc:
                    stderr = exc.stderr or ""
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode("utf-8", errors="replace")
                    exit_code = None
            stderr_path.write_text(stderr)
            result = {
                "profile_id": row["profile_id"],
                "accounting": "DIAGNOSTIC_NOT_PAID",
                "source_request_path": failure["request_path"],
                "source_request_sha256": digest(request_path),
                "seed": replay["seed"],
                "iterations": replay["iterations"],
                "diagnostic_payload_sha256": hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "exit_code": exit_code,
                "panic_reproduced": "balanced RNG: probability must be finite and in [0,1]" in stderr,
                "stderr_path": stderr_path.name,
                "stderr_sha256": digest(stderr_path),
                **parse_invalid_threshold(stderr),
            }
            if frozen != json.loads(request_path.read_text()):
                raise AssertionError("Diagnostic replay mutated the frozen source request")
            results.append(result)
    summary = {
        "scope": "DIAGNOSTIC_NOT_PAID_NOT_JOINT_NOT_P7_PASS",
        "diagnostic_binary_sha256": digest(Path(binary)) if Path(binary).is_file() else None,
        "replays": results,
    }
    (outdir / "rng_probability_diagnostic.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instrument-engine", type=Path)
    parser.add_argument("--replay-gear-probe", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.instrument_engine is not None:
        instrument_engine(args.instrument_engine)
        return
    if not args.replay_gear_probe or not args.binary or not args.out:
        parser.error("Need --replay-gear-probe, --binary and --out")
    if not args.binary.is_file():
        parser.error("Need a compiled real Rust diagnostic binary")
    summary = replay_failed_gear_requests(args.replay_gear_probe, args.out, args.binary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

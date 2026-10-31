#!/usr/bin/env python3
"""Isolated L60 native Rust fix for deterministic Bernoulli extremes.

The pinned scorer and PR #25/#26 remain unchanged. Apply only to the separate
instrumented diagnostic engine after measuring the original six failures.
Stochastic Proc(p) semantics: p >= 1 is always true; p <= 0 always false.
NaN remains an explicit balanced-engine error, not a silently accepted value.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import time
from pathlib import Path

OLD = '''            RandomRequest::Bernoulli(p) => {
                let value = match self {
                    SimRng::Balanced(rng) => rng.proc(p,label),
                    _ if p>=1.0 => true,
                    _ if p<=0.0 => false,
                    _ => matches!(self.sample(RandomRequest::Uniform01,label),
                        RandomOutcome::Float(x) if x < p),
                };
                RandomOutcome::Bool(value)
            }'''
NEW = '''            RandomRequest::Bernoulli(p) => {
                // Match the pinned stochastic Proc(p) semantics at the
                // deterministic extremes before entering the quota sampler.
                // Do NOT clamp NaN: it remains an explicit invalid threshold.
                let value = match self {
                    _ if p>=1.0 => true,
                    _ if p<=0.0 => false,
                    SimRng::Balanced(rng) => rng.proc(p,label),
                    _ => matches!(self.sample(RandomRequest::Uniform01,label),
                        RandomOutcome::Float(x) if x < p),
                };
                RandomOutcome::Bool(value)
            }'''
RUST_TESTS = '''
#[cfg(test)]
mod wf_l60_rng_extreme_tests {
    use super::*;

    #[test]
    fn over_one_physical_crit_matches_stochastic() {
        let mut balanced = SimRng::Balanced(BalancedRng::default());
        let mut stochastic = SimRng::Shared(SplitMix64::new(2710));
        for p in [1.3085, 1.317, 1.3185, 1.229995, 1.22586, 1.227925] {
            assert!(balanced.proc(p, "Physical Crit Roll"));
            assert!(stochastic.proc(p, "Physical Crit Roll"));
        }
    }

    #[test]
    fn negative_crit_is_false_in_both_modes() {
        let mut balanced = SimRng::Balanced(BalancedRng::default());
        let mut stochastic = SimRng::Shared(SplitMix64::new(2710));
        for p in [-0.25, -0.001, 0.0] {
            assert!(!balanced.proc(p, "Physical Crit Roll"));
            assert!(!stochastic.proc(p, "Physical Crit Roll"));
        }
    }

    #[test]
    #[should_panic(expected = "balanced RNG: probability must be finite and in [0,1]")]
    fn nan_remains_explicit_error_in_balanced_mode() {
        let mut balanced = SimRng::Balanced(BalancedRng::default());
        balanced.proc(f64::NAN, "Physical Crit Roll");
    }
}
'''


def patch_engine(root: Path) -> None:
    path = root / "src/core/rng.rs"
    text = path.read_text()
    if text.count(OLD) != 1 or "wf_l60_rng_extreme_tests" in text:
        raise AssertionError("expected one unmodified WF659 Bernoulli dispatch; already patched?")
    path.write_text(text.replace(OLD, NEW, 1) + RUST_TESTS)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_fixed_replays(gear_dir: Path, outdir: Path, binary, *, evaluator=None):
    """Exact same six source requests and seeds on a NEW explicitly hashed Rust.

    Results are native diagnostic scores, NOT search-paid candidates.
    """
    if evaluator is None:
        from p73_talent_search_v2 import run as evaluator
    outdir.mkdir(parents=True, exist_ok=True)
    original = json.loads((gear_dir / "gear_probe.json").read_text())
    results = []
    for row in original["rows"]:
        for failure in row.get("native_failures", []):
            if failure.get("category") != "RUST_BALANCED_RNG_PROBABILITY":
                continue
            path = gear_dir / failure["request_path"]
            request = json.loads(path.read_text())
            frozen = copy.deepcopy(request)
            replay = failure["rng_replay"]
            entry = {
                "profile_id": row["profile_id"],
                "source_request_path": failure["request_path"],
                "source_request_sha256": digest(path),
                "seed": replay["seed"],
                "iterations": replay["iterations"],
                "accounting": "DIAGNOSTIC_NOT_PAID",
                "rng_mode": "balanced",
                "success": False,
            }
            try:
                score, _output, native_s, payload_sha = evaluator(
                    binary, copy.deepcopy(request), replay["iterations"],
                    replay["seed"], "balanced", time.monotonic() + 30.0)
                if not math.isfinite(score):
                    raise ValueError("Non-finite native diagnostic score")
                entry.update(success=True, native_score=score,
                             native_duration_s=native_s,
                             native_payload_sha256=payload_sha)
            except Exception as exc:
                entry["error"] = str(exc)[-1000:]
            if request != frozen or json.loads(path.read_text()) != frozen:
                raise AssertionError("Fixed replay mutated the frozen request")
            results.append(entry)
    report = {
        "scope": "FIXED_RUST_DIAGNOSTIC_NOT_PAID_NOT_JOINT_NOT_P7_PASS",
        "fixed_binary_sha256": digest(Path(binary)) if Path(binary).is_file() else None,
        "replays": results,
    }
    (outdir / "rng_fixed_replays.json").write_text(json.dumps(report, indent=2) + "\n")
    return report



def verify_fixed_scorer_gear_upgrade(original_dir: Path, fixed_dir: Path,
                                     fixed_binary: Path) -> dict:
    """Audit two frozen balanced-RNG failures against a separately pinned scorer.

    This checks *real* paid probe evidence; it does not certify source gear
    legality, a cold JOINT optimizer, or any P7 gate. The two source requests
    must match byte-for-byte, and the scorer must differ from historical Rust.
    """
    old = json.loads((original_dir / "gear_probe.json").read_text())
    new = json.loads((fixed_dir / "gear_probe.json").read_text())
    fixed_sha = digest(fixed_binary)
    assert fixed_sha == new["engine_binary_sha256"], "Fixed probe scorer SHA mismatch"
    assert old["engine_binary_sha256"] != fixed_sha, "Historical scorer was not isolated"

    def index(report):
        rows = report["rows"]
        by_id = {row["profile_id"]: row for row in rows}
        assert len(rows) == len(by_id) == 28, "Require complete 28-row evidence"
        return by_id

    old_rows, new_rows = index(old), index(new)
    assert set(old_rows) == set(new_rows), "Fixed probe lost a profile"
    upgraded = []
    for profile in ("druid/feral_cat", "rogue/assassination"):
        failures = old_rows[profile].get("native_failures") or []
        assert failures and failures[0]["category"] == "RUST_BALANCED_RNG_PROBABILITY", (
            profile + ": missing historical RNG failure"
        )
        frozen = failures[0]
        result = new_rows[profile]
        assert result["native_paid"] == 1, profile + ": fixed scorer did not pay"
        assert result["status"] == "NATIVE_GEAR_PROBE_PAID_PARTIAL_LEGALITY", (
            profile + ": not a successful partial-legal gear probe"
        )
        assert math.isfinite(result["native_score"]), profile + ": nonfinite native score"
        assert result["request_sha256"] == frozen["request_sha256"], (
            profile + ": candidate request changed between scorers"
        )
        assert result["request_path"] == frozen["request_path"], (
            profile + ": request path changed between scorers"
        )
        for directory in (original_dir, fixed_dir):
            assert digest(directory / frozen["request_path"]) == frozen["request_sha256"], (
                profile + ": saved request differs from frozen evidence"
            )
        upgraded.append({
            "profile_id": profile,
            "frozen_request_sha256": frozen["request_sha256"],
            "native_score": result["native_score"],
            "accounting": "PAID_NATIVE_PARTIAL_GEAR_LEGALITY_NOT_JOINT",
        })
    report = {
        "scope": "FIXED_RUST_NATIVE_GEAR_UPGRADE_NOT_JOINT_NOT_P7_PASS",
        "historical_binary_sha256": old["engine_binary_sha256"],
        "fixed_binary_sha256": fixed_sha,
        "upgraded_profiles": upgraded,
        "row_count": len(new_rows),
    }
    (fixed_dir / "fixed_scorer_gear_upgrade.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--patch-engine",type=Path)
    ap.add_argument("--replay-gear-probe",type=Path)
    ap.add_argument("--binary",type=Path)
    ap.add_argument("--out",type=Path)
    a=ap.parse_args()
    if a.patch_engine is not None:
        patch_engine(a.patch_engine)
    elif a.replay_gear_probe and a.binary and a.out:
        if not a.binary.is_file():
            ap.error("Need compiled Rust engine binary")
        print(json.dumps(verify_fixed_replays(a.replay_gear_probe,a.out,a.binary),indent=2))
    else:
        ap.error("Need --patch-engine OR --replay-gear-probe/--binary/--out")


if __name__=="__main__":
    main()

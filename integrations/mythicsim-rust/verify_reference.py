#!/usr/bin/env python3
"""WF633 real Rust replay validator: no mock and no fallback results."""
import argparse
import hashlib
import json
import math
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "wf633"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True, type=pathlib.Path)
    p.add_argument("--request", type=pathlib.Path, default=EVIDENCE / "rust_request_reconstructed.json")
    p.add_argument("--validation", type=pathlib.Path, default=EVIDENCE / "WF633_VALIDATION.json")
    p.add_argument("--tol", type=float, default=1e-9)
    args = p.parse_args()
    meta = json.loads(args.validation.read_text(encoding="utf-8"))
    source = args.request.read_bytes()
    actual_sha = hashlib.sha256(source).hexdigest()
    if actual_sha != meta["request_sha256"]:
        raise SystemExit(f"request SHA256 mismatch: {actual_sha}")
    if not args.engine.is_file():
        raise SystemExit(f"Rust executable missing: {args.engine}")
    req = json.loads(source)
    if int(req["simOptions"]["iterations"]) != int(meta["iterations"]):
        raise SystemExit("iteration mismatch")
    with tempfile.TemporaryDirectory(prefix="wf633-rust-") as d:
        output = pathlib.Path(d) / "result.json"
        completed = subprocess.run(
            [str(args.engine.resolve()), "sim", "--request", str(args.request.resolve()),
             "--outfile", str(output), "--gate"], capture_output=True, text=True)
        if completed.returncode != 0:
            raise SystemExit(f"Rust sim failed (exit {completed.returncode}): {completed.stderr[-2000:]}")
        if not output.is_file():
            raise SystemExit("Rust engine produced no output")
        data = json.loads(output.read_text(encoding="utf-8"))
        if data.get("identity", {}).get("engine") != "forever-engine":
            raise SystemExit("result not produced by forever-engine")
        # source_revision in this output is the Go-reference ruleset SHA, not Rust source SHA.
        # Pin Rust source revision via external build/artifact manifest, and verify the
        # result identifies the native Rust engine rather than inventing revision parity.
        result = data.get("result", {})
        if result.get("iterationsDone") != meta["iterations"]:
            raise SystemExit("result iterations mismatch")
        dps = result["raidMetrics"]["dps"]["avg"]
        if not math.isclose(dps, meta["rust_dps"], rel_tol=0, abs_tol=args.tol):
            raise SystemExit(f"Rust parity FAIL: {dps} vs {meta['rust_dps']}")
        print(json.dumps({"status":"PASS","engine_revision":meta["engine_revision"],
                          "iterations":meta["iterations"],"dps":dps,
                          "external_reference_dps":meta["reference_dps"],
                          "request_sha256":actual_sha}, indent=2))

if __name__ == "__main__":
    main()

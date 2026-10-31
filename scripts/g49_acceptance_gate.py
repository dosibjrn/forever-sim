#!/usr/bin/env python3
"""Portable G49 acceptance runner: never turn a skip/timeout into a PASS.

Use on a local machine with Chromium allowed to access 127.0.0.1. Runs the
real project pytest suites, emits a machine-readable report, and returns 0
only when *every* required stage passes with no skips. Stage-specific runs
are useful for diagnosis but are never reported as G49 acceptance.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    "fast": (
        180,
        (
            "tests/test_generic_capability_default_g49a.py",
            "tests/test_g49b_browser_live_bridge.py",
            "tests/test_generic_auto_browser_network_g49b.py",
            "tests/test_generic_g46g_authority.py",
            "tests/test_g49e_acceptance_runner.py",
            "-k", "not test_g49b_real_auto_promoted_generic_http_never_reads_legacy",
        ),
    ),
    # A real seven-class service test is deliberately a separate process.
    # Previous browser tests can leave expensive shared state in the process;
    # a fresh interpreter makes this checkpoint deterministic and measurable.
    "http": (100, (
        "tests/test_generic_auto_browser_network_g49b.py::test_g49b_real_auto_promoted_generic_http_never_reads_legacy",
    )),
    "slow": (180, ("tests/test_generic_all_class_product_gate_g48d.py",)),
    "native": (60, ("tests/test_g49d_native_browser_e2e.py",)),
}


@dataclass
class GateResult:
    name: str
    status: str
    tests: int
    failures: int
    errors: int
    skipped: int
    exit_code: int | None
    duration_seconds: float | None
    detail: str


def parse_junit(path: Path) -> tuple[int, int, int, int, float | None]:
    """Return counts from pytest's XML; missing XML is never a success."""
    tree = ElementTree.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    # pytest writes a single testsuite; never double-count a nested suite.
    leaves = [suite for suite in suites if not list(suite.iter("testsuite"))[1:]]
    if not leaves:
        leaves = suites
    counts = tuple(sum(int(s.get(field, "0")) for s in leaves) for field in
                   ("tests", "failures", "errors", "skipped"))
    duration = sum(float(s.get("time", "0")) for s in leaves)
    return (*counts, duration)


def run_stage(name: str, *, python: str = sys.executable, timeout: int | None = None) -> GateResult:
    if name not in STAGES:
        raise ValueError(f"unknown stage: {name}")
    default_timeout, files = STAGES[name]
    limit = timeout or default_timeout
    with tempfile.TemporaryDirectory(prefix=f"wow_g49_{name}_") as folder:
        xml = Path(folder) / "pytest.xml"
        env = os.environ.copy()
        if name == "native":
            env["WOW_REQUIRE_NATIVE_BROWSER_E2E"] = "1"
        cmd = [python, "-m", "pytest", "-vv" if name == "slow" else "-q", "--disable-warnings",
               "--junitxml", str(xml), *files]
        log = Path(folder) / "pytest.log"
        try:
            # A Chromium subprocess can inherit a pipe even after pytest exits.
            # Writing to a real file avoids subprocess.communicate() waiting
            # forever for an orphaned pipe writer on some runners.
            with log.open("w", encoding="utf-8") as stream:
                proc = subprocess.run(cmd, cwd=ROOT, env=env, text=True,
                                      stdout=stream, stderr=subprocess.STDOUT,
                                      timeout=limit, check=False)
            output, exit_code = log.read_text(errors="replace"), proc.returncode
        except subprocess.TimeoutExpired:
            return GateResult(name, "TIMEOUT", 0, 0, 0, 0, None, float(limit),
                              f"stage exceeded {limit}s; test was not accepted")
        try:
            tests, failures, errors, skipped, duration = parse_junit(xml)
        except (OSError, ElementTree.ParseError, ValueError) as exc:
            return GateResult(name, "ERROR", 0, 0, 0, 0, exit_code, None,
                              f"missing or invalid JUnit evidence: {exc}; {output[-500:]}")
        if name == "native" and "Native browser socket blocked" in output:
            status = "BLOCKED"
        elif exit_code != 0 or failures or errors:
            status = "FAIL"
        elif tests <= 0 or skipped:
            status = "SKIPPED"
        else:
            status = "PASS"
        return GateResult(name, status, tests, failures, errors, skipped,
                          exit_code, duration, output[-1200:].strip())


def build_report(results: list[GateResult]) -> dict:
    by_name = {row.name: row for row in results}
    complete = set(by_name) == set(STAGES)
    passed = complete and all(row.status == "PASS" for row in by_name.values())
    return {
        "schema_version": 1,
        "gate": "G49",
        "acceptance_passed": passed,
        "acceptance_status": "PASS" if passed else "NOT_ACCEPTED",
        "missing_stages": sorted(set(STAGES) - set(by_name)),
        "stages": [asdict(row) for row in results],
        "native_browser_network_required": True,
        "fail_closed_policy_required": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", *STAGES), default="all")
    parser.add_argument("--report", type=Path, default=ROOT / "G49_ACCEPTANCE_REPORT.json")
    parser.add_argument("--timeout", type=int, help="override each stage timeout in seconds")
    args = parser.parse_args(argv)
    results = []
    for stage in (STAGES if args.stage == "all" else (args.stage,)):
        result = run_stage(stage, timeout=args.timeout)
        results.append(result)
        if result.status != "PASS":
            # No later stage can turn a failed prerequisite into acceptance.
            break
    report = build_report(results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for row in results:
        print(f"{row.name}: {row.status} ({row.tests} tests, {row.skipped} skipped, "
              f"{row.duration_seconds}s)", flush=True)
    print(f"G49 acceptance: {report['acceptance_status']} -> {args.report}", flush=True)
    # Stage-specific diagnostics can succeed without claiming full acceptance.
    return 0 if (report["acceptance_passed"] if args.stage == "all"
                 else all(row.status == "PASS" for row in results)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

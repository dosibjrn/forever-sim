#!/usr/bin/env python3
"""Port mandatory typed RNG selection into the canonical MythicSim Rust fork.

Invoked on a checked-out *selected* Rust source by Forever's CI and by the
authorized fork-sync Action. Fails closed if any expected source anchor changes.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re

CLASSES = ("druid", "hunter", "mage", "paladin", "priest", "rogue",
           "shaman", "warlock", "warrior")
MODE = "crate::core::rng::RngMode"


def patch(path: Path, edits: list[tuple[str, str]]) -> None:
    source = path.read_text()
    for old, new in edits:
        if source.count(old) != 1:
            raise AssertionError(
                f"{path}: expected exactly one source anchor {old!r}; "
                f"found {source.count(old)}")
        source = source.replace(old, new, 1)
    path.write_text(source)


def port(root: Path) -> None:
    rng = root / "src/core/rng.rs"
    existing = rng.read_text()
    if "pub enum RngMode { Balanced, Stochastic }" in existing:
        # The authorized fork-sync Action may run again on an already patched
        # integration branch. Accept only the COMPLETE typed runtime contract.
        main = (root / "src/main.rs").read_text()
        fight = (root / "src/core/fight.rs").read_text()
        if ("WOWSIM_RNG_MODE" in existing
                or "fn new(labeled: bool, seed: u64, mode: RngMode)" not in existing
                or "rng_mode: crate::core::rng::RngMode" not in fight
                or "sim and bench require explicit --rng-mode" not in main):
            raise AssertionError("PARTIAL_RUST_TYPED_RNG_PATCH")
        print("RUST_EXPLICIT_REQUIRED_RNG_PORT_ALREADY_PRESENT")
        return
    patch(rng, [
        ("pub(crate) enum SimRng {", """#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RngMode { Balanced, Stochastic }

pub(crate) enum SimRng {"""),
        ('''    pub(crate) fn new(labeled: bool, seed: u64) -> Self {
        match std::env::var("WOWSIM_RNG_MODE").as_deref() {
            Ok("balanced") => return SimRng::Balanced(BalancedRng::default()),
            Ok("stochastic") | Err(std::env::VarError::NotPresent) => {},
            _ => panic!("unknown WOWSIM_RNG_MODE; expected stochastic or balanced"),
        }

''', '''    pub(crate) fn new(labeled: bool, seed: u64, mode: RngMode) -> Self {
        if mode == RngMode::Balanced {
            return SimRng::Balanced(BalancedRng::default());
        }
'''),
        ("SimRng::new(false, 42)",
         "SimRng::new(false, 42, RngMode::Stochastic)"),
        ("SimRng::new(true, 42)",
         "SimRng::new(true, 42, RngMode::Stochastic)"),
    ])
    patch(root / "src/lib.rs", [(
        "pub use report::{Counts, Report, TraceEvent, Work};",
        "pub use report::{Counts, Report, TraceEvent, Work};\n"
        "pub use crate::core::rng::RngMode;")])
    patch(root / "src/core/fight.rs", [
        ("    pub(crate) fn new(\n        prepared: &PreparedV2,\n        agent: A,",
         f"    pub(crate) fn new(\n        prepared: &PreparedV2,\n"
         f"        rng_mode: {MODE},\n        agent: A,"),
        ("rng: SimRng::new(prepared.sim.labeled_rng, prepared.sim.seed as u64)",
         "rng: SimRng::new(prepared.sim.labeled_rng, prepared.sim.seed as u64, rng_mode)"),
    ])
    # Existing native test fixtures explicitly select stochastic behavior.
    # The typed fight constructor no longer offers implicit RNG selection.
    path = root / "src/core/fight.rs"
    tests = path.read_text()
    old_test_call = "DruidAgent::fight(&prepared)"
    assert tests.count(old_test_call) == 3, "Rust fixture callsites drifted"
    tests = tests.replace(old_test_call,
                          "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)")
    path.write_text(tests)
    for cl in CLASSES:
        agent = root / f"src/classes/{cl}/agent.rs"
        source = agent.read_text()
        old = "pub(crate) fn fight(prepared: &PreparedV2)"
        assert source.count(old) == 1, f"{agent}: fight signature drift"
        source = source.replace(
            old, f"pub(crate) fn fight(prepared: &PreparedV2, rng_mode: {MODE})", 1)
        source, changes = re.subn(
            r"Fight::new\(\s*prepared\s*,", "Fight::new(prepared, rng_mode,",
            source, count=1)
        assert changes == 1, f"{agent}: Fight::new call drift"
        agent.write_text(source)
        patch(root / f"src/classes/{cl}/prepared.rs", [
            ("    prepared: &crate::contracts::prepared_v2::PreparedV2,\n)",
             f"    prepared: &crate::contracts::prepared_v2::PreparedV2,\n"
             f"    rng_mode: {MODE},\n)"),
            ("::fight(prepared)?", "::fight(prepared, rng_mode)?"),
        ])
    path = root / "src/classes.rs"
    source = path.read_text()
    source, count = re.subn(
        r"(pub\(crate\) fn (?:run_prepared|native_two_world_targets|native_two_pull_windows)"
        r"\([\s\S]*?\n)(\) ->|\)\n    ->)",
        lambda m: m.group(1) + f"    rng_mode: {MODE},\n" + m.group(2),
        source, count=3)
    assert count == 3, f"{path}: expected 3 typed dispatch entrypoints, got {count}"
    for cl in CLASSES:
        source = source.replace(
            f"{cl}::prepared::run_prepared(prepared)",
            f"{cl}::prepared::run_prepared(prepared, rng_mode)")
        source = source.replace(
            f"{cl}::agent::{cl.title()}Agent::fight(prepared)",
            f"{cl}::agent::{cl.title()}Agent::fight(prepared, rng_mode)")
    assert "Agent::fight(prepared)" not in source
    assert "::prepared::run_prepared(prepared)" not in source
    path.write_text(source)
    path = root / "src/engine/prepared.rs"
    patch(path, [
        ("pub fn simulate(prepared: &PreparedV2) -> Result<PreparedReport, PreparedError> {",
         f"pub fn simulate(prepared: &PreparedV2, rng_mode: {MODE})"
         " -> Result<PreparedReport, PreparedError> {"),
        ("    run(prepared)\n}", "    run(prepared, rng_mode)\n}"),
        ("pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize)",
         f"pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize,"
         f" rng_mode: {MODE})"),
        ("classes::native_two_world_targets(prepared, target_count)",
         "classes::native_two_world_targets(prepared, target_count, rng_mode)"),
        ("pub fn native_two_pull_windows(prepared: &PreparedV2)",
         f"pub fn native_two_pull_windows(prepared: &PreparedV2, rng_mode: {MODE})"),
        ("classes::native_two_pull_windows(prepared)",
         "classes::native_two_pull_windows(prepared, rng_mode)"),
        ("pub fn simulate_gated(prepared: &PreparedV2) -> Result<Gated, PreparedError> {",
         f"pub fn simulate_gated(prepared: &PreparedV2, rng_mode: {MODE})"
         " -> Result<Gated, PreparedError> {"),
        ("    run(prepared).map(|report| Gated::Simulated(Box::new(report)))",
         "    run(prepared, rng_mode).map(|report| Gated::Simulated(Box::new(report)))"),
        ("fn run(prepared: &PreparedV2) -> Result<PreparedReport, PreparedError> {",
         f"fn run(prepared: &PreparedV2, rng_mode: {MODE})"
         " -> Result<PreparedReport, PreparedError> {"),
        ("classes::run_prepared(prepared)",
         "classes::run_prepared(prepared, rng_mode)"),
    ])
    path = root / "src/main.rs"
    patch(path, [
        ("use serde::Deserialize;", "use serde::Deserialize;\nuse forever_engine::RngMode;"),
        ("fn run() -> Result<(), Failure> {", """fn parse_rng_mode(mode: &str) -> Result<RngMode, Failure> {
    match mode {
        "balanced" => Ok(RngMode::Balanced),
        "stochastic" => Ok(RngMode::Stochastic),
        _ => Err("--rng-mode requires balanced or stochastic".into()),
    }
}

fn run() -> Result<(), Failure> {"""),
        ('if args.len() != 5 || args[1] != "--infile" || args[3] != "--targets"',
         'if args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode"'),
        ('let report = native_two_world_targets(&prepared, target_count)',
         'let report = native_two_world_targets(&prepared, target_count, parse_rng_mode(&args[6])?)'),
        ('if args.len() != 5 || args[1] != "--infile"\n'
         '            || args[3] != "--targets" || args[4] != "2"',
         'if args.len() != 7 || args[1] != "--infile"\n'
         '            || args[3] != "--targets" || args[4] != "2" || args[5] != "--rng-mode"'),
        ('let windows = native_two_pull_windows(&prepared)',
         'let windows = native_two_pull_windows(&prepared, parse_rng_mode(&args[6])?)'),
        ("    let mut go_rules = false;",
         "    let mut go_rules = false;\n    let mut rng_mode = None;"),
        ('            "--trace" if !trace => trace = true,', '''            "--rng-mode" => {
                index += 1;
                let name = args.get(index).ok_or("--rng-mode requires a value")?;
                if rng_mode.replace(parse_rng_mode(name)?).is_some() {
                    return Err("duplicate --rng-mode".into());
                }
            }
            "--trace" if !trace => trace = true,'''),
        ('    if args[0] == "prepare" {',
         '    if args[0] == "prepare" {\n'
         '        if rng_mode.is_some() { return Err("prepare forbids --rng-mode".into()); }'),
        ('    let prepared_from_request = match request_file {',
         '    let rng_mode = rng_mode.ok_or("sim and bench require explicit --rng-mode balanced|stochastic")?;\n'
         '    let prepared_from_request = match request_file {'),
        ("simulate_prepared_gated(&prepared)",
         "simulate_prepared_gated(&prepared, rng_mode)"),
        ("simulate_prepared(&prepared).map_err",
         "simulate_prepared(&prepared, rng_mode).map_err"),
        ("    let request: Request =", '''    if rng_mode == RngMode::Balanced {
        return Err("legacy prototype has no typed balanced RNG; use prepared v2".into());
    }
    let request: Request ='''),
    ])
    # Audit machine-readable provenance from the engine's parsed flag.
    source = path.read_text()
    old = "simulate_prepared(black_box(&prepared))"
    assert source.count(old) == 2, "expected both bench mode runtime calls"
    source = source.replace(old, "simulate_prepared(black_box(&prepared), rng_mode)")
    assert source.count('"result": report, "checkpoint_certified": false,') == 1
    source = source.replace(
        '"result": report, "checkpoint_certified": false,',
        '"rng_mode": match parse_rng_mode(&args[6])? { '
        'RngMode::Balanced => "balanced", RngMode::Stochastic => "stochastic" },\n'
        '            "result": report, "checkpoint_certified": false,')
    path.write_text(source)
    assert "WOWSIM_RNG_MODE" not in rng.read_text()
    print("RUST_EXPLICIT_REQUIRED_RNG_PORT_APPLIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("engine_root", type=Path)
    args = parser.parse_args()
    port(args.engine_root)

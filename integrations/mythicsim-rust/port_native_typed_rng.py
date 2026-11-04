#!/usr/bin/env python3
"""Port the mandatory typed RNG argument into the selected MythicSim Rust runtime.

This is source code for the canonical Rust fork, NOT a Python RNG implementation.
No environment-selected mode, implicit stochastic fallback, or gate-only simulator.
Fail closed on upstream drift; the fork-sync workflow publishes only reviewed code.
"""
from pathlib import Path
import sys

def edit(root, name, transformations):
    path = root / name
    src = path.read_text()
    for old, new, count in transformations:
        actual = src.count(old)
        # A replacement may deliberately contain its original anchor (e.g.
        # the RNG enum inserted after RandomRequest). Reapplying the port to
        # an already-typed published fork must not duplicate that enum.
        if src.count(new) >= count and (
            actual == 0 or (old in new and actual == count)
        ):
            continue
        if actual != count:
            raise RuntimeError(f"RNG_SOURCE_DRIFT {name}: expected {count} of {old[:80]!r}, got {actual}")
        src = src.replace(old, new)
        if old not in new and src.count(old) != 0:
            raise RuntimeError(f"RNG_SOURCE_DRIFT {name}: old call sites remain after migration")
    if src != path.read_text():
        path.write_text(src)

def one(root, name, old, new):
    edit(root, name, [(old, new, 1)])


def ensure_rng_mode_import(root, name):
    """Accept typed RNG imports when newer native CLI imports are also present."""
    source = (root / name).read_text()
    start = source.find("use forever_engine::{")
    end = source.find("};", start) if start >= 0 else -1
    if start < 0 or end < 0:
        raise RuntimeError(f"RNG_SOURCE_DRIFT {name}: public engine import block missing")
    if "RngMode" in source[start:end]:
        return
    one(root, name, "PreparedError, Refusal, Request, Rules, SOURCE_REVISION,",
        "PreparedError, Refusal, Request, RngMode, Rules, SOURCE_REVISION,")

def add_explicit_mode_to_test_calls(source):
    """Add a typed stochastic mode to every legacy one-argument test call.

    Integration tests previously inherited the library's stochastic default.
    The public API has no default now, so preserve those semantics explicitly.
    The small balanced-delimiter scanner handles nested argument calls.
    """
    marker = "simulate_prepared("
    insertions = []
    cursor = 0
    while True:
        start = source.find(marker, cursor)
        if start < 0:
            break
        open_at = start + len("simulate_prepared")
        prefix = source[max(0, start - 12):start]
        if prefix.rstrip().endswith("fn"):
            cursor = open_at + 1
            continue
        parens, brackets, braces, commas = 1, 0, 0, 0
        state = "code"
        block_depth = 0
        escaped = False
        i = open_at + 1
        close_at = None
        while i < len(source):
            ch = source[i]
            nxt = source[i:i + 2]
            if state == "line_comment":
                if ch == "\\n":
                    state = "code"
            elif state == "block_comment":
                if nxt == "/*":
                    block_depth += 1
                    i += 1
                elif nxt == "*/":
                    block_depth -= 1
                    i += 1
                    if block_depth == 0:
                        state = "code"
            elif state in ("string", "char"):
                if escaped:
                    escaped = False
                elif ch == "\\\\":
                    escaped = True
                elif (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                    state = "code"
            else:
                if nxt == "//":
                    state = "line_comment"
                    i += 1
                elif nxt == "/*":
                    state = "block_comment"
                    block_depth = 1
                    i += 1
                elif ch == '"':
                    state = "string"
                elif ch == "'" and source.find("'", i + 1, min(len(source), i + 5)) >= 0:
                    state = "char"
                elif ch == "(":
                    parens += 1
                elif ch == ")":
                    parens -= 1
                    if parens == 0:
                        close_at = i
                        break
                elif ch == "[":
                    brackets += 1
                elif ch == "]":
                    brackets = max(0, brackets - 1)
                elif ch == "{":
                    braces += 1
                elif ch == "}":
                    braces = max(0, braces - 1)
                elif ch == "," and parens == 1 and brackets == 0 and braces == 0:
                    commas += 1
            i += 1
        if close_at is None:
            raise RuntimeError("RNG_TEST_CALL_PARSE_FAILED: simulate_prepared")
        if commas == 0:
            insert_at = close_at
            while insert_at > open_at + 1 and source[insert_at - 1].isspace():
                insert_at -= 1
            insertions.append(insert_at)
        cursor = close_at + 1
    for position in reversed(insertions):
        source = source[:position] + ", forever_engine::RngMode::Stochastic" + source[position:]
    return source, len(insertions)


def migrate_test_simulate_calls(root):
    """Migrate every selected-Rust integration test, not a hand-picked subset."""
    tests_root = root / "tests"
    if not tests_root.is_dir():
        raise RuntimeError("RNG_TEST_TREE_MISSING")
    changed = []
    existing_calls = 0
    for path in sorted(tests_root.rglob("*.rs")):
        original = path.read_text()
        existing_calls += original.count("simulate_prepared(")
        updated, count = add_explicit_mode_to_test_calls(original)
        if count:
            path.write_text(updated)
            changed.append((str(path.relative_to(root)), count))
    # A second fork-sync sees already-explicit calls and is a valid no-op.
    # An empty or unexpectedly different upstream test tree still fails closed.
    if not changed and not existing_calls:
        raise RuntimeError("RNG_TEST_CALLS_NOT_FOUND")
    return changed


def migrate(root):
    one(root, "src/core/rng.rs",
        "pub(crate) enum RandomRequest { Uniform01, Bernoulli(f64) }",
        """pub(crate) enum RandomRequest { Uniform01, Bernoulli(f64) }

/// Mandatory native runtime choice; never inferred from process environment.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RngMode { Balanced, Stochastic }

impl RngMode {
    pub fn parse_cli(text: &str) -> Result<Self, String> {
        match text {
            "balanced" => Ok(Self::Balanced),
            "stochastic" => Ok(Self::Stochastic),
            _ => Err(format!("invalid --rng-mode {text:?}; expected balanced or stochastic")),
        }
    }
}
""")
    one(root, "src/core/rng.rs",
        """    pub(crate) fn new(labeled: bool, seed: u64) -> Self {
        match std::env::var("WOWSIM_RNG_MODE").as_deref() {
            Ok("balanced") => return SimRng::Balanced(BalancedRng::default()),
            Ok("stochastic") | Err(std::env::VarError::NotPresent) => {},
            _ => panic!("unknown WOWSIM_RNG_MODE; expected stochastic or balanced"),
        }

        if labeled {""",
        """    pub(crate) fn new(mode: RngMode, labeled: bool, seed: u64) -> Self {
        if mode == RngMode::Balanced {
            return SimRng::Balanced(BalancedRng::default());
        }
        if labeled {""")
    edit(root, "src/core/rng.rs", [
        ("SimRng::new(false, 42)", "SimRng::new(RngMode::Stochastic, false, 42)", 1),
        ("SimRng::new(true, 42)", "SimRng::new(RngMode::Stochastic, true, 42)", 1),
    ])
    one(root, "src/core/fight.rs", "rng::SimRng,", "rng::{RngMode, SimRng},")
    one(root, "src/core/fight.rs",
        """    pub(crate) fn new(
        prepared: &PreparedV2,
        agent: A,""",
        """    pub(crate) fn new(
        prepared: &PreparedV2,
        rng_mode: RngMode,
        agent: A,""")
    one(root, "src/core/fight.rs",
        "rng: SimRng::new(prepared.sim.labeled_rng, prepared.sim.seed as u64),",
        "rng: SimRng::new(rng_mode, prepared.sim.labeled_rng, prepared.sim.seed as u64),")
    # Real selected-Rust RNG tests: both enum variants and CLI parser.
    rng_path = root / "src/core/rng.rs"
    tests = """
#[cfg(test)]
mod typed_rng_api_tests {
    use super::*;
    #[test]
    fn required_mode_parses_without_environment_fallback() {
        assert_eq!(RngMode::parse_cli("balanced"), Ok(RngMode::Balanced));
        assert_eq!(RngMode::parse_cli("stochastic"), Ok(RngMode::Stochastic));
        assert!(RngMode::parse_cli("").is_err());
        assert!(RngMode::parse_cli("unknown").is_err());
    }
    #[test]
    fn balanced_constructor_is_seed_independent_and_stochastic_is_not() {
        let mut balanced_a = SimRng::new(RngMode::Balanced, false, 101);
        let mut balanced_b = SimRng::new(RngMode::Balanced, false, 100001);
        for _ in 0..100 {
            assert_eq!(balanced_a.proc(0.17, "crit"), balanced_b.proc(0.17, "crit"));
            assert_eq!(balanced_a.next_f64("damage"), balanced_b.next_f64("damage"));
        }
        let mut stochastic_a = SimRng::new(RngMode::Stochastic, false, 101);
        let mut stochastic_b = SimRng::new(RngMode::Stochastic, false, 100001);
        assert_ne!(stochastic_a.next_f64("damage"), stochastic_b.next_f64("damage"));
    }
}
"""
    current = rng_path.read_text()
    if tests not in current:
        if "mod typed_rng_api_tests" in current:
            raise RuntimeError("RNG_TYPED_TEST_SOURCE_DRIFT")
        rng_path.write_text(current + tests)
    # Existing source-native Druid tests intentionally exercise stochastic mode.
    edit(root, "src/core/fight.rs", [
        ("DruidAgent::fight(&prepared)", "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)", 3),
    ])
    for cls in ("mage", "druid", "warlock", "shaman", "paladin", "priest", "rogue", "warrior", "hunter"):
        agent = f"src/classes/{cls}/agent.rs"
        prepared = f"src/classes/{cls}/prepared.rs"
        title = cls.title()
        one(root, agent,
            f"pub(crate) fn fight(prepared: &PreparedV2) -> Result<Fight<{title}Agent>, String> {{",
            f"pub(crate) fn fight(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode) -> Result<Fight<{title}Agent>, String> {{")
        one(root, agent, "Fight::new(prepared, ", "Fight::new(prepared, rng_mode, ") if "Fight::new(prepared, " in (root / agent).read_text() else one(root, agent, "Fight::new(\n            prepared,\n", "Fight::new(\n            prepared,\n            rng_mode,\n")
        one(root, prepared,
            "    prepared: &crate::contracts::prepared_v2::PreparedV2,\n) -> Result<crate::core::fight::FightReport, String> {",
            "    prepared: &crate::contracts::prepared_v2::PreparedV2,\n    rng_mode: crate::core::rng::RngMode,\n) -> Result<crate::core::fight::FightReport, String> {")
        one(root, prepared, f"{title}Agent::fight(prepared)?", f"{title}Agent::fight(prepared, rng_mode)?")
    clsfile = "src/classes.rs"
    one(root, clsfile,
        "pub(crate) fn run_prepared(\n    prepared: &crate::contracts::prepared_v2::PreparedV2,\n)",
        "pub(crate) fn run_prepared(\n    prepared: &crate::contracts::prepared_v2::PreparedV2,\n    rng_mode: crate::core::rng::RngMode,\n)")
    edit(root, clsfile, [
        ("::prepared::run_prepared(prepared)", "::prepared::run_prepared(prepared, rng_mode)", 9),
        ("::fight(prepared)?", "::fight(prepared, rng_mode)?", 18),
    ])
    one(root, clsfile,
        "    target_count: usize,\n) -> Result<serde_json::Value, String> {",
        "    target_count: usize,\n    rng_mode: crate::core::rng::RngMode,\n) -> Result<serde_json::Value, String> {")
    one(root, clsfile,
        "pub(crate) fn native_two_pull_windows(\n    prepared: &crate::contracts::prepared_v2::PreparedV2,\n)",
        "pub(crate) fn native_two_pull_windows(\n    prepared: &crate::contracts::prepared_v2::PreparedV2,\n    rng_mode: crate::core::rng::RngMode,\n)")
    eng = "src/engine/prepared.rs"
    one(root, eng,
        "pub fn simulate(prepared: &PreparedV2) -> Result<PreparedReport, PreparedError> {",
        "pub fn simulate(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode) -> Result<PreparedReport, PreparedError> {")
    one(root, eng, "    run(prepared)\n}", "    run(prepared, rng_mode)\n}")
    one(root, eng,
        "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize)",
        "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize, rng_mode: crate::core::rng::RngMode)")
    one(root, eng, "crate::classes::native_two_world_targets(prepared, target_count)",
        "crate::classes::native_two_world_targets(prepared, target_count, rng_mode)")
    one(root, eng,
        "pub fn native_two_pull_windows(prepared: &PreparedV2)",
        "pub fn native_two_pull_windows(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode)")
    one(root, eng, "crate::classes::native_two_pull_windows(prepared)",
        "crate::classes::native_two_pull_windows(prepared, rng_mode)")
    one(root, eng,
        "pub fn simulate_gated(prepared: &PreparedV2) -> Result<Gated, PreparedError> {",
        "pub fn simulate_gated(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode) -> Result<Gated, PreparedError> {")
    one(root, eng, "    run(prepared).map(|report| Gated::Simulated(Box::new(report)))",
        "    run(prepared, rng_mode).map(|report| Gated::Simulated(Box::new(report)))")
    one(root, eng, "fn run(prepared: &PreparedV2) -> Result<PreparedReport, PreparedError> {",
        "fn run(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode) -> Result<PreparedReport, PreparedError> {")
    one(root, eng, "classes::run_prepared(prepared)", "classes::run_prepared(prepared, rng_mode)")
    one(root, "src/lib.rs", "pub mod contracts;", "pub mod contracts;\npub use core::rng::RngMode;")
    main = "src/main.rs"
    ensure_rng_mode_import(root, main)
    one(root, main, "    let mut infile = None;", "    let mut rng_mode: Option<RngMode> = None;\n    let mut infile = None;")
    one(root, main,
        '            "--trace" if !trace => trace = true,',
        '''            "--rng-mode" => {
                index += 1;
                let value = args.get(index).ok_or("--rng-mode requires a value")?;
                if rng_mode.replace(RngMode::parse_cli(value)?).is_some() {
                    return Err("duplicate --rng-mode".into());
                }
            }
            "--trace" if !trace => trace = true,''')
    one(root, main,
        '    let prepared_from_request = match request_file {',
        '    let rng_mode = rng_mode.ok_or("sim and bench require explicit --rng-mode balanced|stochastic")?;\n    let prepared_from_request = match request_file {')
    one(root, main, "simulate_prepared_gated(&prepared)", "simulate_prepared_gated(&prepared, rng_mode)")
    edit(root, main, [
        ("simulate_prepared(&prepared)", "simulate_prepared(&prepared, rng_mode)", 1),
        ("simulate_prepared(black_box(&prepared))", "simulate_prepared(black_box(&prepared), rng_mode)", 2),
    ])
    # Native world commands must also choose explicitly; no hidden default.
    one(root, main,
        'if args.len() != 5 || args[1] != "--infile" || args[3] != "--targets" {',
        'if args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode" {')
    one(root, main,
        'let report = native_two_world_targets(&prepared, target_count)',
        'let mode = RngMode::parse_cli(&args[6])?;\n        let report = native_two_world_targets(&prepared, target_count, mode)')
    one(root, main,
        'if args.len() != 5 || args[1] != "--infile"\n            || args[3] != "--targets" || args[4] != "2" {',
        'if args.len() != 7 || args[1] != "--infile"\n            || args[3] != "--targets" || args[4] != "2" || args[5] != "--rng-mode" {')
    one(root, main,
        'let windows = native_two_pull_windows(&prepared)',
        'let mode = RngMode::parse_cli(&args[6])?;\n        let windows = native_two_pull_windows(&prepared, mode)')
    # Every integration test keeps its pre-port stochastic semantics, but
    # must now pass that choice explicitly to the no-default public API.
    migrated = migrate_test_simulate_calls(root)
    print("RUST_TYPED_RNG_TEST_CALLS_MIGRATED", migrated)
    # The old v1 frostbolt prototype does not use SimRng; its explicit mode
    # is nevertheless mandatory at the CLI. No false claim of balanced v1.
    print("RUST_TYPED_RNG_PORT_APPLIED")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: port_native_typed_rng.py RUST_CHECKOUT")
    migrate(Path(sys.argv[1]).resolve())

#!/usr/bin/env python3
"""Apply the native sim iteration-prefix CLI port after the typed-RNG port.

The option limits execution to the first N fights while preserving the original
prepared request identity. It is deliberately a CLI/runtime override, not a
mutation of simOptions in the source request.
"""
from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"NATIVE_SIM_ITERATIONS_SOURCE_DRIFT {label}: expected one anchor, got {count}: {old[:100]!r}"
        )
    return source.replace(old, new, 1)


def patch_main(root: Path) -> bool:
    path = root / "src/main.rs"
    source = path.read_text()
    if "fn apply_iterations_override(" in source:
        required = [
            '"--iterations" if args[0] == "sim" =>',
            "apply_iterations_override(&mut prepared, iterations_override)?;",
            "iterations_override.is_some() || gate || rotation_stats",
            "[--iterations N] [--rng-mode balanced|stochastic]",
        ]
        missing = [marker for marker in required if marker not in source]
        if missing:
            raise RuntimeError(f"NATIVE_SIM_ITERATIONS_PARTIAL_MAIN_PATCH:{missing}")
        return False

    helper = """fn apply_iterations_override(
    prepared: &mut PreparedV2,
    requested: Option<u32>,
) -> Result<(), String> {
    let Some(iterations) = requested else {
        return Ok(());
    };
    if iterations == 0 || iterations > prepared.sim.iterations {
        return Err(format!(
            "--iterations must be in 1..={} (the source request limit)",
            prepared.sim.iterations
        ));
    }
    // Limit the runtime prefix without rewriting the source request or its identity hash.
    prepared.sim.iterations = iterations;
    Ok(())
}

"""
    source = replace_once(
        source,
        "fn run() -> Result<(), Failure> {",
        helper + "fn run() -> Result<(), Failure> {",
        "main helper",
    )
    source = replace_once(
        source,
        "    let mut go_rules = false;\n",
        "    let mut go_rules = false;\n    let mut iterations_override: Option<u32> = None;\n",
        "main iterations state",
    )
    rng_block = """            "--rng-mode" => {
                index += 1;
                let value = args.get(index).ok_or("--rng-mode requires a value")?;
                if rng_mode.replace(RngMode::parse_cli(value)?).is_some() {
                    return Err("duplicate --rng-mode".into());
                }
            }
"""
    iterations_block = """            "--iterations" if args[0] == "sim" => {
                index += 1;
                let value = args.get(index).ok_or("--iterations requires a count")?;
                let parsed = value.parse::<u32>().map_err(|_| "invalid --iterations")?;
                if iterations_override.replace(parsed).is_some() {
                    return Err("duplicate --iterations".into());
                }
            }
"""
    source = replace_once(source, rng_block, rng_block + iterations_block, "main CLI parser")
    source = replace_once(
        source,
        "    if let Some(prepared) = prepared_v2(&input)? {\n",
        "    if let Some(mut prepared) = prepared_v2(&input)? {\n"
        "        apply_iterations_override(&mut prepared, iterations_override)?;\n",
        "prepared v2 branch",
    )
    source = replace_once(
        source,
        '    if gate || rotation_stats {\n        return Err("--gate and --rotation-stats require a prepared v2 input".into());\n    }\n',
        '    if iterations_override.is_some() || gate || rotation_stats {\n'
        '        return Err("--iterations, --gate and --rotation-stats require a prepared v2 input".into());\n'
        '    }\n',
        "legacy request guard",
    )
    usage_pairs = [
        (
            "forever-engine sim --infile REQUEST.json|PREPARED_V2.json [--outfile RESULT.json] [--trace] [--gate] [--rotation-stats]",
            "forever-engine sim --infile REQUEST.json|PREPARED_V2.json [--iterations N] [--rng-mode balanced|stochastic] [--outfile RESULT.json] [--trace] [--gate] [--rotation-stats]",
        ),
        (
            "forever-engine sim --request RAID_SIM_REQUEST.json [--scenario ID] [--outfile RESULT.json] [--gate] [--rotation-stats] [--go-rules]",
            "forever-engine sim --request RAID_SIM_REQUEST.json [--scenario ID] [--iterations N] [--rng-mode balanced|stochastic] [--outfile RESULT.json] [--gate] [--rotation-stats] [--go-rules]",
        ),
    ]
    for old, new in usage_pairs:
        source = replace_once(source, old, new, "sim usage")
    path.write_text(source)
    return True


def patch_cli_tests(root: Path) -> bool:
    path = root / "tests/cli.rs"
    source = path.read_text()
    marker = "fn sim_iteration_override_limits_prefix_without_rewriting_source_identity()"
    if marker in source:
        required = [
            '.args(["--rng-mode", "balanced", "--outfile"])',
            '.args(["--iterations", "3", "--rng-mode", "stochastic", "--outfile"])',
            '.args(["--rng-mode", "balanced"])',
        ]
        missing = [item for item in required if item not in source]
        if missing:
            raise RuntimeError(f"NATIVE_SIM_ITERATIONS_PARTIAL_CLI_TEST_PATCH:{missing}")
        return False

    source = replace_once(
        source,
        '        .args(["sim", "--infile"])\n        .arg(input)\n        .arg("--outfile")',
        '        .args(["sim", "--infile"])\n        .arg(input)\n        .args(["--rng-mode", "balanced", "--outfile"])',
        "invalid input sim test",
    )
    source = replace_once(
        source,
        '        .args(["sim", "--gate", "--infile"])\n        .arg(input)\n        .arg("--outfile")',
        '        .args(["sim", "--gate", "--infile"])\n        .arg(input)\n        .args(["--rng-mode", "balanced", "--outfile"])',
        "sim gate helper",
    )
    source = replace_once(
        source,
        '        .args(["sim", "--infile"])\n        .arg(&input)\n        .output()',
        '        .args(["sim", "--infile"])\n        .arg(&input)\n        .args(["--rng-mode", "balanced"])\n        .output()',
        "ungated sim test",
    )
    test = """#[test]
fn sim_iteration_override_limits_prefix_without_rewriting_source_identity() {
    let directory = std::env::temp_dir().join(format!(
        "forever-iteration-override-{}",
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("fixtures/mage/prepared-v2/reference-clearcasting.prepared.json");
    let mut prepared: serde_json::Value =
        serde_json::from_slice(&fs::read(source).unwrap()).unwrap();
    prepared["sim"]["iterations"] = serde_json::json!(10);
    let request_sha256 = prepared["request_sha256"].clone();
    let input = directory.join("input.prepared.json");
    let output = directory.join("result.json");
    let input_bytes = serde_json::to_vec(&prepared).unwrap();
    fs::write(&input, &input_bytes).unwrap();

    let result = Command::new(env!("CARGO_BIN_EXE_forever-engine"))
        .args(["sim", "--gate", "--infile"])
        .arg(&input)
        .args(["--iterations", "3", "--rng-mode", "stochastic", "--outfile"])
        .arg(&output)
        .output()
        .unwrap();
    assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stderr));
    let report: serde_json::Value =
        serde_json::from_slice(&fs::read(&output).unwrap()).unwrap();
    assert_eq!(report["result"]["iterationsDone"], 3);
    assert_eq!(report["request_sha256"], request_sha256);
    assert_eq!(fs::read(&input).unwrap(), input_bytes);

    for count in ["0", "11"] {
        let refused = Command::new(env!("CARGO_BIN_EXE_forever-engine"))
            .args(["sim", "--gate", "--infile"])
            .arg(&input)
            .args(["--iterations", count, "--rng-mode", "stochastic"])
            .output()
            .unwrap();
        assert!(!refused.status.success());
        assert!(String::from_utf8_lossy(&refused.stderr).contains("source request limit"));
    }
    fs::remove_dir_all(directory).unwrap();
}

"""
    source = replace_once(
        source,
        "#[test]\nfn sim_with_the_gate_simulates_a_supported_input_in_one_process() {",
        test + "#[test]\nfn sim_with_the_gate_simulates_a_supported_input_in_one_process() {",
        "CLI integration test",
    )
    path.write_text(source)
    return True


def patch_readme(root: Path) -> bool:
    path = root / "README.md"
    source = path.read_text()
    marker = "For a bounded comparison, `sim --iterations N`"
    if marker in source:
        return False
    anchor = """and prints the same JSON result that Go prints. You do not need Go to build or test
the engine."""
    replacement = anchor + """

For a bounded comparison, `sim --iterations N` runs only the first N iterations of a prepared
request without rewriting its source fields or `request_sha256`. N must be between 1 and the
request's original `simOptions.iterations`."""
    source = replace_once(source, anchor, replacement, "README quick start")
    path.write_text(source)
    return True


def patch(root: Path) -> dict:
    return {
        "main": patch_main(root),
        "cli_tests": patch_cli_tests(root),
        "readme": patch_readme(root),
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    print(patch(root))

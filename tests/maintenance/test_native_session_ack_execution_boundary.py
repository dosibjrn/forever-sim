"""Regress the native/world workflow boundary without auditing Rust internals.

This tests Forever-owned CI invocation only. The selected Rust engine owns
implementation details and its CLI/world outcomes remain the authority.
"""
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/native-source-world-smoke.yml")


def test_selected_native_world_job_reaches_executable_checks_without_source_greps():
    text = WORKFLOW.read_text(encoding="utf-8")
    setup = text.split(
        "      - name: Compile the exact selected Rust fork and verify its RNG CLI\n",
        1)[1].split(
        "      - name: Verify explicit Balanced and Stochastic modes in real native",
        1)[0]
    # Pin exact code revision, build the selected binary, then test its CLI;
    # don't gate a real Rust/2D regression on implementation-specific symbols.
    assert 'test "$selected" = "$actual"' in setup
    assert "cargo build --locked --manifest-path" in setup
    assert "grep -Fq" not in setup
    assert 'if "$binary" sim --infile "$fixture"' in setup
    assert 'if "$binary" sim --rng-mode bogus --infile "$fixture"' in setup

    # Source changes still exercise native + 2D behavior, but test-only
    # edits must not schedule a redundant Rust build or native-paid worlds.
    trigger = text.split("jobs:", 1)[0]
    assert "tests/test_" not in trigger
    # P7.5 historical rotation evidence is consumed by separate P7 tests,
    # not by this expensive selected-Rust/2D world job. Editing archived
    # evidence must not compile Rust or re-pay unrelated world scenarios.
    assert "docs/evidence/druid-l60-balance/p7.5/historical_wf678_winner_axes.json" not in trigger
    # P4/P5 gate-helper and legacy Warlock 100-mob edits do not enter this
    # selected-Rust/2D smoke; both have separate focused workflow coverage.
    assert "tools/wf_gate_p4_p5_partial.py" not in trigger
    assert "tools/wf_warlock_l20_100mob.py" not in trigger
    assert "- 'integrations/mythicsim-rust/engine'" in trigger
    # The downstream scenario checks still exercise native + 2D behavior.
    assert "native_source_control(binary, request, 5, rng_mode=mode)" in text
    assert "probe.run(binary, request, distance=15.0" in text
    assert "live_two_world_pulls.py" in text
    assert "--require-native-health-damage" in text

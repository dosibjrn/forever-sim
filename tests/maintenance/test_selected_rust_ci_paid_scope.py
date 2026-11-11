"""Keep paid selected-Rust probes off Forever-only adapter PRs.

This is CI resource/scope protection, not a new M1 gate or native mechanic test.
"""
from pathlib import Path
import re


WORKFLOW = (Path(__file__).resolve().parents[2] /
            ".github/workflows/rust-submodule-verify.yml")


def test_selected_rust_paid_probes_only_run_on_pin_or_opt_in():
    text = WORKFLOW.read_text(encoding="utf-8")
    cheap = "      - name: Run focused Forever-owned native P3 adapter regressions"
    detector = "      - name: Detect selected Rust pin change"
    paid = "      - name: Build the exact selected engine"
    assert text.index(cheap) < text.index(detector) < text.index(paid)
    assert 'base="${{ github.event.pull_request.base.sha }}"' in text
    assert ('git diff --name-only "$base" HEAD -- .gitmodules '
            'integrations/mythicsim-rust/engine') in text
    assert "echo 'changed=false' >> \"$GITHUB_OUTPUT\"" in text

    # Ordinary Python-only pushes never build native or repay probes. An
    # explicitly labeled P3 producer PR may build and run paid no-record once.
    tail = text[text.index(paid):]
    steps = re.split(r"(?=^      - (?:name:|uses:))", tail, flags=re.MULTILINE)
    steps = [step for step in steps if step.startswith("      - ")]
    assert steps, "selected Rust native verification steps must remain guarded"
    pin = "steps.selected_rust_change.outputs.changed == 'true'"
    opt_in = ("github.event.action == 'labeled' && "
              "github.event.label.name == 'p3-native-paid-no-record'")
    for step in steps:
        headline = step.splitlines()[0]
        guard = re.search(r"^        if: (.+)$", step, flags=re.MULTILINE)
        assert guard is not None, headline
        condition = guard.group(1)
        if ("Build the exact selected engine" in headline
                or "Probe unified get_options JSON" in headline):
            # Pin changes get cheap native transport smoke; explicit labels
            # get the binary even if Forever's P3-only code changed.
            assert pin in condition and opt_in in condition, headline
        else:
            # No-record paid executions and their artifact upload require an
            # explicit label even on a gitlink-changing PR.
            assert opt_in in condition and pin not in condition, headline
        if "actions/upload-artifact@v4" in headline:
            assert "always()" in condition, headline


def test_unaccepted_p3_probes_require_fresh_opt_in_label():
    """PR pushes keep Rust options smoke, but cannot replay paid P3 diagnostics."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [opened, synchronize, reopened, labeled]" in workflow
    assert "Build the exact selected engine" in workflow
    assert "Probe unified get_options JSON on two class/level pairs" in workflow

    def step_guard(name):
        section = workflow.split(f"      - name: {name}\n", 1)
        assert len(section) == 2, name
        body = section[1].split("\n      - name:", 1)[0]
        guard = re.search(r"^        if: (.+)$", body, flags=re.MULTILINE)
        assert guard is not None, name
        return guard.group(1)

    pin = "steps.selected_rust_change.outputs.changed == 'true'"
    label = ("github.event.action == 'labeled' && "
             "github.event.label.name == 'p3-native-paid-no-record'")
    for name in (
        "Run no-record Rogue L20 P3 native capability and gate receipt",
        "Run no-record Priest and Mage L20 P3 with native item options",
        "Run no-record Shaman L20 P3 with native item options",
        "Run no-record Paladin L20 P3 with native player context and item options",
        "Run no-record Mage L30 P3 with native item options",
    ):
        guard = step_guard(name)
        assert label in guard and pin not in guard, name

    # Rust pin changes still get native transport smoke, while a labeled
    # Forever-only P3 source change also receives the native binary it needs.
    for name in (
        "Build the exact selected engine",
        "Probe unified get_options JSON on two class/level pairs",
    ):
        guard = step_guard(name)
        assert pin in guard and label in guard, name

    upload = workflow.split("      - name: Upload no-record native P3 reports", 1)
    assert len(upload) == 2
    guard = re.search(r"^        if: (.+)$", upload[1], flags=re.MULTILINE)
    assert guard is not None
    assert "always()" in guard.group(1)
    assert label in guard.group(1) and pin not in guard.group(1)


def test_warlock_shoot_cargo_regression_is_explicitly_requested():
    """One selected Rust pin PR should not launch a second Cargo-build job.

    The underlying native Shoot test stays available through manual dispatch,
    and normal selected pin PRs still run the shared engine verification.
    This is a CI cost/duplicate-work rule, not an M1 acceptance predicate.
    """
    shoot = WORKFLOW.with_name("warlock-native-shoot-integration.yml")
    text = shoot.read_text(encoding="utf-8")
    assert text.count("\non:\n") == 1
    events = text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "  workflow_dispatch:\n" in events
    for automatic in ("  pull_request:", "  push:", "  schedule:"):
        assert automatic not in events, (
            f"Warlock Shoot test may only be run explicitly: {automatic}"
        )
    assert (
        "cargo test --locked "
        "warlock_wand_registers_native_shoot_for_apl_and_combat -- --nocapture"
    ) in text
    assert "Assert selected Rust gitlink and official source repository" in text
    assert "working-directory: integrations/mythicsim-rust/engine" in text

    pin_workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:\n" in pin_workflow
    assert "      - integrations/mythicsim-rust/engine\n" in pin_workflow
    assert "      - name: Require exact selected engine pin" in pin_workflow
    assert "      - name: Build the exact selected engine" in pin_workflow
    assert "      - name: Probe unified get_options JSON on two class/level pairs" in pin_workflow

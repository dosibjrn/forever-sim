"""Keep paid selected-Rust probes off Forever-only adapter PRs.

This is CI resource/scope protection, not a new M1 gate or native mechanic test.
"""
from pathlib import Path
import re


WORKFLOW = (Path(__file__).resolve().parents[2] /
            ".github/workflows/rust-submodule-verify.yml")


def test_selected_rust_paid_probes_only_run_when_pin_changes():
    text = WORKFLOW.read_text(encoding="utf-8")
    cheap = "      - name: Run focused Forever-owned native P3 adapter regressions"
    detector = "      - name: Detect selected Rust pin change"
    paid = "      - name: Build the exact selected engine"
    assert text.index(cheap) < text.index(detector) < text.index(paid)
    assert 'base="${{ github.event.pull_request.base.sha }}"' in text
    assert ('git diff --name-only "$base" HEAD -- .gitmodules '
            'integrations/mythicsim-rust/engine') in text
    assert "echo 'changed=false' >> \"$GITHUB_OUTPUT\"" in text

    # A Python-only or gate-runner PR still executes the focused tests, but
    # none of the expensive Rust build, no-record probes or uploads.
    tail = text[text.index(paid):]
    steps = re.split(r"(?=^      - (?:name:|uses:))", tail, flags=re.MULTILINE)
    steps = [step for step in steps if step.startswith("      - ")]
    assert steps, "selected Rust native verification steps must remain guarded"
    condition = "steps.selected_rust_change.outputs.changed == 'true'"
    for step in steps:
        headline = step.splitlines()[0]
        guard = re.search(r"^        if: (.+)$", step, flags=re.MULTILINE)
        assert guard is not None, headline
        assert condition in guard.group(1), headline
        if "actions/upload-artifact@v4" in headline:
            assert "always()" in guard.group(1), headline

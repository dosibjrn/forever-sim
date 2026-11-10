"""Keep accepted L60 P3 proof-only native replays out of engine-pin CI.

The original production PASSes are permanent. Selected Rust pin verification
still exercises options transport and still-unaccepted checkpoint integration;
no old 300-second paid P3 probe or duplicate artifact is required for a PASS.
"""
from pathlib import Path
import re

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/rust-submodule-verify.yml"

RETIRED_STEPS = (
    "Probe Feral L60 P3 on selected native engine (no record)",
    "Run Mage Arcane L60 unified-options native P3 (no record)",
    "Run Mage Fire L60 selected-native P3 (no record)",
    "Run Mage Frost L60 selected-native P3 (no record)",
    "Run Paladin Retribution L60 selected-native P3 (no record)",
    "Run Paladin Protection L60 selected-native TPS P3 (no record)",
)

STILL_UNACCEPTED_STEPS = (
    "Run no-record Rogue L20 P3 native capability and gate receipt",
    "Run no-record Priest and Mage L20 P3 with native item options",
    "Run no-record Shaman L20 P3 with native item options",
    "Run no-record Paladin L20 P3 with native player context and item options",
    "Run no-record Mage L30 P3 with native item options",
)


def test_accepted_l60_p3_gate_replays_and_attachments_are_retired():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for step in RETIRED_STEPS:
        assert f"- name: {step}" not in workflow
    assert "paladin-retribution-l60-native-p3-no-record" not in workflow
    assert "paladin-protection-l60-native-p3-no-record" not in workflow
    assert not re.search(
        r"tools/wf_gate\\.py --class (?:druid|mage|paladin) --level 60\\b",
        workflow,
    )


def test_pin_verification_keeps_native_transport_and_unaccepted_p3_coverage():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Build the exact selected engine" in workflow
    assert "Probe unified get_options JSON on two class/level pairs" in workflow
    assert 'cargo build --locked --bin forever-engine' in workflow
    for step in STILL_UNACCEPTED_STEPS:
        assert f"- name: {step}" in workflow
    assert "timeout 600s python tools/wf_gate.py --class rogue --level 20" in workflow

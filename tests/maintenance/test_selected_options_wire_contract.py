"""Selected Rust options smoke verifies Forever transport, not Warcraft rules.

Exercise the exact Python probe embedded in the CI workflow with synthetic
native responses. Rust may evolve legality/coverage statuses without needing
a Forever acceptance exception.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rust-submodule-verify.yml"
PROBE_MARKER = 'python3 - "$class" "$level" "$output" <<\'PY\''


def _probe_script() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count(PROBE_MARKER) == 1
    body = workflow.split(PROBE_MARKER, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(body)


def _run_probe(*, class_name="warrior", level=60, **overrides):
    payload = {
        "schema_version": 1,
        "class": class_name,
        "level": level,
        "source_revision": "rust-fixture",
        "spells": [],
        "items": [{"eligibility": "native_eligible"}],
        "talents": {"status": "unsupported"},
        "coverage": {
            "spell_learnability_complete": True,
            "talent_prerequisites_complete": False,
            "item_eligibility_complete": True,
            "native_item_status": "native_eligible",
        },
    }
    payload.update(overrides)
    with tempfile.TemporaryDirectory() as directory:
        filename = Path(directory) / "native-options.json"
        filename.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-c", _probe_script(),
             class_name, str(level), str(filename)],
            capture_output=True, text=True, check=False,
        )


def test_native_coverage_and_legality_are_not_forever_ci_gates():
    # These valid native results contradicted the former frozen Warrior/Mage
    # status assumptions. They are now forwarded/printed as evidence, not vetoes.
    for klass, level, eligibility in (
        ("warrior", 60, "native_eligible"),
        ("mage", 20, "proficiency_unverified"),
    ):
        result = _run_probe(
            class_name=klass, level=level,
            items=[{"eligibility": eligibility}],
            talents={"status": "unsupported"},
            coverage={"item_eligibility_complete": True, "notes": []},
        )
        assert result.returncode == 0, result.stderr
        assert "UNIFIED_OPTIONS_JSON" in result.stdout


def test_unknown_native_coverage_status_does_not_prevent_transport():
    result = _run_probe(coverage={"native_item_status": "new_source_status"})
    assert result.returncode == 0, result.stderr


def test_corrupt_wire_identity_still_fails():
    result = _run_probe(schema_version=999)
    assert result.returncode != 0
    assert "AssertionError" in result.stderr

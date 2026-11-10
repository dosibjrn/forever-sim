"""Guard against repeat M1 native runs for permanently accepted gate pairs."""

import csv
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/m1-on-demand-record.yml"
FIELDS = ("class", "level", "spec", "gate", "status")


def _workflow_filter_source() -> str:
    """Execute the Python snippet embedded in the real Actions preflight."""
    source = WORKFLOW.read_text(encoding="utf-8")
    marker = """python3 - "$RUNNER_TEMP/m1-current-preflight.tsv" "${unique[@]}" <<'PY'\n"""
    assert source.count(marker) == 1
    snippet = source.split(marker, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(snippet) + "\n"


def _preflight(tmp_path, rows, targets, *, fields=FIELDS):
    ledger = tmp_path / "M1_PASSES.tsv"
    with ledger.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return subprocess.run(
        [sys.executable, "-", str(ledger), *targets],
        input=_workflow_filter_source(), capture_output=True, text=True,
        check=False,
    )


def test_mixed_m1_batch_skips_pass_but_preserves_partial_and_missing(tmp_path):
    result = _preflight(tmp_path, [
        dict(zip(FIELDS, ("warlock", "20", "unrestricted", "P3", "PASS"))),
        dict(zip(FIELDS, ("warlock", "20", "unrestricted", "P4", "PARTIAL"))),
    ], [
        "warlock:20:unrestricted:P3",
        "warlock:20:unrestricted:P4",
        "druid:30:balance:P7.4",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "warlock:20:unrestricted:P4",
        "druid:30:balance:P7.4",
    ]
    assert "M1_ALREADY_ACCEPTED_SKIP warlock:20:unrestricted:P3" in result.stderr


def test_all_accepted_m1_targets_skip_native_compilation_and_publication(tmp_path):
    result = _preflight(tmp_path, [
        dict(zip(FIELDS, ("warlock", "20", "unrestricted", "P3", "PASS"))),
    ], ["warlock:20:unrestricted:P3"])
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'if (( ${#unique[@]} == 0 )); then' in source
    assert "printf 'skip_all=true\\n'" in source
    for step in (
        "Checkout current main, without saved write credentials",
        "Set up Python",
        "Publish M1 ledger and README chart atomically",
    ):
        assert (
            f"- name: {step}\n"
            "        if: steps.targets.outputs.skip_all != 'true'"
        ) in source
    assert (
        "if: steps.targets.outputs.invalidate != 'true' "
        "&& steps.targets.outputs.skip_all != 'true'"
    ) in source
    # The build-enable flags must be derived from filtered candidates.
    assert source.index("mapfile -t unique <<<") < source.index(
        "p7_needed=false\n", source.index("mapfile -t unique <<<"))
    assert source.index("mapfile -t unique <<<") < source.index(
        "warlock_shared_needed=false\n", source.index("mapfile -t unique <<<"))


@pytest.mark.parametrize("fields,rows,reason", [
    (("class", "level", "spec", "gate"), [], "M1_PREFLIGHT_INVALID_LEDGER_SCHEMA"),
    (FIELDS, [dict(zip(FIELDS, ("warlock", "20", "unrestricted", "P3", "UNKNOWN")))],
     "M1_PREFLIGHT_INVALID_LEDGER_STATUS"),
])
def test_m1_preflight_fails_closed_on_malformed_ledger(tmp_path, fields, rows, reason):
    result = _preflight(
        tmp_path, rows, ["warlock:20:unrestricted:P3"], fields=fields)
    assert result.returncode != 0
    assert reason in result.stderr


def test_m1_preflight_reads_current_main_and_never_touches_receipts():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert (
        'gh api "repos/$GITHUB_REPOSITORY/contents/'
        'docs/planning/M1_PASSES.tsv?ref=main"'
    ) in source
    assert source.index("M1_ALREADY_ACCEPTED_SKIP") < source.index(
        "Checkout current main, without saved write credentials")
    assert "python tools/m1_progress.py --invalidate" in source
    assert "python tools/wf_gate.py" in source

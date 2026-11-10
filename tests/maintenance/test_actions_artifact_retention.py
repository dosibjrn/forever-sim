"""Artifact upload steps must not silently inherit the 90-day Actions default.

This is an operational storage regression, not a Warcraft gate or an
additional M1 acceptance predicate. Native no-record evidence is still uploaded.
"""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UPLOAD = re.compile(r"\buses:\s*actions/upload-artifact@v4\s*$")
RETENTION = re.compile(r"\s*retention-days:\s*(\d+)\s*$")


def test_actions_upload_steps_set_explicit_bounded_retention():
    uploads = 0
    for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
        lines = workflow.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not UPLOAD.search(line):
                continue
            uploads += 1
            indent = len(line) - len(line.lstrip(" "))
            step_body = []
            for following in lines[index + 1:]:
                if following.strip() and not following.lstrip().startswith("#"):
                    following_indent = len(following) - len(following.lstrip(" "))
                    # Same-indent "with:" still belongs to this upload step.
                    # Stop at the next list step or a containing YAML key.
                    if (following_indent < indent
                            or (following_indent == indent
                                and following.lstrip().startswith("- "))):
                        break
                step_body.append(following)
            declared = [int(match.group(1))
                        for row in step_body
                        if (match := RETENTION.fullmatch(row))]
            assert len(declared) == 1, (
                f"{workflow.relative_to(ROOT)}:{index + 1}: "
                "upload-artifact must declare retention-days exactly once"
            )
            assert 1 <= declared[0] <= 30, (
                f"{workflow.relative_to(ROOT)}:{index + 1}: "
                "use a deliberate retention of 1–30 days, not the 90-day default"
            )
    assert uploads > 0


def test_rust_pin_pr_no_record_p3_uploads_expire_after_seven_days():
    """Repeatable no-record native P3 PR diagnostics should not occupy a month.

    This does not prune accepted M1 receipts or issue-pinned evidence; it only
    bounds new artifacts from the selected-Rust-pin verification workflow.
    """
    workflow = ROOT / ".github/workflows/rust-submodule-verify.yml"
    lines = workflow.read_text(encoding="utf-8").splitlines()
    upload_indices = [index for index, line in enumerate(lines)
                      if UPLOAD.search(line)]
    assert len(upload_indices) == 3, "review retention when adding a PR artifact"
    for index in upload_indices:
        indent = len(lines[index]) - len(lines[index].lstrip(" "))
        step_body = []
        for following in lines[index + 1:]:
            if following.strip() and not following.lstrip().startswith("#"):
                following_indent = len(following) - len(following.lstrip(" "))
                if (following_indent < indent or
                        (following_indent == indent and
                         following.lstrip().startswith("- "))):
                    break
            step_body.append(following)
        retention = [int(match.group(1)) for row in step_body
                     if (match := RETENTION.fullmatch(row))]
        assert retention == [7], f"{workflow.name}:{index + 1}: expected seven days"


def test_completed_warlock_one_shot_paid_ci_is_replaced():
    """Retire completed per-level PR/push/dispatch workflows, keep fast coverage.

    Historic native 100-target observations and uploaded evidence are NOT
    deleted. The shared route CI tests proposal and publication without
    accidentally repaying already executed Warlock levels.
    """
    retired = [f"work2-warlock-l{level}-native-trial.yml" for level in range(21, 26)]
    retired += [
        "work2-warlock-l21-native-successor.yml",
        "work2-warlock-l22-native-successor.yml",
        *(f"work2-warlock-l{level}-native-trial.yml" for level in range(26, 29)),
        *(f"work2-warlock-l{level}-native-successor.yml" for level in range(29, 33)),
        "work2-warlock-l33-l40-native-batch.yml",
        # Already-paid L20 experiments must not stay as dispatchable
        # native 100-target workloads after the route advanced to L44.
        "warlock-l20-100mob-chain.yml",
        "warlock-l20-talent-apl-100mob.yml",
        # L20 source re-anchor and L40 alternative were already paid;
        # L41 native selection is superseded by the paid L41-L44 route.
        # These fixed-source one-shots must not be re-dispatched on
        # unrelated PRs; reusable range CI and M1 cold gates stay live.
        "work2-warlock-l20-native-reanchor.yml",
        "work2-warlock-l40-paid-alternative.yml",
        "work1-warlock-l41-native-selection.yml",
        # This completed L20 30/300s experiment already yielded real paid
        # receipts; its old PR-open/dispatch job must not restart it.
        "work2-warlock-l20-paid-cold.yml",
        # All three L20 P7.1/P7.2/P7.3 axes are officially PASS;
        # retain source-native forwarding tests, not paid one-shot launchers.
        "work2-warlock-l20-p71-native.yml",
        "work2-warlock-l20-p73-native.yml",
        # Warlock L20 P3 officially PASS on 2026-11-09; no paid no-record replay.
        "work2-warlock-l20-native-p3.yml",
    ]
    for name in retired:
        obsolete = ROOT / ".github/workflows" / name
        assert not obsolete.exists(), f"completed paid per-level CI still active: {name}"

    shared = (ROOT / ".github/workflows/work2-warlock-route-guide.yml").read_text(
        encoding="utf-8")
    for trigger in (
        "      - tools/wf_warlock_next_level_source.py",
        "      - tests/test_work2_warlock_next_level_source.py",
    ):
        assert trigger in shared, "native proposal changes must trigger fast shared CI"
    assert (
        "run: python -m pytest -q tests/test_work2_warlock_route_guide.py "
        "tests/test_work2_warlock_next_level_source.py"
    ) in shared, "shared workflow must execute both real Forever-owned regression suites"

def test_accepted_druid_l30_one_shot_paid_workflows_remain_retired():
    """L30 P7.1/P7.2 are official M1 PASSes, not repeatable paid experiments.

    Keep unaccepted-gate dispatch available through the generic M1 workflow.
    Historical native requests, source code and receipts are not deleted.
    """
    for name in (
        "work1-druid-l30-p71-native.yml",
        "work1-druid-l30-p72-native.yml",
    ):
        assert not (ROOT / ".github/workflows" / name).exists(), (
            f"accepted Druid L30 gate must not remain a paid one-shot: {name}"
        )
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()



def test_accepted_druid_l30_p73_retired_without_losing_native_forwarding():
    """Recorded L30 P7.3 PASS is permanent; do not pay a branch one-shot again.

    Only the old repeatable workflow is retired. Native candidate/refusal tests
    remain executable on source changes; generic M1 stays available for other
    still-unaccepted gates. Historical reference receipts are untouched.
    """
    assert not (ROOT / ".github/workflows/work1-druid-l30-p73-native.yml").exists()
    ci = (ROOT / ".github/workflows/generic-source-search-regressions.yml").read_text(
        encoding="utf-8")
    assert "      - 'tests/test_work1_druid_l30_p73.py'\n" in ci
    for source in ("tools/wf_gate_p7_3_live.py",
                   "src/engine_client/native_talent_proposals.py"):
        assert "      - '" + source + "'\n" in ci
    assert "          tests/test_work1_druid_l30_p73.py\n" in ci
    assert "          tests/gates/test_wf_gate_p7_3_live.py\n" in ci
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()


def test_retired_l20_cold_keeps_fast_forever_regressions():
    """Cold producer and native refusal bridge still receive cheap PR tests."""
    ci = (ROOT / ".github/workflows/warlock-native-optimizer-regressions.yml").read_text(
        encoding="utf-8")
    for path in (
        "tools/wf_warlock_l20_native_cold.py",
        "tools/wf_warlock_l20_gate_bridge.py",
        "tests/test_work2_warlock_native_cold.py",
        "tests/test_work2_warlock_native_cold_cli.py",
        "tests/test_work2_warlock_gate_bridge.py",
    ):
        assert f"      - {path}" in ci, f"PR trigger missing for {path}"
        if path.startswith("tests/"):
            assert f"          {path}" in ci, f"cheap regression suite lost {path}"
    assert "python -m pytest -q" in ci
    assert not (ROOT / ".github/workflows/work2-warlock-l20-paid-cold.yml").exists()


def test_accepted_warlock_l20_p7_axes_keep_fast_source_forwarding_tests():
    """Protect useful Forever transport tests, never reschedule accepted paid P7."""
    ci = (ROOT / ".github/workflows/warlock-native-optimizer-regressions.yml").read_text(
        encoding="utf-8")
    for path in (
        "tools/wf_p7_native_reference.py",
        "tools/wf_gate_p7_1_live.py",
        "tools/wf_gate_p7_2_live.py",
        "tools/wf_gate_p7_3_live.py",
        "src/engine_client/native_talent_proposals.py",
        "fixtures/warlock-l20-p71.request.json",
        "docs/evidence/native-references/warlock-l20-unrestricted/**",
        "tests/test_work2_warlock_l20_p71.py",
        "tests/test_work2_warlock_l20_p72.py",
        "tests/test_work2_warlock_l20_p73.py",
    ):
        assert ci.count("      - " + path + "\n") == 2, (
            "PR and push triggers must cover " + path)
    for name in ("p71", "p72", "p73"):
        assert "          tests/test_work2_warlock_l20_" + name + ".py\n" in ci
    assert "          submodules: true\n" in ci, (
        "fixture provenance test reads the selected native Rust submodule")
    assert not (ROOT / ".github/workflows/work2-warlock-l20-p71-native.yml").exists()
    assert not (ROOT / ".github/workflows/work2-warlock-l20-p73-native.yml").exists()


def test_accepted_warlock_l20_p3_keeps_fast_native_transport_coverage():
    """Previously accepted P3 stays closed; its source/refusal adapters still regress.

    Do not rebuild Rust or re-pay the accepted L20 gate on unrelated PRs.
    """
    ci = (ROOT / ".github/workflows/warlock-native-optimizer-regressions.yml").read_text(
        encoding="utf-8")
    for path in (
        "tools/wf_gate_p3_live.py",
        "tools/wf_native_warlock_l20_equipped.py",
        "integrations/mythicsim-rust/native_p3_equipped.py",
        "integrations/mythicsim-rust/native_executor.py",
        "tests/test_work2_warlock_l20_native_p3.py",
        "tests/test_work2_warlock_l20_equipped_source.py",
    ):
        assert ci.count("      - " + path + "\n") == 2, (
            f"cheap PR and push coverage missing for {path}")
    for path in (
        "tests/test_work2_warlock_l20_native_p3.py",
        "tests/test_work2_warlock_l20_equipped_source.py",
    ):
        assert "          " + path + "\n" in ci
    assert not (ROOT / ".github/workflows/work2-warlock-l20-native-p3.yml").exists()
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()

def test_native_ack_ci_does_not_rerun_completed_warlock_l20_cold_search():
    """Real native/2D ACK tests stay live without replaying the paid 300s job."""
    shared = (ROOT / ".github/workflows/native-session-ack-regressions.yml"
              ).read_text(encoding="utf-8")
    assert "  clock-ack:" in shared
    assert "  source-health-world:" in shared
    assert "  warlock-l20-cold-30-300:" not in shared
    assert "wf_warlock_l20_native_cold.py \\" not in shared
    assert "--budget 300 --snapshot 30 --seed 20261109" not in shared

    # Cheap source/transport coverage survives on PRs; this must not prevent
    # genuinely unaccepted P4/P5 cold runs via the official generic recorder.
    fast = (ROOT / ".github/workflows/warlock-native-optimizer-regressions.yml"
            ).read_text(encoding="utf-8")
    assert "          tests/test_work2_warlock_native_cold.py" in fast
    assert "          tests/test_work2_warlock_native_cold_cli.py" in fast
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()

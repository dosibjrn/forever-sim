"""Artifact upload steps must not silently inherit the 90-day Actions default.

This is an operational storage regression, not a Warcraft gate or an
additional M1 acceptance predicate. Still-unaccepted native P3 evidence is uploaded.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess


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


def test_rust_pin_unaccepted_p3_upload_expires_after_seven_days():
    """Only still-unaccepted P3 diagnostic artifacts may be uploaded on pin changes.

    This does not prune accepted M1 receipts or issue-pinned evidence; it only
    bounds new artifacts from the selected-Rust-pin verification workflow.
    """
    workflow = ROOT / ".github/workflows/rust-submodule-verify.yml"
    lines = workflow.read_text(encoding="utf-8").splitlines()
    upload_indices = [index for index, line in enumerate(lines)
                      if UPLOAD.search(line)]
    assert len(upload_indices) == 1, "accepted L60 P3 artifact uploads must stay retired"
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
    assert "  pull_request:\n" in ci
    assert "\n  push:\n" not in ci, "dated feature-branch pushes double-run the PR suite"
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
        assert ci.count("      - " + path + "\n") == 1, (
            "PR trigger must cover " + path)
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
        assert ci.count("      - " + path + "\n") == 1, (
            f"cheap PR coverage missing for {path}")
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
    native_world = (ROOT / ".github/workflows/native-source-world-smoke.yml"
                    ).read_text(encoding="utf-8")
    assert "  clock-ack:" in shared
    assert "  source-health-world:" not in shared
    assert "  source-health-world:" in native_world
    for ci in (shared, native_world):
        assert "  warlock-l20-cold-30-300:" not in ci
        assert "wf_warlock_l20_native_cold.py \\" not in ci
        assert "--budget 300 --snapshot 30 --seed 20261109" not in ci

    # Cheap source/transport coverage survives on PRs; this must not prevent
    # genuinely unaccepted P4/P5 cold runs via the official generic recorder.
    fast = (ROOT / ".github/workflows/warlock-native-optimizer-regressions.yml"
            ).read_text(encoding="utf-8")
    assert "          tests/test_work2_warlock_native_cold.py" in fast
    assert "          tests/test_work2_warlock_native_cold_cli.py" in fast
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()

def test_accepted_priest_l20_cold_once_remains_retired():
    """Retain native Priest P4/P5 tests without the accepted paid cold launcher."""
    assert not (ROOT / ".github/workflows/work1-priest-l20-cold-once.yml").exists()
    ci = (ROOT / ".github/workflows/generic-source-search-regressions.yml"
          ).read_text(encoding="utf-8")
    for source in (
        "tools/wf_native_priest_l20_cold.py",
        "tools/wf_native_priest_l20_paid.py",
        "src/v2/source_bounded_joint_frontier.py",
    ):
        assert "      - '" + source + "'\n" in ci, (
            f"native source change must trigger cheap CI: {source}")
    for test in (
        "tests/test_wf_native_priest_l20_cold.py",
        "tests/test_wf_native_priest_l20_paid.py",
        "tests/test_work1_p4_p5_single_cold_snapshot.py",
    ):
        assert "      - '" + test + "'\n" in ci, (
            f"test change must trigger cheap CI: {test}")
        assert "          " + test + "\n" in ci, (
            f"Priest native transport regression not executed in shared CI: {test}")
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()


def test_accepted_paladin_holy_l60_p3_no_record_is_retired():
    """Keep native HPS/TPS/DPS forwarding tested without replaying an accepted gate.

    Holy L60 P3 was officially recorded PASS on 2026-11-05. A label-triggered
    300-second Rust rebuild and optional paid recheck cannot revise that PASS.
    Generic native P3 regressions and the unaccepted-gate recorder stay live.
    """
    assert not (ROOT / ".github/workflows/work2-paladin-holy-p3.yml").exists()
    ci = (ROOT / ".github/workflows/generic-source-search-regressions.yml"
          ).read_text(encoding="utf-8")
    for test in (
        "tests/test_work2_paladin_holy_native_p3.py",
        "tests/test_work2_paladin_protection_native_p3.py",
        "tests/test_work2_paladin_retribution_native_p3.py",
    ):
        assert f"      - '{test}'\n" in ci, (
            f"source change or test edit must trigger native Paladin P3 coverage: {test}"
        )
        assert f"          {test}\n" in ci, (
            f"shared CI must actually run Paladin native P3 regression: {test}"
        )
    for source in (
        "tools/wf_gate_p3_live.py",
        "integrations/mythicsim-rust/native_p3_equipped.py",
        "integrations/mythicsim-rust/tests/test_native_p3_equipped.py",
    ):
        assert f"      - '{source}'\n" in ci
    assert (ROOT / ".github/workflows/m1-on-demand-record.yml").is_file()


def test_obsolete_druid_native_p7_branch_paid_jobs_retired_without_losing_fast_tests():
    """Retire branch-specific Rust rebuild/paid upload jobs, not native gate support.

    The L20 reference has a reusable frozen receipt; L30 P7.4 already has a
    paid no-record attempt. Neither old Work1 branch-push job is the official
    Merge recorder. Unaccepted P7.1/P7.4 remain runnable there when needed.
    """
    workflows = ROOT / ".github/workflows"
    for legacy in (
        "work1-druid-l20-p71-native.yml",
        "work1-druid-l30-p74-native.yml",
    ):
        assert not (workflows / legacy).exists(), (
            f"obsolete branch-only paid Druid P7 producer still scheduled: {legacy}"
        )

    shared = (workflows / "generic-source-search-regressions.yml").read_text(
        encoding="utf-8")
    for suite in (
        "tests/test_work1_p71_native_generated.py",
        "tests/test_work1_p7_1_live_entry.py",
        "tests/gates/test_wf_gate_p7_4_live.py",
    ):
        assert f"      - '{suite}'\n" in shared, (
            f"fast PR trigger missing for {suite}")
        assert f"          {suite}\n" in shared, (
            f"fast native-transport regression lost for {suite}")
    assert (workflows / "m1-on-demand-record.yml").is_file()


def test_shared_warlock_guide_never_replays_already_paid_l20_native_world():
    """Publishing the guide must not compile Rust and re-pay L20 source combat.

    The generic native paid-range entry point handles genuinely unpaid levels;
    this fast shared guide job consumes retained observations and reports
    their coverage without making a new acceptance gate.
    """
    workflow = (ROOT / ".github/workflows/work2-warlock-route-guide.yml"
                ).read_text(encoding="utf-8")
    assert workflow.count("\n  guide:\n") == 1
    assert "\n  paid-native-l20-route:" not in workflow
    assert "cargo build --locked --bin forever-engine" not in workflow
    assert "--execute-native" not in workflow
    assert "      - name: Publish reproducible partial guide" in workflow
    assert "run: python -m pytest -q tests/test_work2_warlock_route_guide.py tests/test_work2_warlock_next_level_source.py" in workflow
    assert (ROOT / ".github/workflows/work2-warlock-l41-l50-native-batch.yml").is_file()


def test_completed_disposable_delete_smoke_is_retired_without_disabling_gc():
    """The live create/list/delete smoke is complete; keep only safe routine GC.

    A re-dispatchable storage probe consumes another workflow run and creates
    another artifact without advancing source-native play or safeguarding M1.
    The scheduled, pinned-evidence-aware guard remains the sole maintenance GC.
    """
    workflows = ROOT / ".github/workflows"
    assert not (workflows / "actions-storage-clean-smoke.yml").exists()
    guard = (workflows / "actions-storage-preventive-gc.yml").read_text(
        encoding="utf-8")
    assert "    - cron: '23 */6 * * *'" in guard
    assert "      - name: Inventory and bounded evidence-safe GC" in guard
    assert "APPLY: ${{ github.event_name == 'schedule' || " in guard
    assert "collect_local_references" in guard
    assert "verify_deleted_artifacts_absent(" in guard


def test_retired_warlock_paid_optimizer_and_manual_only_native_joint_sweep():
    """Do not re-pay old Warlock levels or the 28-profile diagnostic on PRs.

    Native optimizer implementation remains covered by cheap regressions.
    The 28-profile sweep remains executable by explicit manual dispatch with
    its opt-in full-evidence upload; none of this changes M1 acceptance.
    """
    workflows = ROOT / ".github/workflows"
    assert not (workflows / "warlock-native-optimize.yml").exists(), (
        "stale fixed-Rust Warlock 100-mob optimizer can repeat paid levels"
    )
    warlock_ci = (workflows / "warlock-native-optimizer-regressions.yml").read_text(
        encoding="utf-8")
    assert "      - tools/wf_warlock_native_optimizer.py\n" in warlock_ci
    assert "          tests/test_work1_warlock_world_finalists.py\n" in warlock_ci

    sweep = (workflows / "native-joint-28-sweep.yml").read_text(
        encoding="utf-8")
    events = sweep.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "  workflow_dispatch:\n" in events
    assert "  pull_request:\n" not in events
    assert "  push:\n" not in events
    assert "      - name: Run balanced native 5s × 28 profile sweep" in sweep
    assert "      - name: Upload compact native matrix and provenance" in sweep
    assert ("github.event_name == 'workflow_dispatch' && "
            "inputs.retain_full_evidence") in sweep

    fast_ci = (workflows / "work2-native-joint-python-contract.yml").read_text(
        encoding="utf-8")
    for path in (
        "integrations/mythicsim-rust/native_joint_28_sweep.py",
        "integrations/mythicsim-rust/tests/test_native_joint_28_sweep.py",
    ):
        assert "      - " + path + "\n" in fast_ci
    assert ("python integrations/mythicsim-rust/tests/"
            "test_native_joint_28_sweep.py -v") in fast_ci


def test_historical_paid_l44_l46_range_is_not_prefilled_on_manual_dispatch():
    """A manual paid baseline dispatch must choose fresh explicit native provenance.

    L20–L60 100/100 baselines are already measured. The legacy adjacent-range
    launcher may serve a genuinely unmeasured request (including L10 root),
    but no UI default may silently replay its historic L44→L46 request.
    This is an anti-repeat-work safeguard, not a new native acceptance gate.
    """
    workflow = (ROOT / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
                ).read_text(encoding="utf-8")
    dispatch = workflow.split("\n  workflow_dispatch:\n", 1)[1].split(
        "\npermissions:\n", 1)[0]
    assert "  pull_request:" not in workflow.split("\non:\n", 1)[1].split(
        "\npermissions:\n", 1)[0]

    def input_body(field):
        # Match the NEXT six-space input key, not the nested eight-space
        # description/required/default keys inside the current input.
        remainder = dispatch.split(f"      {field}:\n", 1)[1]
        return re.split(r"(?m)^      [a-z_]+:[ \t]*$", remainder, maxsplit=1)[0]

    for field in (
        "predecessor_artifact_id", "from_level", "end_level",
        "selected_rust_sha", "predecessor_binary_sha256",
    ):
        body = input_body(field)
        assert "\n        default:" not in body, field
    # Explicit input is still available for authentic new continuation; this
    # does not delete paid receipts or restrict the generic route optimizer.
    for field in ("from_level", "end_level", "selected_rust_sha"):
        body = input_body(field)
        assert "\n        required: true\n" in body, field
    assert "      - name: Preserve selected source, native 100-mob receipts" in workflow


def test_paid_range_dispatch_preflight_executes_before_native_checkout():
    """Invalid manual provenance must cost zero Rust build time.

    Extract and *execute* the same bash run block shipped in the workflow;
    this is input validation for a retired baseline launcher, not an M1 gate.
    """
    workflow = (ROOT / ".github/workflows/work2-warlock-l41-l50-native-batch.yml"
                ).read_text(encoding="utf-8")
    marker = "      - name: Validate manual paid-range request before native checkout and build\n"
    checkout = "      - name: Checkout exact Forever source\n"
    assert workflow.count(marker) == 1
    assert workflow.index(marker) < workflow.index(checkout)
    step = workflow.split(marker, 1)[1].split(checkout, 1)[0]
    assert "        run: |\n" in step
    source = step.split("        run: |\n", 1)[1]
    script = "\n".join(row[10:] if row.startswith(" " * 10) else row
                       for row in source.splitlines())

    base = {
        "FROM_LEVEL": "10", "END_LEVEL": "12",
        "MAX_NEW_LEVELS": "2", "MAX_PROPOSALS": "30",
        "SELECTED_RUST_SHA": "a" * 40,
        "PREDECESSOR_ARTIFACT_ID": "",
        "PREDECESSOR_BINARY_SHA256": "",
        "RESUME_ROOT_ARTIFACT_ID": "",
    }

    def check(overrides, *, accepted, expected=None):
        completed = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, **base, **overrides},
            text=True, capture_output=True, check=False,
        )
        assert (completed.returncode == 0) is accepted, (
            overrides, completed.stdout, completed.stderr)
        if expected is not None:
            assert expected in completed.stdout + completed.stderr

    check({}, accepted=True)
    check({"RESUME_ROOT_ARTIFACT_ID": "123"}, accepted=True)
    continuation = {
        "FROM_LEVEL": "45", "END_LEVEL": "47",
        "PREDECESSOR_ARTIFACT_ID": "54321",
        "PREDECESSOR_BINARY_SHA256": "b" * 64,
    }
    check(continuation, accepted=True)
    for bad, error in (
        ({"END_LEVEL": "10"}, "from_level < end_level"),
        ({"END_LEVEL": "61"}, "end_level <= 60"),
        ({"MAX_PROPOSALS": "0"}, "positive decimal integers"),
        ({"SELECTED_RUST_SHA": "not-a-commit"}, "40-hex commit"),
        ({"PREDECESSOR_ARTIFACT_ID": "54321"}, "must not reuse a paid predecessor"),
        ({"RESUME_ROOT_ARTIFACT_ID": "-1"}, "positive artifact ID"),
        ({**continuation, "PREDECESSOR_ARTIFACT_ID": ""}, "predecessor artifact ID"),
        ({**continuation, "PREDECESSOR_BINARY_SHA256": ""}, "paid binary SHA256"),
        ({**continuation, "RESUME_ROOT_ARTIFACT_ID": "123"}, "only valid for an L10 root"),
    ):
        check(bad, accepted=False, expected=error)


def test_manual_native_joint_sweep_preserves_inflight_paid_receipts():
    """A second manual dispatch must not cancel a native sweep mid-evaluation.

    The queued request may still be replaced before starting; no already-paid
    source/world work should be discarded solely by workflow concurrency.
    """
    workflow = (ROOT / ".github/workflows/native-joint-28-sweep.yml").read_text(
        encoding="utf-8")
    head = workflow.split("\njobs:", 1)[0]
    assert "  workflow_dispatch:\n" in head
    for automatic in ("  pull_request:", "  push:", "  schedule:"):
        assert automatic not in head
    assert "  group: native-joint-28-stage5-${{ github.ref }}" in head
    assert "  cancel-in-progress: false" in head
    assert "  cancel-in-progress: true" not in head
    assert "Run balanced native 5s × 28 profile sweep" in workflow
    assert "if: always()" in workflow
    assert "retention-days: 3" in workflow
    assert "retention-days: 7" in workflow

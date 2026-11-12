"""The M0.6 original Rust-paid comparison must never be an automatic PR job.

The initial two-sample native measurement is preserved in Actions #43072652469.
New original-paid decisions are opt-in; ordinary PR changes still run fast tests.
"""
from pathlib import Path
import re


WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/native-paid-route-regressions.yml")


def _job(name: str, text: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z][a-zA-Z0-9_-]*:|\Z)",
        text,
    )
    assert match, f"missing workflow job: {name}"
    return match.group(1)


def test_original_native_payment_needs_explicit_boolean_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")
    dispatch = text.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    input_block = dispatch.split("      run_m06_original:\n", 1)[1]
    assert "        type: boolean\n" in input_block
    assert "        default: false\n" in input_block
    paid_job = _job("work2-m06-original-native", text)
    assert (
        "    if: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.run_m06_original == true }}\n"
    ) in paid_job
    assert "cargo build --locked" in paid_job
    assert "python -m src.v2.runner optimize" in paid_job



def test_m06_original_dispatch_cannot_also_launch_predecessor_100_mobs():
    text = WORKFLOW.read_text(encoding="utf-8")
    m06_job = _job("work2-m06-original-native", text)
    predecessor_job = _job("cross-tree-native-world", text)
    assert "inputs.run_m06_original == true" in m06_job
    assert (
        "    if: ${{ github.event_name == 'workflow_dispatch' "
        "&& inputs.predecessor_artifact_id != '' "
        "&& inputs.run_m06_original != true }}"
    ) in predecessor_job


def test_native_paid_pr_regressions_remain_fast_and_not_paid():
    text = WORKFLOW.read_text(encoding="utf-8")
    fast_job = _job("native-paid-route", text)
    assert "    if: github.event_name == 'pull_request'\n" in fast_job
    assert "python -m pytest -q" in fast_job
    assert "cargo build" not in fast_job
    # Only parser/help is permitted on PRs; native-paid optimize remains
    # guarded by the explicit manual run_m06_original dispatch input.
    direct_optimize_commands = re.findall(
        r"^\s+run:\s*(python -m src\.v2\.runner optimize[^\n]*)$",
        fast_job, flags=re.MULTILINE,
    )
    assert direct_optimize_commands == ["python -m src.v2.runner optimize --help"]

def test_only_superseded_fast_pr_runs_are_cancelled():
    text = WORKFLOW.read_text(encoding="utf-8")
    header = text.split("\njobs:\n", 1)[0]
    fast_job = _job("native-paid-route", text)
    assert "concurrency:" not in header
    assert (
        "    concurrency:\n"
        "      group: native-paid-route-fast-pr-"
        "${{ github.event.pull_request.number }}\n"
        "      cancel-in-progress: true\n"
    ) in fast_job
    # Separate manual original/native 100-mob comparisons must retain their
    # paid receipts even when a faster PR update lands.
    for name in ("work2-m06-original-native", "cross-tree-native-world"):
        manual_job = _job(name, text)
        assert "cancel-in-progress:" not in manual_job
        assert "    if: ${{ github.event_name == 'workflow_dispatch'" in manual_job

def test_fast_native_route_ci_covers_public_m06_optimizer_dispatch():
    text = WORKFLOW.read_text(encoding="utf-8")
    pr_paths = text.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
    assert "      - src/v2/native_range_optimizer.py\n" in pr_paths
    assert "      - src/v2/runner.py\n" in pr_paths
    assert "      - tests/maintenance/test_m06_paid_dispatch_boundary.py\n" in pr_paths
    fast_job = _job("native-paid-route", text)
    # A PR changing the real `python -m` entry point must not silently skip
    # CI or substitute library-only mocks for the public command dispatch.
    assert "python -m src.v2.runner optimize --help" in fast_job
    assert "cargo build" not in fast_job
    assert "run_m06_original" not in fast_job


def test_m06_new_original_dispatch_needs_digest_verified_predecessor_before_payment():
    text = WORKFLOW.read_text(encoding="utf-8")
    dispatch = text.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "      reuse_m06_artifact_id:\n" in dispatch
    paid_job = _job("work2-m06-original-native", text)
    assert "M06_ORIGINAL_CACHE_ARTIFACT_REQUIRED" in paid_job
    assert '[[ ! "$REUSE_M06_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]' in paid_job
    assert "python -m tools.wf_m06_original_cache_stage" in paid_job
    assert "--cache-dir runs/native-api-paid-cache" in paid_job
    assert "runs/m06-original-cache-manifest.json" in paid_job
    assert paid_job.index("M06_ORIGINAL_CACHE_ARTIFACT_REQUIRED") < (
        paid_job.index("cargo build --locked"))
    assert paid_job.index("python -m tools.wf_m06_original_cache_stage") < (
        paid_job.index("python -m src.v2.runner optimize"))
    assert "actions: read" in text
    fast_job = _job("native-paid-route", text)
    assert "tests/test_work2_m06_original_cache_stage.py" in fast_job
    assert "python -m tools.wf_m06_original_cache_stage" not in fast_job

RELAY = (Path(__file__).resolve().parents[2]
         / ".github/workflows/m06-original-dispatch-relay.yml")


def test_owner_comment_relay_passes_authenticated_original_cache_to_native_job():
    relay = RELAY.read_text(encoding="utf-8")
    assert "github.event.issue.number == 1104" in relay
    assert "github.event.comment.user.login == 'dosibjrn'" in relay
    assert "startsWith(github.event.comment.body, '/run-m06-original ')" in relay
    assert "github.event.comment.body == '/run-m06-original'" not in relay
    assert "^/run-m06-original[ ]([1-9][0-9]*)$" in relay
    assert "M06_OWNER_COMMAND_REQUIRES_ORIGINAL_ARTIFACT_ID" in relay
    assert "actions/artifacts/$artifact_id" in relay
    assert "^work2-m06-adaptive-original-[0-9a-f]{40}$" in relay
    assert '"$artifact_expired" != false' in relay
    assert 'echo "reuse_m06_artifact_id=$artifact_id" >> "$GITHUB_OUTPUT"' in relay
    assert '-f reuse_m06_artifact_id="${{ steps.guard.outputs.reuse_m06_artifact_id }}"' in relay
    assert "-f run_m06_original=true" in relay
    assert "-f predecessor_artifact_id=''" in relay
    assert relay.count("gh workflow run native-paid-route-regressions.yml") == 1
    paid = WORKFLOW.read_text(encoding="utf-8")
    assert "      reuse_m06_artifact_id:\n" in paid
    assert 'REUSE_M06_ARTIFACT_ID: ${{ inputs.reuse_m06_artifact_id }}' in paid


def test_owner_comment_requires_exact_one_positive_decimal_artifact_id():
    pattern = r"^/run-m06-original[ ]([1-9][0-9]*)$"
    assert re.fullmatch(pattern, "/run-m06-original 13941049347").group(1) == "13941049347"
    for invalid in ("/run-m06-original", "/run-m06-original ",
                    "/run-m06-original 0", "/run-m06-original 01",
                    "/run-m06-original 42 more", "/run-m06-original 42;echo",
                    "/run-m06-original\t42", "/run-m06-original -f foo"):
        assert re.fullmatch(pattern, invalid) is None


def test_native_paid_fast_pr_triggers_for_every_executed_regression_file():
    """A modified native paid/axis test must actually launch its fast PR CI."""
    text = WORKFLOW.read_text(encoding="utf-8")
    pr_paths = text.split("  pull_request:\n", 1)[1].split(
        "  workflow_dispatch:\n", 1)[0]
    fast_job = _job("native-paid-route", text)
    executed = set(re.findall(r"\btests/(?:maintenance/)?[a-zA-Z0-9_]+\.py\b", fast_job))
    assert executed, "the fast native route job lost its focused regressions"
    missing = sorted(path for path in executed if f"      - {path}\n" not in pr_paths)
    assert not missing, f"fast native route tests missing PR path triggers: {missing}"

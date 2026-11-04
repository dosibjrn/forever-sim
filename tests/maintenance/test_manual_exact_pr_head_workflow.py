"""Static fail-closed contract for the manual exact-PR-HEAD verifier.

These tests do NOT substitute for a real hosted-runner positive/negative smoke.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/manual-exact-pr-head.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


class ManualExactHeadContract(unittest.TestCase):
    def test_manual_only_main_and_read_only(self):
        self.assertIn("workflow_dispatch:", TEXT)
        self.assertNotIn("\n  push:", TEXT)
        self.assertNotIn("\n  pull_request:", TEXT)
        self.assertNotIn("\n  schedule:", TEXT)
        self.assertIn("github.ref == 'refs/heads/main'", TEXT)
        self.assertIn("permissions:\n  contents: read", TEXT)
        self.assertNotIn("contents: write", TEXT)
        self.assertIn("timeout-minutes: 15", TEXT)
        self.assertIn("cancel-in-progress: false", TEXT)

    def test_validates_pr_identity_and_exact_sha_before_checkout(self):
        before_checkout = TEXT.split("- name: Checkout verified commit", 1)[0]
        self.assertIn("^[1-9][0-9]{0,5}$", before_checkout)
        self.assertIn("^[0-9a-f]{40}$", before_checkout)
        for token in ('.state // ""', '.head.repo.full_name // ""',
                      '.base.repo.full_name // ""', '.base.ref // ""',
                      '.head.sha // ""', '"$actual_sha" != "$EXPECTED_SHA"',
                      '"$head_repo" != "$GITHUB_REPOSITORY"',
                      '"$base_repo" != "$GITHUB_REPOSITORY"',
                      'main|work/*)', '"$state" != open'):
            self.assertIn(token, before_checkout)

    def test_stacked_pr_base_is_allowlisted_before_checkout(self):
        before_checkout = TEXT.split("- name: Checkout verified commit", 1)[0]
        self.assertIn('case "$base_ref" in', before_checkout)
        self.assertIn('main|work/*)', before_checkout)
        self.assertIn('PR base is not main or an approved work/* branch', before_checkout)
        self.assertIn('"$base_repo" != "$GITHUB_REPOSITORY"', before_checkout)
        self.assertNotIn('"$base_ref" != main', before_checkout)

    def test_checkout_exact_api_verified_commit_without_credentials(self):
        self.assertIn("ref: ${{ steps.verify-pr.outputs.sha }}", TEXT)
        self.assertIn("persist-credentials: false", TEXT)
        self.assertIn("lfs: true", TEXT)
        self.assertIn('[[ "$actual" == "$EXPECTED_SHA" ]]', TEXT)
        self.assertIn('[[ "$current" == "$EXPECTED_SHA" ]]', TEXT)

    def test_untrusted_suite_has_no_api_token_and_no_arbitrary_shell(self):
        self.assertIn("Execute allowlisted tests without API token", TEXT)
        suite = TEXT.split("- name: Execute allowlisted tests without API token", 1)[1]
        self.assertNotIn("GH_TOKEN:", suite)
        self.assertNotIn("github.token", suite)
        self.assertNotIn("eval ", suite)
        self.assertNotIn("bash -c", suite)
        self.assertNotIn("curl ", suite)
        self.assertNotIn("gh api", suite)
        # Keep the live, source-backed suites mandatory. The one-off private
        # migration guard may be retired after public source migration without
        # weakening exact-HEAD validation or allowing arbitrary commands.
        for suite_name in ("native-ack-unit", "paid-replay-unit",
                           "source-periodic-unit", "source-profile-unit"):
            self.assertIn(suite_name, suite)
        self.assertNotIn("p1p2-unit", TEXT)
        self.assertIn("Suite not allowlisted", TEXT)

    def test_relocated_service_queue_tests_have_a_bounded_manual_suite(self):
        # Same PR identity, SHA and read-only token constraints as other suites.
        self.assertIn("          - service-queue-unit", TEXT)
        self.assertIn("source-periodic-unit|service-queue-unit) ;;", TEXT)
        self.assertIn("source-periodic-unit|service-queue-unit)", TEXT)
        self.assertIn("tests/integration/service/test_g50[c-i]_*.py", TEXT)
        self.assertIn("tests/maintenance/test_manual_exact_pr_head_workflow.py", TEXT)
        self.assertIn("-k 'not browser'", TEXT)
        suite = TEXT.split("- name: Execute allowlisted tests without API token", 1)[1]
        self.assertIn("*) echo 'Suite not allowlisted' >&2; exit 6", suite)


if __name__ == "__main__":
    unittest.main()

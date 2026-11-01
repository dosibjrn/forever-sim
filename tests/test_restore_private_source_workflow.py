"""Fail-closed contract for the manual public migration publication boundary.

The actual source/index negative controls live in test_verify_public_snapshot.py.
This test guards the workflow wiring to that tested implementation.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/restore-private-source.yml"


class ManualMigrationWorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.shell = cls.text.split("        run: |", 1)[1].split(
            "      - name: Upload only public-safe audit SUMMARY", 1
        )[0]

    def test_manual_only_with_explicit_source_approval(self):
        header = self.text.split("jobs:", 1)[0]
        self.assertIn("workflow_dispatch:", header)
        self.assertNotIn("\n  push:", header)
        self.assertNotIn("\n  pull_request:", header)
        self.assertIn('APPROVED_SOURCE_SHA', self.shell)
        self.assertIn('"$APPROVED_SOURCE_SHA" != "$source_sha"', self.shell)

    def test_same_protected_policy_for_audit_and_publication(self):
        self.assertIn("from verify_public_snapshot import protected", self.shell)
        self.assertIn('python3 - "$SOURCE" "$REPORT" "$TARGET"', self.shell)
        self.assertIn('--source "$SOURCE" --emit-selected-paths', self.shell)

    def test_only_selected_paths_are_copied_and_staged(self):
        self.assertIn('tar -C "$SOURCE" --null -T "$REPORT/selected-paths.z"', self.shell)
        self.assertIn('GIT_LITERAL_PATHSPECS=1 git -C "$TARGET" add -A --force', self.shell)
        self.assertIn('--pathspec-from-file="$REPORT/selected-paths.z" --pathspec-file-nul', self.shell)
        self.assertNotIn("rsync -a", self.shell)
        self.assertNotIn('git -C "$TARGET" add -A --force\n', self.shell)

    def test_stage_parity_is_verified_before_publish(self):
        selection = self.shell.index('--emit-selected-paths')
        stage = self.shell.index('--pathspec-from-file=')
        verification = self.shell.index('--source "$SOURCE" --target "$TARGET"')
        commit = self.shell.index('commit -m "migration:')
        self.assertLess(selection, stage)
        self.assertLess(stage, verification)
        self.assertLess(verification, commit)
        self.assertIn('if git -C "$TARGET" diff --cached --name-only --diff-filter=D', self.shell)


if __name__ == "__main__":
    unittest.main()

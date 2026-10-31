"""Regression contracts for issue #14 phase 2B alternate runner relocation."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ROOT / "scripts" / "commands"
NAMES = ("run-fast", "run-both", "run-forever", "run-v2", "run-mc")


class AlternateRunnerRelocation(unittest.TestCase):
    def test_alternates_relocated_primary_unchanged(self):
        for stem in NAMES:
            for ext in ("sh", "ps1"):
                name = f"{stem}.{ext}"
                with self.subTest(name=name):
                    self.assertFalse((ROOT / name).exists(), name)
                    self.assertTrue((COMMANDS / name).is_file(), name)
        for name in ("run.sh", "run.ps1"):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_shell_syntax_and_repo_root_resolution(self):
        for stem in NAMES:
            path = COMMANDS / f"{stem}.sh"
            with self.subTest(name=path.name):
                subprocess.run(["bash", "-n", str(path)], check=True)
                self.assertIn('cd "$(dirname "$0")/../.."', path.read_text())

    def test_all_bash_alternates_from_unrelated_cwd_with_stubbed_python(self):
        invocations = {
            "run-fast": (["--optimize-only"], "src.v2.runner", 1),
            "run-v2": (["--optimize-only"], "src.v2.runner", 1),
            "run-forever": (["--no-listener"], "src.v2.runner", 3),
            "run-both": (["--school", "frost"], "src.master_optimizer", 3),
            "run-mc": (["--optimize-only"], "src.master_optimizer", 1),
        }
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            script = temp / "python"
            script.write_text(
                '#!/bin/sh\n'
                'printf "%s|%s\\n" "$PWD" "$*" >> "$CAPTURE_LOG"\n'
            )
            script.chmod(0o755)
            log = temp / "calls.log"
            env = dict(os.environ,
                       PATH=str(temp) + os.pathsep + os.environ.get("PATH", ""),
                       CAPTURE_LOG=str(log), MSYSTEM="")
            for stem, (args, expected, min_calls) in invocations.items():
                with self.subTest(stem=stem):
                    log.unlink(missing_ok=True)
                    subprocess.run(["bash", str(COMMANDS / f"{stem}.sh"), *args],
                                   cwd=temp, env=env, check=True, timeout=20)
                    entries = log.read_text().splitlines()
                    self.assertGreaterEqual(len(entries), min_calls)
                    self.assertTrue(all(e.startswith(str(ROOT) + "|") for e in entries))
                    self.assertTrue(any(expected in e for e in entries), entries)

    def test_powershell_scripts_use_repo_root_and_correct_siblings(self):
        for stem in NAMES:
            s = (COMMANDS / f"{stem}.ps1").read_text()
            with self.subTest(stem=stem):
                self.assertIn("Join-Path $PSScriptRoot '../..'", s)
                self.assertIn("Set-Location $repoRoot", s)
        self.assertIn("Join-Path $repoRoot 'run.ps1'",
                      (COMMANDS / "run-both.ps1").read_text())
        self.assertIn("Join-Path $repoRoot 'run.ps1'",
                      (COMMANDS / "run-mc.ps1").read_text())
        self.assertIn('cygpath -w "$PWD/scripts/commands/run-both.ps1"',
                      (COMMANDS / "run-both.sh").read_text())


if __name__ == "__main__":
    unittest.main()

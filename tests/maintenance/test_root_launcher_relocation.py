"""Regression contracts for issue #14 root launcher relocation (phase 2A)."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = ROOT / "scripts" / "commands"
BASH_SCRIPTS = (
    "run-validation-fast.sh", "run-validation-v1.sh", "run-validation-v2.sh",
    "run-validation-v3.sh", "run-validation-v4.sh", "run-validation-v5.sh",
    "run-release-smoke.sh", "run-listener-smoke.sh", "service-start.sh",
    "service-stop.sh", "talentsforever-capture.sh",
    "wowhead-abilities-capture.sh", "wowhead-capture-adaptive.sh",
    "wowhead-capture.sh",
)
POWERSHELL_SCRIPTS = (
    "run-validation-fast.ps1", "run-validation-v1.ps1",
    "run-validation-v2.ps1", "run-validation-v3.ps1",
    "run-release-smoke.ps1",
)
TARGETS = {
    "run-validation-fast.sh": "tools/validate_fast.py",
    "run-validation-v1.sh": "tools/validate_v1_browser.py",
    "run-validation-v2.sh": "tools/validate_v2_restart.py",
    "run-validation-v3.sh": "tools/validate_v3_checkpoint_failure.py",
    "run-validation-v4.sh": "tools/validate_v4_concurrency.py",
    "run-validation-v5.sh": "tools/validate_v5_acceptance.py",
    "run-release-smoke.sh": "-m pytest",
    "run-listener-smoke.sh": "-m pytest",
    "service-start.sh": "-m src.service.local_stack",
    "service-stop.sh": "-m src.service.local_stack --stop",
    "talentsforever-capture.sh": "tools/capture_talentsforever_references.py",
    "wowhead-abilities-capture.sh": "tools/capture_forever_abilities_sqlite.py",
    "wowhead-capture-adaptive.sh": "tools/capture_wowhead_adaptive.py",
    "wowhead-capture.sh": "tools/capture_wowhead.py",
}

class RootLauncherRelocation(unittest.TestCase):
    def test_no_auxiliary_launchers_left_in_root(self):
        for name in BASH_SCRIPTS + POWERSHELL_SCRIPTS:
            with self.subTest(name=name):
                self.assertFalse((ROOT / name).exists(), name)
                self.assertTrue((COMMANDS / name).is_file(), name)
        self.assertTrue((ROOT / "run.sh").is_file())
        self.assertTrue((ROOT / "run.ps1").is_file())

    def test_bash_syntax_and_target_files(self):
        for name in BASH_SCRIPTS:
            with self.subTest(name=name):
                script = COMMANDS / name
                subprocess.run(["bash", "-n", str(script)], check=True)
                if TARGETS[name].startswith("tools/"):
                    self.assertTrue((ROOT / TARGETS[name]).is_file(), name)

    def test_relocated_bash_launches_from_root_without_real_python(self):
        with tempfile.TemporaryDirectory() as d:
            temp = Path(d)
            python_stub = temp / "python"
            python_stub.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$PWD" > "$CAPTURE_CWD"\n'
                'printf "%s\\n" "$*" > "$CAPTURE_ARGS"\n'
            )
            python_stub.chmod(0o755)
            cwdlog, argslog = temp / "cwd.txt", temp / "args.txt"
            env = dict(os.environ, PATH=str(temp) + os.pathsep + os.environ.get("PATH", ""),
                       CAPTURE_CWD=str(cwdlog), CAPTURE_ARGS=str(argslog))
            for name in BASH_SCRIPTS:
                with self.subTest(name=name):
                    cwdlog.unlink(missing_ok=True)
                    argslog.unlink(missing_ok=True)
                    subprocess.run(["bash", str(COMMANDS / name)], cwd=temp,
                                   env=env, check=True, timeout=15)
                    self.assertEqual(str(ROOT), cwdlog.read_text().strip())
                    self.assertIn(TARGETS[name], argslog.read_text().strip())

    def test_powershell_path_resolution_and_python_target(self):
        for name in POWERSHELL_SCRIPTS:
            with self.subTest(name=name):
                text = (COMMANDS / name).read_text()
                self.assertIn("Join-Path $PSScriptRoot '../..'", text)
                self.assertIn("python ", text)

    def test_root_entrypoint_bash_kept_usable(self):
        subprocess.run(["bash", "-n", str(ROOT / "run.sh")], check=True)

if __name__ == "__main__":
    unittest.main()

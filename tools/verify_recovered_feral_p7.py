#!/usr/bin/env python3
"""Re-run recovered historical Feral Cat source tests from a verified WF607 archive.

The original executable is archived, NOT checked into Git. This script creates a
temporary directory, verifies the ZIP digest, extracts safely, and runs the
P7.2 / P7.3 / P7.4 source unit tests including real Go/2D paid simulations.

Usage:
 python tools/verify_recovered_feral_p7.py /path/WoW_Forever_Cat_L60_P7_WF607_LOCAL_2026-10-28.zip
"""
import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import sys
import tempfile
import zipfile

EXPECTED = "434e1e14f6145131f396b4dda21d0baa0b010f829daea5ed86da50c90c718674"

def main(archive: Path):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != EXPECTED:
        raise ValueError("Incorrect original WF607 archive sha256: " + digest)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                posix = PurePosixPath(member.filename)
                windows = PureWindowsPath(member.filename)
                if (member.is_dir() or posix.is_absolute() or windows.is_absolute()
                    or windows.drive or "\\" in member.filename
                    or ".." in posix.parts):
                    continue
                # Remove the original package root folder.
                if len(posix.parts) < 2:
                    continue
                target = root.joinpath(*posix.parts[1:])
                if not target.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Unsafe archive member: " + member.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(member))
        native = root / "wowsimcli-wf598"
        if not native.exists():
            raise FileNotFoundError(native)
        native.chmod(native.stat().st_mode | 0o111)
        tests = ["test_wf603_p72", "test_wf606_p73", "test_wf607_p74"]
        print("WF607 archive SHA256 verified; testing", ", ".join(tests), flush=True)
        result = subprocess.run([sys.executable, "-m", "unittest", *tests, "-v"], cwd=root, check=False)
        return result.returncode

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Pass exactly one WF607 source archive path")
    sys.exit(main(Path(sys.argv[1])))

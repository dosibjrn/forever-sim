#!/usr/bin/env python3
"""Import archived WF607–WF613 source and run evidence into a local checkout.

Usage:
 python tools/import_feral_p7_archives.py /path/WoW_Forever_Cat_L60_P7_WF607_LOCAL_2026-10-28.zip /path/WF613_COMPATIBILITY_REPAIR_P75_FAIL_2026-10-28.zip

This does not rerun a simulation; archive provenance is verified and files are
extracted under evidence for subsequent reproducibility/review. Never upload
unreviewed binaries or private files from those archives.
"""
from pathlib import Path
import hashlib, sys, zipfile
from pathlib import PurePosixPath, PureWindowsPath

EXPECTED = {
 "WoW_Forever_Cat_L60_P7_WF607_LOCAL_2026-10-28.zip": "434e1e14f6145131f396b4dda21d0baa0b010f829daea5ed86da50c90c718674",
 "WF613_COMPATIBILITY_REPAIR_P75_FAIL_2026-10-28(2).zip": "a95e89f1bbd36d3cccb3c605fb9c8c90490bdd857112fc2c6bb83ceac1785e5f",
}
DEST = Path("docs/evidence/druid-p7/recovered/archives")
ALLOW_SUFFIXES = {".py", ".json", ".md", ".log", ".txt", ".sh", ".cmd"}
EXCLUDE = ("__pycache__", ".git/", "native_batch_", "reference_full_report")

def restore(path):
    expected = EXPECTED.get(path.name)
    if not expected:
        raise ValueError(f"unknown archive: {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"archive sha256 mismatch: {path.name}: {digest}")
    root = DEST / path.stem.replace("(2)", "")
    count = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            win = PureWindowsPath(info.filename)
            # Reject absolute POSIX, Windows drive/UNC, backslash and traversal members.
            if (info.is_dir() or name.is_absolute() or win.is_absolute()
                or win.drive or "\\" in info.filename
                or any(part in ("..", ".", "") for part in name.parts)):
                continue
            if name.suffix.lower() not in ALLOW_SUFFIXES or any(x in str(name) for x in EXCLUDE):
                continue
            out = root.joinpath(*name.parts)
            if not out.resolve().is_relative_to(root.resolve()):
                raise ValueError(f'unsafe archive member: {info.filename}')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(info))
            count += 1
    print(f"{path.name}: sha256 OK; extracted {count} source/evidence files under {root}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        restore(Path(arg))

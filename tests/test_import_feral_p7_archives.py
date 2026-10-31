"""ZIP member normalization is a safety boundary, even for SHA-pinned archives."""
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import import_feral_p7_archives as importer


class FeralArchiveImportTests(unittest.TestCase):
    def test_reject_single_backslash_and_windows_absolute_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("safe/file.py", "print('safe')\n")
                z.writestr("safe\\evil.py", "print('backslash')\n")
                z.writestr("C:\\Windows\\evil.py", "print('windows')\n")
                z.writestr("../evil.py", "print('traversal')\n")
            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            dest = Path(tmp) / "out"
            with mock.patch.object(importer, "EXPECTED", {archive.name: expected}), \
                 mock.patch.object(importer, "DEST", dest):
                importer.restore(archive)
            root = dest / "fixture"
            self.assertTrue((root / "safe" / "file.py").is_file())
            self.assertFalse((root / "safe\\evil.py").exists())
            self.assertFalse((root / "evil.py").exists())
            self.assertEqual([p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()],
                             ["safe/file.py"])


if __name__ == "__main__":
    unittest.main()

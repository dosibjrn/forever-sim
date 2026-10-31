import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_public_snapshot.py'
spec = importlib.util.spec_from_file_location('verify_public_snapshot', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


class VerifyPublicSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = Path(self.temp.name) / 'old'
        self.new = Path(self.temp.name) / 'new'
        for root in (self.old, self.new):
            root.mkdir()
            git(root, 'init', '-q')
            git(root, 'config', 'user.email', 'test@example.invalid')
            git(root, 'config', 'user.name', 'test')

    def put(self, path, data, target=None):
        root = target or self.old
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def stage(self, root):
        git(root, 'add', '-A', '--force')

    def test_byte_identical_binary_and_protected_exclusion(self):
        self.put('data/asset.sqlite', b'SQLite format 3\x00\x00\xff')
        self.put('data/asset.sqlite', b'SQLite format 3\x00\x00\xff', self.new)
        self.put('README.md', b'private README')
        self.put('README.md', b'public README', self.new)
        self.stage(self.old)
        self.stage(self.new)
        count, excluded, errors = mod.verify(self.old, self.new)
        self.assertEqual((count, excluded, errors), (1, 1, []))

    def test_missing_or_mismatched_binary_fails(self):
        self.put('data/source.bin', b'\x00\xff\x01')
        self.stage(self.old)
        self.assertIn('MISSING_OR_NONREGULAR data/source.bin', mod.verify(self.old, self.new)[2])
        self.put('data/source.bin', b'\x00\xff\x02', self.new)
        self.stage(self.new)
        self.assertIn('BYTE_MISMATCH data/source.bin', mod.verify(self.old, self.new)[2])

    def test_lfs_pointer_is_not_payload(self):
        pointer = b'version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 8\n'
        self.put('data/model.bin', pointer)
        self.put('data/model.bin', pointer, self.new)
        self.stage(self.old)
        self.stage(self.new)
        self.assertIn('UNHYDRATED_SOURCE_LFS data/model.bin', mod.verify(self.old, self.new)[2])

    def test_ignored_asset_must_be_staged(self):
        self.put('data/ignored.sqlite', b'binary')
        self.put('data/ignored.sqlite', b'binary', self.new)
        self.put('.gitignore', b'*.sqlite\n', self.new)
        self.put('.gitignore', b'*.sqlite\n', self.old)
        self.stage(self.old)
        self.stage(self.new)
        git(self.new, 'rm', '-q', '--cached', 'data/ignored.sqlite')
        self.assertTrue(any('NOT_STAGED_WITH_SOURCE_MODE data/ignored.sqlite' in e for e in mod.verify(self.old, self.new)[2]))

    def test_symlink_mismatch_fails(self):
        (self.old / 'shortcut').symlink_to('real.txt')
        (self.new / 'shortcut').symlink_to('other.txt')
        self.stage(self.old)
        self.stage(self.new)
        self.assertIn('SYMLINK_MISMATCH shortcut', mod.verify(self.old, self.new)[2])

    def test_executable_mode_must_match(self):
        self.put('bin/tool.sh', b'#!/bin/sh\n')
        self.put('bin/tool.sh', b'#!/bin/sh\n', self.new)
        (self.old / 'bin/tool.sh').chmod(0o755)
        self.stage(self.old)
        self.stage(self.new)
        self.assertTrue(any('NOT_STAGED_WITH_SOURCE_MODE bin/tool.sh' in e for e in mod.verify(self.old, self.new)[2]))


if __name__ == '__main__':
    unittest.main()

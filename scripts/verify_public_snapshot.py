#!/usr/bin/env python3
"""Offline, read-only source->public working-tree parity preflight.

Run on *local authenticated* clones before publishing a private snapshot.
This is not a source-disclosure approval, LFS upload proof or gate PASS.
"""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys

# Public migration controls must not be overwritten by historical private files.
PROTECTED_EXACT = {
    'README.md',
    'docs/planning/WORK_PRIORITY.md',
    'scripts/complete_public_migration.sh',
    'scripts/port_remaining_branches.sh',
    'scripts/verify_public_snapshot.py',
    'tests/test_verify_public_snapshot.py',
}
PROTECTED_PREFIX = ('docs/migration/', '.github/workflows/')
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1\n'


def git_index(root):
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
    result = {}
    for entry in raw.split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, _oid, stage = metadata.decode('ascii').split()
        path = os.fsdecode(raw_path)
        if stage != '0':
            raise ValueError(f'unmerged index entry: {path}')
        if path in result:
            raise ValueError(f'duplicate index entry: {path}')
        result[path] = mode
    return result


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def protected(path):
    return path in PROTECTED_EXACT or any(path.startswith(p) for p in PROTECTED_PREFIX)


def selected_source_paths(source):
    """Emit only Git-indexed, non-protected source paths for safe snapshot copying."""
    result = []
    for rel, mode in sorted(git_index(source).items()):
        if protected(rel):
            continue
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts or not rel:
            raise ValueError(f'UNSAFE_PATH {rel!r}')
        if mode not in ('100644', '100755', '120000'):
            raise ValueError(f'UNSUPPORTED_SOURCE_MODE {mode} {rel}')
        result.append(rel)
    return result


def verify(source, target, require_staged=True):
    source_index = git_index(source)
    target_index = git_index(target) if require_staged else {}
    errors = []
    compared = 0
    excluded = 0
    for rel, mode in sorted(source_index.items()):
        if protected(rel):
            excluded += 1
            continue
        p = PurePosixPath(rel)
        if p.is_absolute() or '..' in p.parts or not rel:
            errors.append(f'UNSAFE_PATH {rel!r}')
            continue
        src = source / rel
        dst = target / rel
        if mode == '160000':
            errors.append(f'SUBMODULE_REQUIRES_AUDIT {rel}')
            continue
        if mode == '120000':
            if not src.is_symlink() or not dst.is_symlink() or os.readlink(src) != os.readlink(dst):
                errors.append(f'SYMLINK_MISMATCH {rel}')
                continue
        elif mode in ('100644', '100755'):
            if not src.exists() or not dst.exists() or not stat.S_ISREG(src.lstat().st_mode) or not stat.S_ISREG(dst.lstat().st_mode):
                errors.append(f'MISSING_OR_NONREGULAR {rel}')
                continue
            with src.open('rb') as f:
                if f.read(len(LFS_POINTER)) == LFS_POINTER:
                    errors.append(f'UNHYDRATED_SOURCE_LFS {rel}')
                    continue
            with dst.open('rb') as f:
                if f.read(len(LFS_POINTER)) == LFS_POINTER:
                    errors.append(f'UNHYDRATED_TARGET_LFS {rel}')
                    continue
            if sha256_file(src) != sha256_file(dst):
                errors.append(f'BYTE_MISMATCH {rel}')
                continue
        else:
            errors.append(f'UNSUPPORTED_GIT_MODE {mode} {rel}')
            continue
        if require_staged and target_index.get(rel) != mode:
            errors.append(f'NOT_STAGED_WITH_SOURCE_MODE {rel} expected={mode} got={target_index.get(rel)}')
            continue
        compared += 1
    return compared, excluded, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, type=Path, help='hydrated private source checkout')
    ap.add_argument('--target', type=Path, help='staged public destination checkout')
    ap.add_argument('--emit-selected-paths', action='store_true',
                    help='write NUL-delimited tracked, non-protected paths for tar/git add')
    ap.add_argument('--no-stage-check', action='store_true', help='only compare working bytes (before git add)')
    args = ap.parse_args(argv)
    if args.emit_selected_paths:
        try:
            for path in selected_source_paths(args.source):
                sys.stdout.buffer.write(os.fsencode(path) + b'\0')
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f'PREPUBLICATION_SELECTION_ERROR: {exc}', file=sys.stderr)
            return 2
        return 0
    if args.target is None:
        ap.error('--target is required unless --emit-selected-paths is used')
    try:
        compared, excluded, errors = verify(args.source, args.target, not args.no_stage_check)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'PREPUBLICATION_PARITY_ERROR: {exc}', file=sys.stderr)
        return 2
    print(f'Prepublication parity: compared={compared} protected={excluded} failures={len(errors)}')
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print('WORKTREE_AND_INDEX_PARITY_OK (NOT a publication audit, LFS remote proof, or gate PASS)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

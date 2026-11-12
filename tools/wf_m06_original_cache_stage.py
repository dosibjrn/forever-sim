#!/usr/bin/env python3
"""Stage authentic M0.6 original native-paid cache pairs without repaying mobs.

The current evaluator re-checks native prepared-actor identity, world policy,
dual-resource recovery, and source/2D ACK when it actually reuses each pair.
This import only accepts a compatible immutable runtime/binary identity and
raw-byte digest; it never upgrades an older/different paid runtime by fiat.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

from tools.wf_warlock_native_candidate_scoring import _exact_paid_cache_identity

_ALLOWED_SUFFIXES = (".native.cache.json", ".native.json")
_MAX_ENTRY_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Retained original 2026-11-12 paid run. This is NOT a general "ignore runtime
# hash" escape hatch: every old Git object and live paid-scoring path is checked.
_ORIGINAL_M06_COMMIT = "0fdd07a8ad82972cf89b796391949a26c2cf7b57"
_ORIGINAL_RUNTIME_PATHS = (
    "src/game", "src/scenarios", "src/shared",
    "integrations/mythicsim-rust/live_two_world_pulls.py",
    "tools/wf_warlock_native_candidate_scoring.py",
    "tools/wf_warlock_native_persistent_optimizer.py",
)
_SAFE_PROPOSAL_ONLY_CHANGES = {
    "src/game/native_p3_item_options.py",
    "src/game/native_p3_player_context.py",
    "tools/wf_warlock_native_candidate_scoring.py",
    "tools/wf_warlock_native_persistent_optimizer.py",
}


def _original_m06_runtime_compatible(metadata: dict, expected: dict) -> bool:
    """Verify original schema-2 payment has the same native execution contract.

    Only the standalone prepared-comparison function and the candidate
    scheduler are permitted to change; old and current source/world, native
    paid executor, serial/rolling ACK predicate and scorer must be identical.
    Source/prepared/world policy/binary/raw digest are checked separately by
    the unchanged current evaluator, which re-scores the original receipt.
    """
    if (metadata.get("cache_schema") != 2
            or metadata.get("native_binary_sha256")
            != expected.get("native_binary_sha256")
            or not _HEX64.fullmatch(str(
                metadata.get("forever_paid_runtime_sha256", "")))):
        return False
    root = Path(__file__).resolve().parents[1]

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            check=True, timeout=10).stdout.strip()

    def execution_ast(path: str, source: str) -> str:
        module = ast.parse(source, filename=path)
        if path.endswith("native_candidate_scoring.py"):
            module.body = [
                node for node in module.body
                if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "compare_prepared_candidates")
            ]
        else:
            for node in module.body:
                if (isinstance(node, ast.ClassDef)
                        and node.name == "PersistentNativeEvaluator"):
                    node.body = [
                        member for member in node.body
                        if not (isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and member.name == "__call__")
                    ]
        return ast.dump(module, include_attributes=False)

    try:
        old_objects = git("rev-parse", *(
            f"{_ORIGINAL_M06_COMMIT}:{path}"
            for path in _ORIGINAL_RUNTIME_PATHS)).splitlines()
        if (len(old_objects) != len(_ORIGINAL_RUNTIME_PATHS)
                or any(not re.fullmatch(r"[0-9a-f]{40}", obj)
                       for obj in old_objects)):
            return False
        original_hash = hashlib.sha256(
            "\n".join(old_objects).encode()).hexdigest()
        if metadata["forever_paid_runtime_sha256"] != original_hash:
            return False
        # Historical Git objects must really be available; missing/shallow
        # history, dirty execution paths or any other runtime edit fail closed.
        if git("status", "--porcelain", "--untracked-files=all",
               "--", *_ORIGINAL_RUNTIME_PATHS):
            return False
        changes = set(git(
            "diff", "--name-only", _ORIGINAL_M06_COMMIT, "HEAD",
            "--", *_ORIGINAL_RUNTIME_PATHS).splitlines())
        if not changes.issubset(_SAFE_PROPOSAL_ONLY_CHANGES):
            return False
        for path in (
            "tools/wf_warlock_native_candidate_scoring.py",
            "tools/wf_warlock_native_persistent_optimizer.py",
        ):
            original = git("show", f"{_ORIGINAL_M06_COMMIT}:{path}")
            current = git("show", f"HEAD:{path}")
            if execution_ast(path, original) != execution_ast(path, current):
                return False
        return True
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError):
        return False



def stage_original_paid_cache(
    archive: Path, destination: Path, *, expected_identity: dict
) -> dict:
    """Import only digest-valid schema-2 pairs matching this executable runtime.

    A foreign/expired/corrupt archive cannot cause a native payment fallback.
    Source/prepared SHA and world-policy identities remain intact; the live
    evaluator validates their match against the actual Rust prepare response.
    """
    if (not isinstance(expected_identity, dict)
            or expected_identity.get("cache_schema") != 2
            or not _HEX64.fullmatch(str(
                expected_identity.get("forever_paid_runtime_sha256", "")))
            or not _HEX64.fullmatch(str(
                expected_identity.get("native_binary_sha256", "")))):
        raise ValueError("M06_CURRENT_PAID_RUNTIME_NOT_VERIFIABLE")
    members: dict[str, bytes] = {}
    total_bytes = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = PurePosixPath(info.filename)
            if info.is_dir():
                continue
            if (name.is_absolute() or ".." in name.parts
                    or "\\" in info.filename
                    or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError("M06_UNSAFE_CACHE_ARCHIVE_ENTRY")
            if not name.name.endswith(_ALLOWED_SUFFIXES):
                continue
            # A later artifact can contain our immutable original metadata
            # alongside the currently keyed cache. Do not re-import those
            # historical names as independent paid candidates (or duplicate
            # the same basename across separate archive directories).
            if "original-runtime-provenance" in name.parts:
                continue
            # The archived run contains several output files. Only the
            # immutable native API paid cache is eligible for import.
            if (len(name.parts) > 1
                    and "native-api-paid-cache" not in name.parts):
                continue
            if (info.file_size > _MAX_ENTRY_BYTES
                    or total_bytes + info.file_size > _MAX_ARCHIVE_BYTES):
                raise ValueError("M06_OVERSIZED_CACHE_ARCHIVE")
            if name.name in members:
                raise ValueError("M06_DUPLICATE_CACHE_BASENAME")
            content = zf.read(info)
            if len(content) != info.file_size:
                raise ValueError("M06_INVALID_CACHE_ARCHIVE_LENGTH")
            total_bytes += len(content)
            members[name.name] = content

    accepted: dict[str, bytes] = {}
    original_pairs: dict[str, bytes] = {}
    rejected_identity = 0
    migrated_pairs = 0
    for name, raw_meta in sorted(members.items()):
        if not name.endswith(".native.cache.json"):
            continue
        base = name.removesuffix(".native.cache.json")
        raw_name = base + ".native.json"
        if raw_name not in members:
            raise ValueError("M06_CACHE_PAIR_MISSING_RAW_RECEIPT")
        try:
            metadata = json.loads(raw_meta)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("M06_INVALID_ORIGINAL_CACHE_METADATA") from exc
        if not isinstance(metadata, dict):
            raise ValueError("M06_INVALID_ORIGINAL_CACHE_METADATA")
        if (metadata.get("cache_schema") != 2 or any(
                metadata.get(key) != value
                for key, value in expected_identity.items()
                if key != "forever_paid_runtime_sha256")):
            rejected_identity += 1
            continue
        migrating = (
            metadata.get("forever_paid_runtime_sha256")
            != expected_identity["forever_paid_runtime_sha256"])
        if migrating and not _original_m06_runtime_compatible(
                metadata, expected_identity):
            rejected_identity += 1
            continue
        if (not _HEX64.fullmatch(str(metadata.get("source_sha256", "")))
                or not _HEX64.fullmatch(str(
                    metadata.get("prepared_sha256", "")))):
            raise ValueError("M06_INVALID_ORIGINAL_SOURCE_IDENTITY")
        original_digest = metadata.get("native_raw_receipt_sha256")
        raw_receipt_bytes = members[raw_name]
        if (not _HEX64.fullmatch(str(original_digest))
                or _sha256(raw_receipt_bytes) != original_digest):
            raise ValueError("M06_ORIGINAL_RAW_RECEIPT_DIGEST_MISMATCH")
        try:
            receipt = json.loads(raw_receipt_bytes)
        except (UnicodeError, ValueError) as exc:
            raise ValueError("M06_INVALID_ORIGINAL_RAW_RECEIPT") from exc
        if not isinstance(receipt, dict):
            raise ValueError("M06_INVALID_ORIGINAL_RAW_RECEIPT")
        if migrating:
            # Preserve original bytes and the original sidecar; key a NEW
            # compatible metadata copy to the current exact paid identity.
            # Do not alter source/prepared, world policy, recovery or receipt.
            original_pairs[name] = raw_meta
            original_pairs[raw_name] = raw_receipt_bytes
            migrated = dict(
                metadata, forever_paid_runtime_sha256=
                expected_identity["forever_paid_runtime_sha256"])
            key_fields = dict(migrated)
            key_fields.pop("native_raw_receipt_sha256")
            base = _sha256(json.dumps(
                key_fields, sort_keys=True).encode())
            raw_name = base + ".native.json"
            name = base + ".native.cache.json"
            raw_meta = (json.dumps(
                migrated, sort_keys=True, indent=2) + "\n").encode()
            migrated_pairs += 1
        if name in accepted or raw_name in accepted:
            raise ValueError("M06_DUPLICATE_COMPATIBLE_CACHE_KEY")
        accepted[name] = raw_meta
        accepted[raw_name] = raw_receipt_bytes
    if not accepted:
        raise ValueError(
            "M06_NO_COMPATIBLE_ORIGINAL_PAID_CACHE: "
            "no validated receipt matches this exact Rust binary and paid "
            "runtime; refusing to replay an existing 12-attempt experiment")
    provenance = destination / "original-runtime-provenance"
    # Preflight before any write; old receipts are immutable.
    if (any((destination / name).exists() for name in accepted)
            or (original_pairs and provenance.exists())):
        raise FileExistsError("M06_CACHE_DESTINATION_COLLISION")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in accepted.items():
        with (destination / name).open("xb") as handle:
            handle.write(data)
    if original_pairs:
        provenance.mkdir()
        for name, data in original_pairs.items():
            with (provenance / name).open("xb") as handle:
                handle.write(data)
    return {
        "status": "M06_COMPATIBLE_CACHE_STAGED",
        "imported_pairs": len(accepted) // 2,
        "migrated_original_runtime_pairs": migrated_pairs,
        "excluded_incompatible_pairs": rejected_identity,
        "archive_sha256": _sha256(archive.read_bytes()),
        "native_binary_sha256": expected_identity["native_binary_sha256"],
        "forever_paid_runtime_sha256":
            expected_identity["forever_paid_runtime_sha256"],
    }

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    args = parser.parse_args()
    # Actor/mob/target specifics vary by cache pair and are subsequently
    # matched by _paid; only immutable runtime/binary fingerprint is common.
    identity = _exact_paid_cache_identity(
        args.binary, actor_level=20, mob_count=2, target_hp=484.0)
    if identity is None:
        raise ValueError("M06_CURRENT_PAID_RUNTIME_NOT_VERIFIABLE")
    result = stage_original_paid_cache(
        args.archive, args.cache_dir,
        expected_identity={
            "cache_schema": identity["cache_schema"],
            "forever_paid_runtime_sha256":
                identity["forever_paid_runtime_sha256"],
            "native_binary_sha256": identity["native_binary_sha256"],
        })
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

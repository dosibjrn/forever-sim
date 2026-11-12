#!/usr/bin/env python3
"""Stage authentic M0.6 original native-paid cache pairs without repaying mobs.

The current evaluator re-checks native prepared-actor identity, world policy,
dual-resource recovery, and source/2D ACK when it actually reuses each pair.
This import only accepts a compatible immutable runtime/binary identity and
raw-byte digest; it never upgrades an older/different paid runtime by fiat.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

from tools.wf_warlock_native_candidate_scoring import _exact_paid_cache_identity

_ALLOWED_SUFFIXES = (".native.cache.json", ".native.json")
_MAX_ENTRY_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    rejected_identity = 0
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
        if metadata.get("cache_schema") != 2 or any(
                metadata.get(key) != value
                for key, value in expected_identity.items()):
            rejected_identity += 1
            continue
        if (not _HEX64.fullmatch(str(metadata.get("source_sha256", "")))
                or not _HEX64.fullmatch(str(
                    metadata.get("prepared_sha256", "")))):
            raise ValueError("M06_INVALID_ORIGINAL_SOURCE_IDENTITY")
        original_digest = metadata.get("native_raw_receipt_sha256")
        if (not _HEX64.fullmatch(str(original_digest))
                or _sha256(members[raw_name]) != original_digest):
            raise ValueError("M06_ORIGINAL_RAW_RECEIPT_DIGEST_MISMATCH")
        try:
            receipt = json.loads(members[raw_name])
        except (UnicodeError, ValueError) as exc:
            raise ValueError("M06_INVALID_ORIGINAL_RAW_RECEIPT") from exc
        if not isinstance(receipt, dict):
            raise ValueError("M06_INVALID_ORIGINAL_RAW_RECEIPT")
        accepted[name] = raw_meta
        accepted[raw_name] = members[raw_name]
    if not accepted:
        raise ValueError(
            "M06_NO_COMPATIBLE_ORIGINAL_PAID_CACHE: "
            "no validated receipt matches this exact Rust binary and paid "
            "runtime; refusing to replay an existing 12-attempt experiment")
    destination.mkdir(parents=True, exist_ok=True)
    # Do not overwrite locally paid evidence or silently merge two archives.
    if any((destination / name).exists() for name in accepted):
        raise FileExistsError("M06_CACHE_DESTINATION_COLLISION")
    for name, data in accepted.items():
        with (destination / name).open("xb") as handle:
            handle.write(data)
    return {
        "status": "M06_COMPATIBLE_CACHE_STAGED",
        "imported_pairs": len(accepted) // 2,
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

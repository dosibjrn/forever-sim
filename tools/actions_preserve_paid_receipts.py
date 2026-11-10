"""Verify a retained native-paid Actions ZIP before publishing it unchanged.

Operational evidence preservation only. This does not certify an M1 gate,
re-execute Rust, or imply adjacent levels form a continuous route.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

EXPECTED_LEVELS = frozenset(range(47, 61))
RECEIPT = re.compile(
    r"warlock-paid-range/L(?P<level>\d+)/[^/]+/paid/"
    r"native_l(?P=level)/best_apl/chain_native_world\.json\Z"
)


def validate_archive(path: Path, expected_sha256: str) -> dict[int, str]:
    """Fail closed on an altered/incomplete paid archive; return native source IDs."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError(f"archive SHA256 mismatch: {digest} != {expected_sha256}")

    found: dict[int, str] = {}
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("corrupt ZIP member")
        for filename in archive.namelist():
            match = RECEIPT.fullmatch(filename)
            if match is None:
                continue
            level = int(match.group("level"))
            if level in found:
                raise ValueError(f"duplicate paid receipt for L{level}")
            receipt = json.loads(archive.read(filename))
            if (len(receipt.get("native_windows", [])) != 100
                    or len(receipt.get("world_kills", [])) != 100
                    or receipt.get("world_targets_killed") != 100
                    or receipt.get("continuous_native_actor") is not True
                    or receipt.get("actual_2d_ack") is not True
                    or receipt.get("paid_recovery") is not True):
                raise ValueError(f"L{level}: expected complete original paid 100/100 native ACK")
            source = receipt.get("source_sha256")
            if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{64}", source) is None:
                raise ValueError(f"L{level}: missing original native source identity")
            request = filename.removesuffix("chain_native_world.json") + "source_request.json"
            if request not in archive.namelist():
                raise ValueError(f"L{level}: original paid source request missing")
            found[level] = source
    if frozenset(found) != EXPECTED_LEVELS:
        missing = sorted(EXPECTED_LEVELS.difference(found))
        extra = sorted(set(found).difference(EXPECTED_LEVELS))
        raise ValueError(f"paid 14-level native evidence incomplete: missing={missing} extra={extra}")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    sources = validate_archive(args.archive, args.sha256)
    for level, source in sorted(sources.items()):
        print(f"ORIGINAL_NATIVE_RECEIPT L{level} source_sha256={source} 100/100_ACK")
    print(f"ARCHIVE_VERIFIED levels={len(sources)} original_zip_sha256={args.sha256}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate the selected native Druid layout export API without game-law tests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.engine_client.native_p2_rank_probe import load_native_druid_layout  # noqa: E402


def main() -> int:
    root = Path(os.environ["FOREVER_ENGINE_ROOT"]).resolve()
    binary = Path(os.environ["FOREVER_ENGINE_BINARY"]).resolve()
    layout, metadata = load_native_druid_layout(root, binary=binary)
    if metadata.get("source") != "native_cli":
        raise AssertionError(f"native layout CLI unavailable in selected-source check: {metadata}")
    if not metadata.get("source_revision") or not metadata.get("client_build"):
        raise AssertionError(f"native layout identity missing: {metadata}")

    expected_keys = ("balance", "feral", "restoration")
    if tuple(layout) != expected_keys:
        raise AssertionError(f"native tree order changed: {tuple(layout)}")
    field_count = 0
    proto_counts = {"proto": 0, "new": 0}
    for tree_key, entries in layout.items():
        if not entries:
            raise AssertionError(f"native tree is empty: {tree_key}")
        for position, entry in enumerate(entries):
            if entry.get("position") != position:
                raise AssertionError(f"native position mismatch: {tree_key}:{position}")
            if not isinstance(entry.get("field"), str) or not entry["field"]:
                raise AssertionError(f"native field missing: {tree_key}:{position}")
            if not isinstance(entry.get("name"), str) or not entry["name"]:
                raise AssertionError(f"native name missing: {tree_key}:{position}")
            if type(entry.get("max_ranks")) is not int:
                raise AssertionError(f"native max_ranks type invalid: {tree_key}:{position}")
            if type(entry.get("in_proto")) is not bool:
                raise AssertionError(f"native proto flag type invalid: {tree_key}:{position}")
            proto_counts["proto" if entry["in_proto"] else "new"] += 1
            field_count += 1
    if field_count == 0 or not all(proto_counts.values()):
        raise AssertionError(f"native layout metadata incomplete: {proto_counts}")

    print(json.dumps({
        "status": "PASS",
        "api": "talent-layout --class druid",
        "source": metadata["source"],
        "source_revision": metadata["source_revision"],
        "client_build": metadata["client_build"],
        "tree_keys": expected_keys,
        "field_count": field_count,
        "proto_counts": proto_counts,
        "legality_decisions": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

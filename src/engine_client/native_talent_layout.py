"""Typed selected-MythicSim talent-layout wire client.

This module transports native metadata for candidate serialization only.
It never decides whether a talent rank, build or action is game-legal.
The live P2 adapter may switch to this client only after the matching Rust
API is published and the exact engine SHA is pinned in Forever.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess


class NativeTalentLayoutError(RuntimeError):
    """Selected Rust layout endpoint is unavailable or violates its wire contract."""


def load_druid_talent_layout(
    binary: str | Path, *, timeout_seconds: float = 10.0
) -> dict[str, list[dict[str, object]]]:
    """Query native talent-layout metadata; preserve the native tree/field order.

    The returned max_ranks values are metadata, not Python legality limits.
    The selected Rust prepare endpoint remains the only build-validity judge.
    """
    executable = Path(binary)
    if not executable.is_file():
        raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_BINARY_MISSING")
    if not 0 < timeout_seconds <= 120:
        raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_TIMEOUT_INVALID")
    try:
        result = subprocess.run(
            [str(executable), "talent-layout", "--class", "druid"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeTalentLayoutError(
            "NATIVE_TALENT_LAYOUT_CLI_FAILED:" + type(exc).__name__
        ) from exc
    if result.returncode != 0:
        raise NativeTalentLayoutError(
            "NATIVE_TALENT_LAYOUT_CLI_REFUSED:" + str(result.returncode)
        )
    try:
        document = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_INVALID_JSON") from exc
    if (
        not isinstance(document, dict)
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
        or document.get("class") != "druid"
        or document.get("ruleset") != "forever"
        or not isinstance(document.get("trees"), list)
        or not document["trees"]
    ):
        raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_CONTRACT_MISMATCH")

    layout: dict[str, list[dict[str, object]]] = {}
    all_fields: set[str] = set()
    for tree in document["trees"]:
        if not isinstance(tree, dict):
            raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_TREE_INVALID")
        key, talents = tree.get("key"), tree.get("talents")
        if (
            not isinstance(key, str)
            or not key
            or key in layout
            or not isinstance(talents, list)
            or not talents
        ):
            raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_TREE_INVALID")
        entries: list[dict[str, object]] = []
        for talent in talents:
            if not isinstance(talent, dict):
                raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_ENTRY_INVALID")
            field, name = talent.get("field"), talent.get("name")
            max_ranks, in_proto = talent.get("max_ranks"), talent.get("in_proto")
            if (
                not isinstance(field, str)
                or not field
                or field in all_fields
                or not isinstance(name, str)
                or not name
                or type(max_ranks) is not int
                or max_ranks < 0
                or type(in_proto) is not bool
            ):
                raise NativeTalentLayoutError("NATIVE_TALENT_LAYOUT_ENTRY_INVALID")
            all_fields.add(field)
            entries.append({
                "field": field, "name": name,
                "max_ranks": max_ranks, "in_proto": in_proto,
            })
        layout[key] = entries
    return layout

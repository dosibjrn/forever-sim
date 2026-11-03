#!/usr/bin/env python3
"""Fail-closed/idempotency checks for the selected-Rust Roots control port."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "port_native_entangling_roots_control",
    HERE / "port_native_entangling_roots_control.py",
)
assert SPEC and SPEC.loader
PORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PORT)


def fixtures() -> dict[str, str]:
    return {
        "src/classes/druid/spells.rs": "pub(crate) mod bear;\n",
        "src/classes/druid/agent.rs": "\n".join(
            old for old, _new, _label in PORT.AGENT_PATCHES
        ),
        "src/core/fight/world_bridge.rs": "\n".join(
            old for old, _new, _label in PORT.WORLD_BRIDGE_PATCHES
        ),
    }


def main() -> int:
    source = fixtures()
    first = {
        path: PORT.port_text(path, contents)
        for path, contents in source.items()
    }
    first[PORT.ROOTS_MODULE_PATH] = PORT.port_text(PORT.ROOTS_MODULE_PATH, "")
    second = {
        path: PORT.port_text(path, contents)
        for path, contents in first.items()
    }
    assert second == first, "NATIVE_ROOTS_CONTROL_PORT_NOT_IDEMPOTENT"
    assert "record_control_attempt" in first["src/classes/druid/spells.rs"] or (
        "record_control_attempt" in first["src/core/fight/world_bridge.rs"]
    )
    assert "native_control_events" in first["src/core/fight/world_bridge.rs"]
    assert "same_clock_control_boundary" in first["src/core/fight/world_bridge.rs"]
    assert "record_control_state" in first["src/classes/druid/agent.rs"]
    assert "EntanglingRoots" in first[PORT.ROOTS_MODULE_PATH]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for path, contents in source.items():
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(contents)
        PORT.main(["port_native_entangling_roots_control.py", str(root)])
        snapshot = {
            path: (root / path).read_text()
            for path in PORT.PATHS
        }
        PORT.main(["port_native_entangling_roots_control.py", str(root)])
        assert snapshot == {
            path: (root / path).read_text()
            for path in PORT.PATHS
        }, "NATIVE_ROOTS_CONTROL_FILE_PORT_NOT_IDEMPOTENT"

    try:
        PORT.port_text("src/classes/druid/spells.rs", "pub(crate) mod unrelated;\n")
    except ValueError as exc:
        assert "SOURCE_DRIFT" in str(exc)
    else:
        raise AssertionError("NATIVE_ROOTS_CONTROL_PORT_MUST_FAIL_CLOSED")

    print("NATIVE_ROOTS_CONTROL_PORT_IDEMPOTENCY_AND_DRIFT_GUARD_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

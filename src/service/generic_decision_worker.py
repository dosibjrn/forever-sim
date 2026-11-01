from __future__ import annotations

"""G50f: a strictly bounded native generic queue child, no legacy projection."""
import argparse
import json
import os
from pathlib import Path

from src.forever_build import configure
from src.version import SOFTWARE_VERSION


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--class", dest="class_name", required=True)
    parser.add_argument("--level", type=int, required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args(argv)
    from src.game.data.forever.queue_capabilities import (
        PINNED_FOREVER_AS_OF, require_native_generic_queue, native_generic_queue_artifact,
    )
    try:
        require_native_generic_queue(args.class_name, args.level)
    except ValueError as exc:
        parser.error(str(exc))
    if args.as_of != PINNED_FOREVER_AS_OF:
        parser.error("native generic queue requires pinned as-of source")
    root = os.environ.get("WOW_SIM_STATE_BASE")
    if not root:
        parser.error("WOW_SIM_STATE_BASE required; standalone publication is forbidden")
    configure(args.as_of, source="explicit_native_generic_queue_job")
    from src.v2.generic_backend import build_partial_generic_records
    records = build_partial_generic_records(class_names=[args.class_name], selected_level=args.level)
    if len(records) != 1:
        raise RuntimeError("native generic producer returned unexpected record count")
    decision = records[0].as_dict()
    if (decision.get("backend", {}).get("id") != "generic"
            or decision.get("provenance", {}).get("source") != "generic_backend_native"
            or decision.get("provenance", {}).get("legacy_fallback") is not False):
        raise RuntimeError("native generic Decision authority not proven")
    envelope = {
        "schema_version": 1, "complete": True,
        "execution_authority": "native_generic_decision",
        "legacy_fallback": False, "producer_version": SOFTWARE_VERSION,
        "forever_build_as_of": args.as_of, "decision": decision,
    }
    output = Path(root) / native_generic_queue_artifact(args.class_name, args.level)
    output.parent.mkdir(parents=True, exist_ok=True)
    # The immutable attempt root is private until Scheduler's atomic pointer swap.
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

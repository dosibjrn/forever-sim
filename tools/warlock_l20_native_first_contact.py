#!/usr/bin/env python3
"""Read-only Warlock L20 first contact with the pinned MythicSim Rust API.

This is a diagnostic, NOT a P3 gate or a second source of Warcraft truth.
The CLI reports native source coverage and refuses to promote unknown item
proficiency, unverified spell learning or unexecuted L20 combat to a PASS.

Usage:
    python tools/warlock_l20_native_first_contact.py --binary PATH/forever-engine
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Callable


class NativeWarlockProbeError(ValueError):
    """The selected Rust binary or its response cannot be trusted."""


def _invoke(binary: str, args: list[str], runner: Callable) -> dict:
    try:
        proc = runner(
            [binary, *args], capture_output=True, text=True,
            timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeWarlockProbeError(
            "NATIVE_RUST_COMMAND_UNAVAILABLE:" + args[0]
        ) from exc
    if proc.returncode != 0:
        raise NativeWarlockProbeError(
            "NATIVE_RUST_COMMAND_FAILED:" + args[0] + ":"
            + str(proc.stderr).strip()[-240:]
        )
    try:
        value = json.loads(proc.stdout)
    except (TypeError, ValueError) as exc:
        raise NativeWarlockProbeError(
            "NATIVE_RUST_INVALID_JSON:" + args[0]
        ) from exc
    if not isinstance(value, dict):
        raise NativeWarlockProbeError(
            "NATIVE_RUST_INVALID_OBJECT:" + args[0]
        )
    return value


def diagnose_warlock_l20(
    binary: str, *, runner: Callable = subprocess.run
) -> dict:
    """Query two independent native APIs, return only directly observed facts.

    No Python class proficiency rules, gear score, spell level extrapolation,
    P3 acceptance or synthetic simulated combat is performed.
    """
    options = _invoke(
        binary, ["options", "--class", "warlock", "--level", "20"], runner,
    )
    if options.get("schema_version") != 1 or (
        options.get("class"), options.get("level")
    ) != ("warlock", 20):
        raise NativeWarlockProbeError("NATIVE_OPTIONS_WRONG_CLASS_OR_LEVEL")
    revision = options.get("source_revision")
    if not isinstance(revision, str) or not revision:
        raise NativeWarlockProbeError("NATIVE_OPTIONS_REVISION_MISSING")
    coverage = options.get("coverage")
    talents = options.get("talents")
    spells = options.get("spells")
    items = options.get("items")
    if not isinstance(coverage, dict) or not isinstance(talents, dict):
        raise NativeWarlockProbeError("NATIVE_OPTIONS_COVERAGE_MISSING")
    if not isinstance(spells, list) or not isinstance(items, list):
        raise NativeWarlockProbeError("NATIVE_OPTIONS_SOURCE_ROWS_MISSING")
    # Level 20 has 11 talent points under the client's standard 10+ rule.
    # This is an API integrity expectation, not an independently validated
    # talent allocation or a source-rank acquisition check.
    if (talents.get("status") != "ok"
            or talents.get("points_available") != 11
            or not isinstance(talents.get("trees"), list)
            or len(talents["trees"]) != 3):
        raise NativeWarlockProbeError("NATIVE_L20_TALENTS_INVALID")
    native_gear = _invoke(
        binary,
        ["item-options", "--class", "warlock", "--level", "20",
         "--spec", "unrestricted", "--slot", "all"],
        runner,
    )
    if (
        native_gear.get("class"), native_gear.get("level"),
        native_gear.get("spec"), native_gear.get("slot"),
    ) != ("warlock", 20, "unrestricted", "all"):
        raise NativeWarlockProbeError("NATIVE_ITEM_OPTIONS_WRONG_REQUEST")

    raw_eligibility = coverage.get("item_eligibility_complete")
    raw_learning = coverage.get("spell_learnability_complete")
    if type(raw_eligibility) is not bool or type(raw_learning) is not bool:
        raise NativeWarlockProbeError("NATIVE_OPTIONS_COVERAGE_INVALID")
    item_status = native_gear.get("status")
    refusal = native_gear.get("refusal")
    if item_status == "refused":
        if not isinstance(refusal, dict) or not refusal.get("code"):
            raise NativeWarlockProbeError("NATIVE_ITEM_REFUSAL_MALFORMED")
        eligible_count = 0
    elif item_status in ("ok", "empty", "partial_level_unknown"):
        native_items = native_gear.get("items")
        if not isinstance(native_items, list):
            raise NativeWarlockProbeError("NATIVE_ITEM_OPTIONS_ITEMS_MISSING")
        eligible_count = len(native_items)
        if not raw_eligibility or item_status == "partial_level_unknown":
            # A partially qualified list must never become legal suggestions.
            eligible_count = 0
    else:
        raise NativeWarlockProbeError("NATIVE_ITEM_OPTIONS_UNKNOWN_STATUS")
    ready = (
        raw_eligibility and raw_learning
        and item_status in ("ok", "empty")
        and native_gear.get("required_level_supported") is True
    )
    missing = []
    if not raw_eligibility or item_status not in ("ok", "empty"):
        missing.append("WARLOCK_L20_NATIVE_ITEM_PROFICIENCY")
    if not raw_learning:
        missing.append("WARLOCK_L20_SPELL_LEARNABILITY")
    # The L20 prepared-actor and real paid combat must be independently proven;
    # get_options is only source discovery, never combat execution.
    missing.append("WARLOCK_L20_NATIVE_PREPARED_ACTOR_AND_PAID_COMBAT")
    return {
        "checkpoint": "warlock:20:unrestricted",
        "source": "selected_mythicsim_rust",
        "source_revision": revision,
        "source_options_level": 20,
        "status": "BLOCKED",
        "gate_acceptance": "NOT_RUN",
        "native_l20_combat": "NOT_EXECUTED",
        "item_source_ready": bool(raw_eligibility and item_status in ("ok", "empty")),
        "spell_learning_source_ready": raw_learning,
        "native_gear_status": item_status,
        "native_gear_refusal": refusal if item_status == "refused" else None,
        "native_gear_eligible_count": eligible_count,
        "native_gear_unverified_count": len(items) if not raw_eligibility else 0,
        "native_spell_family_rows": len(spells),
        "talent_trees": len(talents["trees"]),
        "talent_points": talents["points_available"],
        "all_source_dimensions_ready": ready,
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument(
        "--require-ready", action="store_true",
        help="Return 3 if native source or combat proof is still missing",
    )
    args = parser.parse_args()
    try:
        report = diagnose_warlock_l20(str(args.binary))
    except NativeWarlockProbeError as exc:
        print(json.dumps({
            "checkpoint": "warlock:20:unrestricted", "status": "ERROR",
            "reason": str(exc),
        }, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    # Completed diagnostics exit 0, missing L20 gate readiness is NEVER PASS.
    return 3 if args.require_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())

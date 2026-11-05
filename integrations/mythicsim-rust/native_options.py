"""Thin source-only bridge to the selected MythicSim Rust `get_options` API.

Rust owns class/level/item/talent/spell mechanics. Never infer spell learnability,
equipment proficiency, or build legality in Python. Exact candidates are still
prepared and paid in the native engine; this only expands the proposal domain.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable


class NativeOptionsError(ValueError):
    """The selected Rust get_options boundary did not provide valid source data."""


def query_native_options(
    binary: str | Path, class_key: str, level: int, *,
    runner: Callable = subprocess.run,
) -> dict:
    """Read one native source snapshot with fail-closed CLI/contract handling."""
    class_key = str(class_key).lower()
    if not class_key or type(level) is not int or not 1 <= level <= 60:
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_REQUEST")
    cmd = [str(binary), "options", "--class", class_key, "--level", str(level)]
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeOptionsError("NATIVE_OPTIONS_EXECUTION_FAILED") from exc
    if result.returncode:
        raise NativeOptionsError("NATIVE_OPTIONS_EXECUTION_FAILED:"
                                 + str(result.stderr or "")[-500:])
    try:
        source = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_JSON") from exc
    if (not isinstance(source, dict)
            or source.get("schema_version") != 1
            or source.get("class") != class_key
            or source.get("level") != level
            or not isinstance(source.get("spells"), list)
            or not isinstance(source.get("items"), list)
            or not isinstance(source.get("talents"), dict)
            or not isinstance(source.get("coverage"), dict)
            or not isinstance(source.get("source_revision"), str)):
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_RESPONSE")
    coverage = source["coverage"]
    if (type(coverage.get("spell_learnability_complete")) is not bool
            or type(coverage.get("item_eligibility_complete")) is not bool
            or coverage.get("talent_prerequisites_complete") is not True
            or source["talents"].get("status") != "ok"
            or not isinstance(source["talents"].get("trees"), list)
            or len(source["talents"]["trees"]) != 3):
        raise NativeOptionsError("NATIVE_OPTIONS_INVALID_COVERAGE")
    for item in source["items"]:
        if not isinstance(item, dict) or type(item.get("item_id")) is not int:
            raise NativeOptionsError("NATIVE_OPTIONS_INVALID_ITEM")
        if item.get("eligibility") == "native_eligible":
            native = item.get("native")
            if (not isinstance(native, dict)
                    or native.get("item_id") != item["item_id"]
                    or not isinstance(native.get("slot"), str)
                    or not native["slot"]):
                raise NativeOptionsError("NATIVE_OPTIONS_INVALID_NATIVE_ITEM")
        elif item.get("eligibility") == "proficiency_unverified":
            if item.get("native") is not None:
                raise NativeOptionsError("NATIVE_OPTIONS_UNVERIFIED_AS_NATIVE")
        else:
            raise NativeOptionsError("NATIVE_OPTIONS_UNKNOWN_ELIGIBILITY")
    return source


def native_equipment_proposals(source: dict, base_items: list[dict]) -> dict[int, list[dict]]:
    """Propose Rust-source items without making a Python legality decision.

    Verified entries carry a native slot; use it only where a known equipped
    native item provides the same slot. Unverified entries have *no native
    slot*. Propose them at every structural equipment position, including
    empty or unknown anchors, and let the Rust evaluator accept/refuse the
    complete request. This is intentionally NOT a Python equip rule.
    """
    verified = [entry["native"] for entry in source["items"]
                if entry["eligibility"] == "native_eligible"]
    unverified_ids = [entry["item_id"] for entry in source["items"]
                      if entry["eligibility"] == "proficiency_unverified"]
    by_id = {entry["item_id"]: entry for entry in verified}
    by_slot: dict[str, list[dict]] = {}
    for native in verified:
        by_slot.setdefault(native["slot"], []).append(native)
    proposals: dict[int, list[dict]] = {}
    for index, equipped in enumerate(base_items):
        if not isinstance(equipped, dict) or type(equipped.get("id")) is not int:
            continue  # malformed request structure, not a gameplay judgement
        item_id = equipped["id"]
        anchor = by_id.get(item_id)
        verified_ids = ([entry["item_id"] for entry in by_slot[anchor["slot"]]]
                        if anchor is not None else [])
        # No proficiency or slot inference for unverified source records.
        # The native prepare/simulate path is the ONLY equip authority.
        proposed_ids = dict.fromkeys([*verified_ids, *unverified_ids])
        options = [{"id": candidate_id} for candidate_id in proposed_ids
                   if candidate_id != item_id]
        if options:
            proposals[index] = options
    return proposals
